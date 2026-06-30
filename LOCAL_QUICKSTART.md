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
| Sandbox | Simülasyon | Docker pool |
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

Beklenen: `status: ok`, `llm.enabled: true`, isteğe bağlı `sandbox.pool_ready: true`.

Arayüzde **Sistem durumu** rozeti (LLM modelleri + sandbox) görünür.

---

## 4. İlk analiz akışı

1. **Öğretmen** olarak giriş → bölüm/ders/ödev oluştur → rubrik onayla  
2. **Öğrenci** olarak giriş → ödevi aç → `.py` dosyası yükle  
3. **Ajanları Çalıştır** — ilk analiz **3–8 dakika** sürebilir (normal)  
4. Sağ panel → Süreç / Rapor → PDF indir

Ollama kapalıysa analiz başlamadan uyarı alırsınız.

---

## 5. Sık sorunlar

| Sorun | Çözüm |
|-------|--------|
| Docker bulunamadı | Docker Desktop’ı açın veya `setup:demo` kullanın |
| Ollama yok / model yok | `ollama serve` + `ollama pull qwen2.5-coder:7b` |
| Port 8080/8001 meşgul | İlgili süreci kapatın |
| Sandbox simülasyon | Docker + `docker build -t agentgrade-sandbox sandbox-images/agentgrade/` |
| Çok yavaş | `.env`: `SANDBOX_POOL_SIZE=3`, `OLLAMA_CODER_MODEL=qwen2.5-coder:7b` |

---

## 6. Durdurma

`Ctrl+C` ile `npm run dev:full` durdurulur.

Docker servisleri:

```bash
docker compose down
```
