# AgentGrade — Kurulum Rehberi

Bu doküman, AgentGrade çoklu-ajan kod değerlendirme sistemini sıfırdan
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
3. **Python venv**: `.venv` oluşturur, `pip install -r requirements.txt` çalıştırır.
4. **npm install**: `frontend/` klasöründe çalıştırır.
5. **Sandbox imajı**: `docker build -t agentgrade-sandbox sandbox-images/agentgrade/`.
6. **PostgreSQL**: `docker compose up -d postgres`.
7. **Ollama modeli**: `ollama pull qwen2.5:7b`.
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
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama servisi |
| `OLLAMA_MODEL` | `qwen2.5:7b` | LLM model adı |
| `SANDBOX_POOL_SIZE` | `10` | Önyüklenecek konteyner sayısı |
| `DEMO_MODE` | `0` | `1` ise PostgreSQL'siz çalışır |

### 4.3 Sandbox İmajı

```bash
docker build -t agentgrade-sandbox sandbox-images/agentgrade/
```

İlk build 3–5 dakika sürebilir (Python + g++ + OpenJDK 21 indirir).

### 4.4 PostgreSQL

İki seçenek vardır:

**A) Docker compose (önerilen):**

```bash
docker compose up -d postgres
```

**B) Yerel PostgreSQL kurulumu varsa:**

```bash
psql -U postgres -c "CREATE USER semas WITH PASSWORD '12345';"
psql -U postgres -c "CREATE DATABASE agent_db OWNER semas;"
```

### 4.5 Ollama Modeli

```bash
ollama pull qwen2.5:7b
ollama serve   # Servis arka planda çalışmıyorsa
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
- [ ] `npm run dev:full` ile başlatıldığında hem Vite (`8080`) hem FastAPI (`8001`) açıldı.
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

### Sandbox build çok yavaş veya OOM

- `SANDBOX_POOL_SIZE`'ı azaltın (örn. 3) ve Docker Desktop için en az 4 GB RAM ayırın.

### Ollama modeli çekilemiyor

- `ollama pull qwen2.5:7b` manuel deneyin; ağ engelliyorsa daha küçük bir modele
  geçin (`OLLAMA_MODEL=qwen2.5:3b`).

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

- Scriptlerin tümü idempotenttir; tekrar çalıştırmak güvenlidir.
- `install.ps1` ve `install.sh` zorunlu önkoşullar yoksa **çıkış kodu 1** döner;
  CI ortamlarında doğrudan kullanılabilir.
- `check-prereqs.mjs` salt okunur; CI smoke test'i olarak da çalışır.
- Yeni bir bağımlılık eklediğinizde `requirements.txt` ve/veya
  `frontend/package.json`'u güncellemeniz yeterlidir; scriptler otomatik
  toplar.
