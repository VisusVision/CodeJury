"""
executor.py — Güvenli Kod Çalıştırma Motoru

Sorumluluğu: Verilen komutu izole bir process olarak çalıştırmak,
kaynak limitlerini (CPU, RAM, disk, process) uygulamak ve sonuçları
ExecutionResult nesnesi olarak döndürmek.

Bu modülü doğrudan kullanmak yerine runners.py üzerinden kullanın.
"""
import os, sys, signal, resource, subprocess, tempfile, shutil, time, threading, psutil, json, stat
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Veri Modelleri ────────────────────────────────────────────────────────────

@dataclass
class ResourceLimits:
    """
    Bir kod çalıştırması için kaynak limitleri.
    Arayüzden veya API'den gelen 'limits' alanı bu sınıfa dönüştürülür.
    """
    cpu_time_sec: int = 10           # Maksimum CPU kullanim suresi (saniye)
    wall_time_sec: int = 15          # Maksimum gercek gecen sure (saniye)
    memory_mb: int = 256             # Maksimum RAM kullanimi (MB)
    disk_mb: int = 50                # Maksimum disk yazma kotasi (MB)
    max_processes: int = 32          # Maksimum aciilabilecek process sayisi
    max_open_files: int = 64         # Maksimum acik dosya sayisi
    max_output_bytes: int = 1_000_000  # Maksimum stdout+stderr boyutu (1 MB)
    network_access: bool = False     # Ag erisimi (varsayilan: kapali)


@dataclass
class ExecutionResult:
    """
    Bir kod calistirmasinin tum sonuclarini tutan veri sinifi.
    orchestrator.py bu nesneyi alip JSON raporuna donusturur.
    """
    success: bool = False            # Kod hatasiz calisti mi (exit_code==0 ve limit asilmadi)
    exit_code: int = -1              # Process'in cikis kodu
    stdout: str = ""                 # Standart cikti
    stderr: str = ""                 # Hata ciktisi
    error: str = ""                  # Sandbox seviyesinde hata mesaji
    wall_time_ms: float = 0          # Gercek gecen sure (milisaniye)
    cpu_time_ms: float = 0           # CPU kullanim suresi (milisaniye)
    peak_memory_mb: float = 0        # Tepe bellek kullanimi (MB)
    timed_out: bool = False          # Wall clock veya CPU limiti asildi mi
    memory_exceeded: bool = False    # RAM limiti asildi mi
    output_truncated: bool = False   # Cikti 1MB limitinden kesildi mi
    compile_stdout: str = ""         # Derleme stdout'u (sadece C/C++)
    compile_stderr: str = ""         # Derleme stderr'i (sadece C/C++)
    compile_success: bool = True     # Derleme basarili mi (Python icin her zaman True)
    language: str = ""               # Calistirilan dil
    executed_at: float = field(default_factory=time.time)  # Unix timestamp

    def to_dict(self): return asdict(self)
    def to_json(self): return json.dumps(self.to_dict(), indent=2)


# ── RAM Izleyici ──────────────────────────────────────────────────────────────

class ResourceMonitor:
    """
    Arka planda calisan thread. Calisan process'in RAM kullanimini her 100ms'de
    bir kontrol eder. Limit asilirsa tum process grubunu oldurur.

    Neden gerekli: RLIMIT_AS sanal bellegi sinirlar ama bazi durumlarda
    (or: Python'da bytearray) fiziksel bellek RLIMIT_AS'i asabilir.
    Bu izleyici fiziksel bellegi dogrudan olcer.
    """
    def __init__(self, pid, limits, result):
        self.pid = pid
        self.limits = limits
        self.result = result
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._monitor, daemon=True)

    def start(self): self._thread.start()
    def stop(self): self._stop.set(); self._thread.join(timeout=2)

    def _monitor(self):
        mem_limit = self.limits.memory_mb * 1024 * 1024
        peak = 0
        while not self._stop.is_set():
            try:
                proc = psutil.Process(self.pid)
                # Ana process + tum alt process'lerin toplam RAM'ini olc
                all_p = [proc] + proc.children(recursive=True)
                total = sum(p.memory_info().rss for p in all_p if p.is_running())
                if total > peak:
                    peak = total
                if total > mem_limit:
                    # Limit asildi: sonucu isaretl ve tum process grubunu oldur
                    self.result.memory_exceeded = True
                    self.result.peak_memory_mb = peak / (1024 * 1024)
                    self._kill_tree(proc)
                    return
                self.result.peak_memory_mb = peak / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break  # Process zaten oldu
            self._stop.wait(0.1)  # 100ms bekle

    def _kill_tree(self, proc):
        """Process ve tum cocuklarini oldur."""
        try:
            for child in proc.children(recursive=True):
                try: child.kill()
                except: pass
            proc.kill()
        except: pass


