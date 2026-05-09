# CodeJury — Kurulum Rehberi

Bu doküman, CodeJury çoklu-ajan kod değerlendirme sistemini sıfırdan
kurmak için gereken tüm adımları içerir. Otomatik kurulum scriptlerinin
yanı sıra manuel adımlar da açıklanmıştır.

> Hızlı yol istiyorsanız doğrudan [Otomatik Kurulum](#3-otomatik-kurulum)
> bölümüne geçebilirsiniz.

---

## 1. Sistem Önkoşulları

| Bileşen | Minimum Sürüm | Zorunlu mu? | Not |
|---------|---------------|-------------|-----|
| **Python** | 3.11 | Evet | Backend ve ajanlar için |
| **Node.js** | 18 | Evet | Frontend (Vite + React) için |
| **npm** | 9+ | Evet | Node.js ile birlikte gelir |
| **Docker Desktop / Engine** | 24+ | Sandbox için zorunlu | Demo mode'da opsiyonel |
| **docker compose v2** | — | Sandbox için zorunlu | Docker Desktop ile birlikte gelir |
| **Ollama** | son sürüm | LLM için önerilir | Olmadan ajanlar çalışmaz |
| **Git** | herhangi | Evet | Klonlama / sürüm kontrol |
| **RAM** | 8 GB | — | LLM modelleri için 16 GB önerilir |
| **Disk** | 10 GB boş | — | Sandbox imajı + Ollama modelleri |

### İşletim Sistemi Notları

- **Windows 10/11**: Docker Desktop + WSL2 backend önerilir.
- **macOS (Intel/Apple Silicon)**: Docker Desktop önerilir.
- **Linux (Ubuntu 22.04+)**: `docker.io` + `docker-compose-plugin` paketleri.

### Resmi Kurulum Linkleri

- Python — <https://www.python.org/downloads/>
- Node.js — <https://nodejs.org/>
- Docker Desktop — <https://www.docker.com/products/docker-desktop/>
- Ollama — <https://ollama.com/download>

---

## 2. Önkoşulları Doğrulama

Sisteminizde gerekli araçların kurulu olup olmadığını hızlıca kontrol
etmek için, **hiçbir şey kurmadan** çalışan bir doğrulama scripti
hazırlandı. Yalnızca Node.js gerektirir:

```bash
node scripts/check-prereqs.mjs
# veya
npm run check:prereqs
```

Çıktı örneği:

```
[OK]    Repo               Beklenen tum dosyalar mevcut.
[OK]    Env                .env mevcut.
[OK]    Python             python 3.12.0
[OK]    Node.js            v20.10.0
[OK]    npm                10.2.3
[OK]    Docker             Docker version 27.0.3
[OK]    docker compose     Docker Compose version v2.29.0
[OK]    Ollama servis      ollama version is 0.3.6 - http://localhost:11434 calisiyor
```

`[ERROR]` satırı görünüyorsa o önkoşul **zorunludur** ve
kurulumu tamamlanmadan devam edemez. `[WARN]` satırları ise opsiyonel
veya geçici sorunları (örn. Docker daemon kapalı) bildirir.

---

## 3. Otomatik Kurulum

### 3.1 Windows (PowerShell)

```powershell
# Tam kurulum (Docker + Ollama + Postgres dahil)
powershell -ExecutionPolicy Bypass -File scripts\install.ps1

# Yalnızca demo mode (Docker'sız hızlı deneme)
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -DemoMode

# Postgres veya sandbox derlemesini atla
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -NoPostgres -NoSandbox
```

### 3.2 Linux / macOS

```bash
# Tam kurulum
bash scripts/install.sh

# Demo mode
bash scripts/install.sh --demo

# Sadece bağımlılıkları kur, Docker servislerini başlatma
bash scripts/install.sh --no-postgres --no-sandbox --no-ollama
```

### 3.3 npm Kısayolları

```bash
npm run check:prereqs   # Sadece doğrulama
npm run setup           # Platforma göre otomatik kurulum (full mode)
npm run setup:demo      # Platforma göre otomatik kurulum (demo mode)
```

### Scriptin Yaptığı Adımlar

1. **Önkoşul kontrolü**: Python, Node, npm, Docker, docker compose, Ollama — eksikse renkli uyarı verir, zorunlu olanlar eksikse durur.
2. **`.env` hazırlığı**: `.env` yoksa `.env.example` dosyasından kopyalar.
3. **Python venv**: `.venv` oluşturur; **bozuk, eksik veya başka bilgisayardan kopyalanmış**
   `.venv` algılanırsa silinip yeniden oluşturulur. `python -m pip` ile
   `requirements.txt` kurulur (taşınabilir Python sürümleriyle uyumlu).
4. **npm install**: `frontend/` klasöründe çalıştırır.
5. **Sandbox imajı**: `docker build -t agentgrade-sandbox sandbox-images/agentgrade/`.
6. **PostgreSQL + Redis**: `docker compose up -d postgres redis`.
7. **Ollama modelleri**: `ollama pull qwen2.5:7b` ve `ollama pull qwen2.5-coder:7b`.
8. Sonunda renkli özet (uyarı/hata listesi) yazdırır.

> **Önemli:** `--demo` / `-DemoMode` parametresi 5–7. adımları atlar
> ve `.env` içinde `DEMO_MODE=1` yapar. Bu modda PostgreSQL yerine
> bellek-içi demo store kullanılır. Kullanıcılar:
> Öğretmen `demo@agentgrade.local` / `demo123`,
> Öğrenci `20240001` / `11111111111`.

---

## 4. Manuel Kurulum

Otomatik scripti kullanmak istemiyorsanız:

### 4.1 Bağımlılıklar

```bash
# Python sanal ortam
python -m venv .venv
# Windows: .\.venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### 4.2 .env Dosyası

```bash
cp .env.example .env       # Linux/macOS
copy .env.example .env     # Windows
```

Düzenlenebilir alanlar:

| Anahtar | Varsayılan | Açıklama |
|---------|------------|----------|
| `DATABASE_URL` | `postgresql://semas:12345@localhost:5432/agent_db` | Postgres bağlantısı |
| `REDIS_URL` | `redis://localhost:6379/0` | Analiz is kuyrugu baglantisi |
| `ANALYSIS_QUEUE_NAME` | `stream:analysis_jobs` | Redis Streams analiz kuyrugu |
| `LLM_PROVIDER` | `ollama` | `ollama` veya `nvidia_nim`; NIM secilirse ajanlar NVIDIA API'ye gider |
| `LLM_GENERAL_PROVIDER` | bos | Chatbot/rubrik icin provider override; bos ise `LLM_PROVIDER` kullanilir |
| `LLM_CODER_PROVIDER` | bos | Kod degerlendirme ajanlari icin provider override; bos ise `LLM_PROVIDER` kullanilir |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama servisi |
| `OLLAMA_GENERAL_MODEL` | `qwen2.5:7b` | Genel sohbet/öneri LLM model adı |
| `OLLAMA_CODER_MODEL` | `qwen2.5-coder:7b` | Kod değerlendirme ajanları için LLM model adı |
| `NVIDIA_NIM_API_KEY` | bos | `LLM_PROVIDER=nvidia_nim` modunda kullanilan API key |
| `NVIDIA_NIM_GENERAL_MODEL` | `qwen/qwen2.5-coder-32b-instruct` | Chatbot, rubrik ve genel LLM isleri |
| `NVIDIA_NIM_CODER_MODEL` | `qwen/qwen2.5-coder-32b-instruct` | Kod degerlendirme ajanlari |
| `NVIDIA_NIM_RPM_LIMIT` | `35` | Dakika basi NIM istek freni; `0` sinirsiz |
| `NVIDIA_NIM_NUM_PREDICT` | `3072` | NIM JSON cevaplari icin varsayilan maksimum token |
| `SANDBOX_POOL_SIZE` | `10` | Önyüklenecek konteyner sayısı |
| `DEMO_MODE` | `0` | `1` ise PostgreSQL'siz çalışır |

### 4.3 Sandbox İmajı

```bash
docker build -t agentgrade-sandbox sandbox-images/agentgrade/
```

İlk build 3–5 dakika sürebilir (Python + g++ + OpenJDK 21 indirir).

### 4.4 PostgreSQL ve Redis

İki seçenek vardır:

**A) Docker compose (önerilen):**

