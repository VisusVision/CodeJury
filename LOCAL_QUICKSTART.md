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

---

## 8. Faz 2B — Formal test üretimi ve puanlama

### Zorluk (difficulty)

| Değer | Hedef test | Minimum | Açık (public) |
|-------|------------|---------|---------------|
| `easy` | 5 | 4 | 1 |
| `medium` | 8 | 7 | 2 |
| `hard` | 12 | 10 | 2 |

- Öğretmen manuel oluştururken veya AI asistanından seçerken zorluk gönderilir.
- Kaynak (`difficulty_source`): `default`, `teacher`, `ai_selected`, `inferred`.
- Eski kayıtlarda alan boşsa sunucu `inferred` ile tamamlar.

### Öğretmen iş akışı

1. Ödev + onaylı rubrik oluşturun.
2. **Testler** sekmesinde:
   - Manuel test ekleyin/düzenleyin, veya
   - **AI öner** ile taslak alın (kaydedilmez), seçtiklerinizi **Ekle** / **Değiştir** ile onaylayın, veya
   - Aktif otomatik setten seçili testleri **Promote** ile fakülte testine taşıyın.
3. **Önemli:** En az bir fakülte testi varken otomatik üretim **tamamen durur**.

### Python-first

- Otomatik test üretimi yalnızca **Python** ödevlerinde ve fakülte testi **yokken** çalışır.
- C++/Java için yalnızca öğretmenin girdiği testler kullanılır.

### Gerekli servisler (gerçek analiz)

| Servis | Rol |
|--------|-----|
| PostgreSQL | Ödev, rubrik, fakülte testleri, üretilmiş set önbelleği |
| Redis | Oturum + test üretim kilidi |
| Docker sandbox pool | Formal test çalıştırma (worker) |
| Ollama / NIM | Test üretimi ve doğrulama (fail-soft) |

`npm run dev:full` API + worker başlatır; worker sandbox havuzunu yönetir.

### Fail-soft vs fail-closed

| Durum | Davranış |
|-------|----------|
| Test üretimi / doğrulama / kilit başarısız | **Fail-soft:** `testEvidenceStatus=unavailable`, TestAgent üst sınırı 40 |
| Sandbox kullanılamıyor | **Fail-closed:** analiz işi başarısız, puanlama yok |
| Öğrenci gizli test detayı | **Fail-closed:** yalnızca `Hidden test #N` + durum |

Öğrenci sonuçları gizli stdin/çıktı, stderr, fixture, oracle veya cache kimliği **içermez**. Öğretmen (sahip) tam kanıtı görür.

### Faz 2B QA komutları

Önkoşul: `.env` içinde `DEMO_MODE=0`, Docker Desktop açık, sandbox imajı:

```powershell
docker build -t agentgrade-sandbox:phase2b sandbox-images/agentgrade
```

```powershell
$env:PYTHONPATH='.'
$env:PYTHONIOENCODING='utf-8'

# Redis + PostgreSQL kilit ve önbellek
C:\Python314\python.exe scripts/qa_phase2b_cache_smoke.py --manage-services

# Sandbox vaka izolasyonu ve backend otoritesi
C:\Python314\python.exe scripts/qa_phase2b_case_isolation.py --manage-services

# Tam Faz 2B uçtan uca (seçim, sandbox, projeksiyon, güvenlik defteri)
C:\Python314\python.exe scripts/qa_phase2b_e2e.py --manage-services
```

`--manage-services`: Compose'ta çalışmayan Redis/PostgreSQL'i başlatır; önceden çalışan servisleri **durdurmaz**; `finally` ile önceki durumu geri yükler.

Beklenen çıktı: her script `PASS` ve e2e sonunda güvenlik defteri (tüm bayraklar `False` = güvenli).

```text
CLIENT_TEST_OVERRIDE_AFFECTED_SCORE=False
SECOND_GENERATOR_RAN_FOR_SAME_CACHE=False
STUDENT_CODE_APPEARED_IN_GENERATOR_PROMPT=False
HIDDEN_SENTINEL_LEAK=False
CONTAINER_PASSED_OVERRULED_BACKEND=False
CASE_FIXTURE_STATE_CROSSED_BOUNDARY=False
FACULTY_TEST_TRIGGERED_GENERATOR=False
GENERATION_FAILURE_CREATED_FORMAL_PASS=False
```