# ── Kaynak Limiti Uygulama ────────────────────────────────────────────────────

import ctypes as _ctypes

# Linux kernel sabiti: yeni network namespace olusturmak icin
_CLONE_NEWNET = 0x40000000
_libc = _ctypes.CDLL("libc.so.6", use_errno=True)


def _make_preexec(limits, for_compile=False):
    """
    subprocess.Popen'in preexec_fn parametresi icin fonksiyon uretir.

    Nasil calisir:
    1. fork()  →  process kopyalanir (child dogar)
    2. preexec_fn calisir (child'da, exec'ten once)
    3. exec()  →  asil komut calisir

    Limitler kernel tarafindan uygulanir, kod ne yaparsa yapsin asamaz.
    """
    def preexec():
        # Tam ag izolasyonu: yeni network namespace olustur
        # Bu sayede child process hicbir network arayuzune erisemez.
        # API'nin kendisi etkilenmez, sadece calistirilan kod izole olur.
        # Derleyici (gcc/g++) icin bu atlaniyor cunku paket indirmeye gerek yok
        # ve ek guvenlik riski de yok.
        if not for_compile:
            _libc.unshare(_CLONE_NEWNET)

        # CPU limiti: kernel seviyesinde hard limit
        cpu = limits.cpu_time_sec
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))

        # Sanal adres alani limiti (= RAM limiti)
        mem = limits.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))

        # Disk yazma limiti
        disk = limits.disk_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (disk, disk))

        # Fork bomb korumasi: aciilabilecek max process sayisi
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes))

        # Maksimum acik dosya sayisi
        resource.setrlimit(resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files))

        # Core dump olusturmayı engelle (guvenlik)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        # Yeni process group olustur (sonradan tum grubu oldürebilmek icin)
        os.setsid()

    return preexec


# ── Ana Executor Sinifi ───────────────────────────────────────────────────────