```bash
docker compose up -d postgres redis
```

**B) Yerel PostgreSQL kurulumu varsa:**

```bash
psql -U postgres -c "CREATE USER semas WITH PASSWORD '12345';"
psql -U postgres -c "CREATE DATABASE agent_db OWNER semas;"
```

### 4.5 Ollama Modeli

```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b
ollama serve   # Servis arka planda çalışmıyorsa
```

### 4.5.1 NVIDIA NIM ile Calistirma

Yerel Ollama yerine NVIDIA NIM kullanmak icin `.env` dosyasinda:

```env
LLM_PROVIDER=nvidia_nim
NVIDIA_NIM_API_KEY=
NVIDIA_NIM_GENERAL_MODEL=qwen/qwen2.5-coder-32b-instruct
NVIDIA_NIM_CODER_MODEL=qwen/qwen2.5-coder-32b-instruct
```

Bu modda ajanlar, rubrik onerisi ve assignment chatbot ayni merkezi LLM
istemcisi uzerinden NIM API'ye gider. Modu kapatmak icin
`LLM_PROVIDER=ollama` yapmaniz yeterlidir.

NIM chatbot/rubrik icin iyi ama tam kod degerlendirme pipeline'i yavas
kalirsa hibrit mod kullanin:

```env
LLM_PROVIDER=nvidia_nim
LLM_GENERAL_PROVIDER=nvidia_nim
LLM_CODER_PROVIDER=ollama
```

