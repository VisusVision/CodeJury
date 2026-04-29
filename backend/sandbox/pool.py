"""
pool.py — Sandbox Container Pool

Manages N agentgrade-sandbox containers.
Each container exposes a REST API (POST /api/execute).
After each execution the container is cleaned and returned to the pool.
"""
import queue
import threading
import time
from dataclasses import dataclass

try:
    import requests as _requests
except ModuleNotFoundError:
    _requests = None  # type: ignore

try:
    import docker as _docker
except ModuleNotFoundError:
    _docker = None  # type: ignore


def _log(msg: str) -> None:
    print(f"[pool] {msg}", flush=True)


@dataclass
class ContainerSlot:
    """Represents a single container in the pool."""
    container: object
    url: str
    port: int


class SandboxPool:
    """
    Pool that manages N sandbox containers.

    Usage:
        pool = SandboxPool(image="agentgrade-sandbox", pool_size=10)
        pool.initialize()   # call at application startup
        slot = pool.acquire()
        try:
            # send HTTP request to slot.url
            ...
        finally:
            pool.release(slot)
        pool.shutdown()     # call at application shutdown
    """

    def __init__(
        self,
        image: str = "agentgrade-sandbox",
        pool_size: int = 10,
        base_port: int = 8181,
        acquire_timeout: float = 30.0,
    ):
        self.image = image
        self.pool_size = pool_size
        self.base_port = base_port
        self.acquire_timeout = acquire_timeout

        self._available: queue.Queue = queue.Queue()
        self._slots: list[ContainerSlot] = []
        self._client = None
        self._initialized = False
        self._lock = threading.Lock()

    # ── Initialization ────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Start all containers in parallel."""
        if _docker is None:
            _log("'docker' paketi bulunamadi — sandbox devre disi")
            return
        if _requests is None:
            _log("'requests' paketi bulunamadi — sandbox devre disi")
            return

        try:
            self._client = _docker.from_env()
            self._client.ping()
        except Exception as e:
            _log(f"Docker baglantisi kurulamadi: {e} — sandbox devre disi")
            return

        self._cleanup_existing()

        results = [None] * self.pool_size

        def start_one(i):
            port = self.base_port + i
            try:
                slot = self._create_slot(port)
                results[i] = slot
            except Exception as e:
                _log(f"Container {i+1} (port {port}) baslatılamadi: {e}")

        threads = [
            threading.Thread(target=start_one, args=(i,), daemon=True)
            for i in range(self.pool_size)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for slot in results:
            if slot is not None:
                self._slots.append(slot)
                self._available.put(slot)

        self._initialized = True
        _log(
            f"{len(self._slots)}/{self.pool_size} container hazir "
            f"(port {self.base_port}-{self.base_port + self.pool_size - 1})"
        )

    def _cleanup_existing(self) -> None:
        """Remove leftover containers from a previous run."""
        try:
            existing = self._client.containers.list(
                all=True,
                filters={"name": "agentgrade-pool-"}
            )
            for c in existing:
                try:
                    c.stop(timeout=1)
                    c.remove(force=True)
                except Exception:
                    pass
        except Exception:
            pass

    def _create_slot(self, port: int) -> ContainerSlot:
        """Start a container and return a slot after it passes the health check."""
        container = self._client.containers.run(
            image=self.image,
            name=f"agentgrade-pool-{port}",
            detach=True,
            ports={"8080/tcp": port},
            read_only=True,
            tmpfs={"/tmp": "size=50m,exec", "/run": "size=10m"},
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            cap_add=["SETUID", "SETGID"],
            mem_limit="512m",
            memswap_limit="512m",
            cpu_period=100000,
            cpu_quota=100000,
            pids_limit=64,
            remove=False,
        )

        url = f"http://localhost:{port}"
        self._wait_healthy(url, timeout=45.0)
        _log(f"Container hazir -> {url}")
        return ContainerSlot(container=container, url=url, port=port)

    def _wait_healthy(self, url: str, timeout: float = 45.0) -> None:
        """Block until the container responds to GET /api/health."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = _requests.get(f"{url}/api/health", timeout=2.0)
                if resp.status_code == 200 and resp.json().get("status") == "ok":
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"Container {url} saglik kontrolu zamanası ({timeout}s)")

    # ── Usage ─────────────────────────────────────────────────────────────────

    def acquire(self) -> ContainerSlot:
        """
        Acquire a free container from the pool.
        Blocks up to acquire_timeout seconds if all containers are busy.
        """
        if not self._initialized or not self._slots:
            raise RuntimeError("Sandbox pool baslatilmamis veya hic container yok")
        try:
            return self._available.get(timeout=self.acquire_timeout)
        except queue.Empty:
            raise TimeoutError(
                f"Tum sandbox container'lari mesgul "
                f"({self.acquire_timeout}s timeout asildi)"
            )

    def release(self, slot: ContainerSlot, ok: bool = True) -> None:
        """
        Return a container to the pool.
        If ok=False the container is considered unhealthy and replaced.
        """
        if ok and self._is_healthy(slot):
            self._available.put(slot)
            return

        _log(f"Container sagliksiz, yenileniyor: {slot.url}")
        threading.Thread(
            target=self._replace_slot, args=(slot,), daemon=True
        ).start()

    def _replace_slot(self, old_slot: ContainerSlot) -> None:
        """Stop the old container and start a fresh one on the same port."""
        try:
            old_slot.container.stop(timeout=2)
            old_slot.container.remove(force=True)
        except Exception:
            pass
        try:
            new_slot = self._create_slot(old_slot.port)
            with self._lock:
                idx = next(
                    (i for i, s in enumerate(self._slots) if s.port == old_slot.port),
                    None
                )
                if idx is not None:
                    self._slots[idx] = new_slot
            self._available.put(new_slot)
            _log(f"Container yenilendi: {new_slot.url}")
        except Exception as e:
            _log(f"Container yenilenemedi (port {old_slot.port}): {e}")

    def _is_healthy(self, slot: ContainerSlot) -> bool:
        try:
            resp = _requests.get(f"{slot.url}/api/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Stop and remove all containers."""
        count = 0
        for slot in self._slots:
            try:
                slot.container.stop(timeout=2)
                slot.container.remove(force=True)
                count += 1
            except Exception:
                pass
        self._slots.clear()
        while not self._available.empty():
            try:
                self._available.get_nowait()
            except queue.Empty:
                break
        _log(f"{count} container kapatildi")

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._initialized and len(self._slots) > 0

    @property
    def available_count(self) -> int:
        return self._available.qsize()