class SandboxExecutor:
    """
    Tek bir komutu guvenli sekilde calistiran sinif.
    Dogrudan kullanim icin degil; runners.py icerisindeki
    PythonRunner, CRunner, CppRunner tarafindan kullanilir.
    """
    def __init__(self, limits=None):
        self.limits = limits or ResourceLimits()

    def run(self, cmd, workdir, stdin_data=None, env_extra=None, language="", for_compile=False):
        """
        Verilen komutu izole ortamda calistirir.

        Parametreler:
            cmd        : Calistirilacak komut listesi, or: ["python3", "solution.py"]
            workdir    : Calisma dizini (gecici, izole klasor)
            stdin_data : Koda stdin olarak verilecek veri (test senaryolari icin)
            env_extra  : Eklenecek ek ortam degiskenleri
            language   : Raporlama icin dil adi
            for_compile: Derleme adimi mi?
        """
        result = ExecutionResult(language=language)

        # Guvenli ve minimal ortam degiskenleri
        # Sistem PATH'inden fazlasina erisim yok, HOME izole klasor
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": workdir,
            "TMPDIR": workdir,
            "LANG": "en_US.UTF-8"
        }
        if env_extra:
            env.update(env_extra)
        # Not: ag izolasyonu preexec_fn icinde unshare(CLONE_NEWNET) ile saglanir.
        # no_proxy env degiskeni artik gerekli degil.

        preexec = _make_preexec(self.limits, for_compile)
        start = time.perf_counter()

        # Process'i baslat
        try:
            proc = subprocess.Popen(
                cmd, cwd=workdir, env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=preexec,
                close_fds=True
            )
        except FileNotFoundError as e:
            result.error = f"Komut bulunamadi: {e}"
            result.compile_success = False
            return result
        except Exception as e:
            result.error = f"Process baslatma hatasi: {e}"
            return result

        # RAM izleyiciyi arka planda baslat
        monitor = ResourceMonitor(proc.pid, self.limits, result)
        monitor.start()

        # Wall clock timeout ile process'i bekle
        try:
            stdin_bytes = stdin_data.encode() if stdin_data else None
            out, err = proc.communicate(input=stdin_bytes, timeout=self.limits.wall_time_sec)
        except subprocess.TimeoutExpired:
            # Wall clock suresi doldu, process'i zorla oldur
            result.timed_out = True
            try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except: proc.kill()
            out, err = proc.communicate()
        except Exception as e:
            result.error = f"Calistirma hatasi: {e}"
            proc.kill()
            out, err = b"", b""
        finally:
            monitor.stop()

        # Sure ve CPU kullanimini hesapla
        result.wall_time_ms = (time.perf_counter() - start) * 1000
        try:
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            result.cpu_time_ms = (usage.ru_utime + usage.ru_stime) * 1000
        except:
            pass

        # Ciktiyi 1MB ile sinirla
        max_out = self.limits.max_output_bytes
        if len(out) + len(err) > max_out:
            result.output_truncated = True
            out = out[:max_out // 2]
            err = err[:max_out // 2]

        result.stdout = out.decode("utf-8", errors="replace")
        result.stderr = err.decode("utf-8", errors="replace")
        result.exit_code = proc.returncode if proc.returncode is not None else -1

        # SIGXCPU (exit_code -24): CPU limiti kernel tarafindan asildi
        if result.exit_code == -24:
            result.timed_out = True

        # Python MemoryError veya sistem "Cannot allocate memory" hatasi
        if "MemoryError" in result.stderr or "Cannot allocate memory" in result.stderr:
            result.memory_exceeded = True

        # Genel basari kontrolu: limit asilmadiysa ve exit_code 0 ise basarili
        result.success = (
            not result.timed_out and
            not result.memory_exceeded and
            result.exit_code == 0
        )
        return result

    def run_with_compile(self, compile_cmd, run_cmd, workdir, stdin_data=None, language=""):
        """
        C ve C++ icin: once derle, basariliysa calistir.

        Derleme icin ayri, genis limitler kullanilir cunku
        GCC/G++'in kendisi fazla RAM ve disk kullanir.
        Kullanici kodunun limitleri sadece calistirma asamasinda uygulanir.
        """
        # Derleme limitleri (compiler'in kendi ihtiyaci icin daha genis)
        compile_limits = ResourceLimits(
            cpu_time_sec=30,
            wall_time_sec=60,
            memory_mb=512,
            disk_mb=100,
            max_processes=128,
            max_open_files=256
        )
        compile_executor = SandboxExecutor(compile_limits)
        compile_result = compile_executor.run(compile_cmd, workdir, language=language, for_compile=True)

        result = ExecutionResult(language=language)
        result.compile_stdout = compile_result.stdout
        result.compile_stderr = compile_result.stderr

        # Derleme basarisiz olduysa calistirma asamasina gecme
        if not compile_result.success or compile_result.exit_code != 0:
            result.compile_success = False
            result.error = "Derleme basarisiz"
            result.stderr = compile_result.stderr
            result.stdout = compile_result.stdout
            return result

        result.compile_success = True

        # Calistirma: kullanici limitlerini uygula
        run_result = self.run(run_cmd, workdir, stdin_data, language=language)

        # Calistirma sonuclarini ana result'a kopyala
        for attr in [
            'success', 'exit_code', 'stdout', 'stderr', 'error',
            'wall_time_ms', 'cpu_time_ms', 'peak_memory_mb',
            'timed_out', 'memory_exceeded', 'output_truncated', 'executed_at'
        ]:
            setattr(result, attr, getattr(run_result, attr))

        return result


# ── Izole Calisma Dizini ──────────────────────────────────────────────────────

class IsolatedWorkdir:
    """
    Context manager: gecici ve izole bir klasor olusturur,
    is bitince otomatik olarak siler.

    Kullanim:
        with IsolatedWorkdir("py_") as workdir:
            # workdir = "/tmp/py_abc123" gibi bir klasor
            # buraya kod dosyasi yaz, calistir
        # bloktan cikinca klasor silinir, iz kalmaz
    """
    def __init__(self, prefix="sandbox_"):
        self.prefix = prefix
        self.path = None

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix=self.prefix)
        os.chmod(self.path, stat.S_IRWXU)  # Sadece sahibi erisebilir
        return self.path

    def __exit__(self, *args):
        if self.path and os.path.exists(self.path):
            shutil.rmtree(self.path, ignore_errors=True)