### 4.6 Uygulamayı Başlatma

```bash
npm run dev:full
```

Ardından <http://localhost:8080> adresini açın.

---

## 5. Doğrulama

Kurulum sonrası kontrol listesi:

- [ ] `node scripts/check-prereqs.mjs` çıktısında zorunlu satırlar `[OK]`.
- [ ] `docker ps` çıktısında `agentgrade-postgres` (veya benzeri) çalışıyor.
- [ ] `docker images` çıktısında `agentgrade-sandbox` görünüyor.
- [ ] `curl http://localhost:11434/api/tags` 200 dönüyor.
- [ ] `npm run dev:full` ile başlatıldığında Vite (`8080`), FastAPI (`8001`) ve analysis worker açıldı.
- [ ] Tarayıcıda <http://localhost:8080> ana sayfası geliyor.

---

## 6. Sık Karşılaşılan Sorunlar

### "Docker bulunamadi" / daemon çalışmıyor

- Windows: Docker Desktop simgesinin yeşil olduğundan emin olun.
- Linux: `sudo systemctl start docker` ve `sudo usermod -aG docker $USER` (yeniden oturum açın).
- Demo mode'a geçin: `install` scriptini `--demo` parametresi ile çalıştırın.

### `npm install` izin hataları

- Yönetici/sudo ile çalıştırmayın; yerine npm'in kullanıcı dizinine kurulduğundan emin olun:
  `npm config set prefix "$HOME/.npm-global"`.

### `pip install` SSL/sertifika hataları

- Şirket VPN/proxy arkasındaysanız pip için sertifika ayarlayın:
  `pip config set global.cert <path-to-corporate-cert.pem>`.

### `.venv` / `pip` “bulunamadı” veya başka PC’deki Python yoluna referans

- Projeyi USB veya zip ile taşıdıysanız eski `.venv` silinmiş Python’a işaret edebilir.
  Kurulum scripti bunu çoğu durumda otomatik düzeltir; olmazsa `.venv` klasörünü silip
  `npm run setup` veya `npm run setup:demo` komutunu tekrar çalıştırın.
- Betiği **depo kökünden** çalıştırın (`npm run setup` bunu garanti eder) veya doğrudan
  `scripts/install.ps1` / `bash scripts/install.sh` çağırın; script içi olarak kök dizine geçilir.

### Sandbox build çok yavaş veya OOM

- `SANDBOX_POOL_SIZE`'ı azaltın (örn. 3) ve Docker Desktop için en az 4 GB RAM ayırın.

### Ollama modeli çekilemiyor

- `ollama pull qwen2.5:7b` ve `ollama pull qwen2.5-coder:7b` komutlarını manuel deneyin; ağ engelliyorsa
  `OLLAMA_GENERAL_MODEL` veya `OLLAMA_CODER_MODEL` değerlerini daha küçük modellere çekin.

### Port çakışması (5432, 8080, 8001, 8181-8190, 11434)

- Çakışan servisi durdurun ya da `.env`/`docker-compose.yml` içinde portları değiştirin.

---

## 7. Kaldırma

```bash
# Konteynerler ve veritabanı verisi
docker compose down -v

# Sandbox havuz konteynerleri
docker rm -f $(docker ps -aq --filter "name=agentgrade-sandbox")

# İmajlar
docker rmi agentgrade-sandbox postgres:16-alpine

# Python venv ve frontend node_modules
rm -rf .venv frontend/node_modules
```

Windows PowerShell için `rm -rf` yerine `Remove-Item -Recurse -Force` kullanın.

---

## 8. Geliştirici Notları

- Scriptlerin tümü idempotenttir; tekrar çalıştırmak güvenlidir. Python tarafında bozuk `.venv`
  otomatik yenilenir; `pip` çağrıları `python -m pip` ile yapılır.
- `install.ps1` ve `install.sh` zorunlu önkoşullar yoksa **çıkış kodu 1** döner;
  CI ortamlarında doğrudan kullanılabilir.
- `check-prereqs.mjs` salt okunur; CI smoke test'i olarak da çalışır.
- Yeni bir bağımlılık eklediğinizde `requirements.txt` ve/veya
  `frontend/package.json`'u güncellemeniz yeterlidir; scriptler otomatik
  toplar.
