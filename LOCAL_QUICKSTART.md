# CodeJury — Yerel Kurulum (Tek Kullanıcı)

Bu rehber, projeyi **kendi bilgisayarınızda** çalıştırmak isteyen tek kullanıcı içindir.
Sunucu veya bulut kurulumu gerekmez.

---

## Hangi yolu seçmeliyim?

| | **Hızlı deneme** | **Gerçek analiz** |
|---|------------------|-------------------|
| Komut | `npm run setup:demo` | `npm run setup` |
| Süre | ~15 dk | ~45–90 dk |
| Docker | Gerekmez | Gerekli |
| PostgreSQL | Gerekmez (bellek içi) | Docker ile |
| Sandbox | Docker gerekli (yoksa analiz engellenir) | Docker pool |
| Ollama | Opsiyonel | Önerilir (zorunlu sayılır) |
| Amaç | Arayüzü görmek | Tam puanlama + PDF |

Detaylı kurulum: [INSTALL.md](INSTALL.md)

---

## 1. Önkoşullar

```bash
npm run check:prereqs
```

**Hızlı deneme:** Python 3.11+, Node 18+, npm  
**Gerçek analiz:** + Docker Desktop, Ollama

---

## 2. Kurulum

### A) Hızlı deneme (demo)

```bash
git clone https://github.com/agentgrade/codejury.git
cd CodeJury
npm run setup:demo
npm run dev:full
```

Tarayıcı: **http://localhost:8080**

**Demo hesaplar:**

| Rol | Giriş | Şifre |
|-----|-------|-------|
| Öğretmen | `demo@agentgrade.local` | `demo123` |
| Öğrenci | `20240001` | `11111111111` |

### B) Gerçek analiz (tam kurulum)

```bash
npm run setup
npm run dev:full
```

İlk kurulumda Ollama modelleri indirilir (~12 GB coder modeli).  
Zayıf bilgisayar için `.env` içinde **Lite profil** bölümüne bakın.

---

## 3. Çalışıyor mu?

Uygulama açıkken (`npm run dev:full`):

```bash
cd frontend && npm run verify:health
```

Beklenen:

```json
{
  "status": "ok",
  "analysis_ready": true,
  "worker_count": 1,
  "ready_worker_count": 1,
  "sandbox": {
    "mode": "pool",
    "pool_ready": true,
    "container_count": 3,
    "available_count": 3
  }
}
```

- `status: degraded` ve `analysis_ready: false` → worker ve Docker'ı başlatın/kontrol edin.
- `analysis_ready: true` ile birlikte `status: degraded` → kısmi kapasite; analiz yine de kullanılabilir.
- Aynı makinede birden fazla worker çalıştırırken her birine benzersiz `SANDBOX_POOL_BASE_PORT` aralığı ve farklı bir `SANDBOX_POOL_OWNER` değeri verin.

Arayüzde **Sistem durumu** rozeti (LLM modelleri + sandbox) görünür.

---

## 4. İlk analiz akışı

1. **Öğretmen** olarak giriş → bölüm/ders/ödev oluştur → rubrik onayla  
2. **Öğrenci** olarak giriş → ödevi aç → `.py` dosyası yükle  
3. **Ajanları Çalıştır** — ilk analiz **3–8 dakika** sürebilir (normal)  
4. Sağ panel → Süreç / Rapor → PDF indir

Ollama kapalıysa analiz başlamadan uyarı alırsınız.

---

## 5. Oturum ve kimlik doğrulama

Giriş artık **Redis** üzerinde tutulan oturumlara bağlıdır; Redis yalnızca analiz kuyruğu için değil, login için de zorunludur.

| Ayar | Yerel | Production (HTTPS) |
|------|-------|-------------------|
| `AUTH_COOKIE_SECURE` | `false` | `true` |
| `CORS_ALLOWED_ORIGINS` | Frontend origin’lerini içermeli (varsayılan: `http://localhost:8080,http://127.0.0.1:8080`) | Aynı kural |

**HTTP durum kodları:** `401` oturum yok veya geçersiz; `403` yanlış rol veya CSRF hatası; `503` Redis/oturum servisine ulaşılamıyor.

- **Çıkış:** `POST /api/auth/logout` idempotenttir — geçersiz veya süresi dolmuş oturumda da `204` döner ve çerezler temizlenir.
- **Öğretmen kaydı:** `POST /api/teacher/register` hâlâ açıktır ve oturum oluşturmaz (davranış değişmedi).

---

## 6. Sık sorunlar

| Sorun | Çözüm |
|-------|--------|
| Docker bulunamadı | Docker Desktop’ı açın veya `setup:demo` kullanın |
| Ollama yok / model yok | `ollama serve` + `ollama pull qwen2.5-coder:7b` |
| Port 8080/8001 meşgul | İlgili süreci kapatın |
| Sandbox kullanılamıyor / `analysis_ready: false` | Docker Desktop açık mı? `docker build -t agentgrade-sandbox sandbox-images/agentgrade/` çalıştırıldı mı? Worker sürecini kontrol edin. |
| Çok yavaş | `.env`: `SANDBOX_POOL_SIZE=3`, `OLLAMA_CODER_MODEL=qwen2.5-coder:7b` |

---

## 7. Durdurma

`Ctrl+C` ile `npm run dev:full` durdurulur.

Docker servisleri:

```bash
docker compose down
```
