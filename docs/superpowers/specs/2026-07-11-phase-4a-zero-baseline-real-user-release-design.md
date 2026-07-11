# Faz 4A Zero-Baseline Real-User Release Design

## Amaç

Faz 4A, AgentGrade'in mevcut Python-first ürün davranışını değiştirmeden release-grade hale getirir. Başarı ölçütü yalnızca test paketinin yeşil olması değildir: production-benzeri gerçek servislerle, aktif gerçek LLM provider'ıyla ve gerçek öğretmen/öğrenci tarayıcı yolculuklarıyla bütün analiz zincirinin kanıtlanmasıdır.

Faz sonunda:

- Backend test paketinde beklenen veya tolere edilen failure kalmaz.
- Frontend testleri ve production build sıfır hatayla tamamlanır.
- PostgreSQL, Redis, analysis worker ve Docker sandbox pool birlikte çalışır.
- `.env` içinde seçili gerçek LLM provider bütün ajan çağrılarında kullanılır.
- Öğretmen ve öğrenci UI yolculukları gerçek hesaplarla tamamlanır.
- Hidden test, oracle, fixture ve expectation provenance öğrenci yüzeyine sızmaz.
- Her koşu, credential veya private veri içermeyen denetlenebilir bir kanıt defteri üretir.

## Kapsam

### Dahil

1. Mevcut sekiz backend baseline failure'ın kök nedenleriyle kapatılması.
2. CI'ın sıfır beklenen failure politikasıyla çalışması.
3. Gerçek servis readiness, queue, worker ve sandbox doğrulaması.
4. Gerçek LLM ile bütün ajanların sözleşme ve fallback davranışının doğrulanması.
5. Teacher ve student UI üzerinden gerçek kullanıcı acceptance yolculukları.
6. Faz 1, Faz 2A, Faz 2B ve Faz 3 güvenlik/otorite invariantlarının birleşik regresyonu.
7. QA verisinin benzersiz run kimliğiyle oluşturulması ve yalnızca run-owned verinin temizlenmesi.
8. Release kanıt defteri ve tekrar çalıştırılabilir QA komutlarının dokümantasyonu.

### Hariç

- C++/Java AI test generation ve derin algoritma analizi; bunlar Faz 4B kapsamıdır.
- Hidden reference solution oracle; bu ayrı sonraki fazdır.
- Öğretmen kayıt akışı veya kullanıcı rol modelinin değiştirilmesi.
- Yeni rubrik/final-score ürün politikası.
- Var olan kullanıcı parolası veya profilinin değiştirilmesi.
- Production deployment veya GitHub push; ayrıca yetki verilmelidir.

## Onaylanan Çalışma Ortamı

- `DEMO_MODE=0`.
- PostgreSQL gerçek persistence kaynağıdır.
- Redis queue, session, lock ve cache kaynağıdır.
- Analysis worker gerçek queue tüketicisidir.
- Docker sandbox pool fail-closed çalışır.
- LLM provider, mevcut `.env` ayarından seçilir; test doubles release acceptance yerine geçmez.
- Mevcut öğretmen ve öğrenci hesapları kullanılır.
- Credential değerleri repo, log, artifact veya komut çıktısına yazılmaz.

## Mimari

Faz 4A dört bağımsız kapıdan oluşur. Bir kapının başarısızlığı sonraki kapıyı başarılı saymaya izin vermez.

### Gate 4A.1 — Zero Baseline

Mevcut sekiz failure ayrı ayrı RED olarak yeniden üretilir, kök nedenleri izlenir ve en dar davranış değişikliğiyle kapatılır:

1. SecurityAgent HTTP-client kalibrasyonu.
2. Assignment suggestion near-duplicate temizliği.
3. MasterEvaluator alignment cap eşikleri.
4. Coder modelinin NVIDIA NIM payload routing'i.
5. Text çağrısının NVIDIA NIM routing'i.
6. Hybrid general/coder provider routing'i.
7. NVIDIA NIM token floor uygulaması.
8. Hard-assignment rubric prompt sözleşmesi.

Her fix kendi regresyon testi ve task-scoped commit'iyle ilerler. Testi değiştirerek üretim hatasını saklamak yasaktır; yalnız onaylı ürün sözleşmesi değiştiyse test ve uygulama birlikte güncellenebilir.

### Gate 4A.2 — Real Services

Tek bir release orchestrator şu bileşenleri readiness sırasıyla doğrular:

1. PostgreSQL bağlantısı ve schema readiness.
2. Redis bağlantısı ve sahiplik kontrollü geçici key.
3. Analysis worker heartbeat ve `analysis_ready=true`.
4. Sandbox pool health ve gerçek container execution.
5. Aktif LLM provider health ve provider/model metadata doğrulaması.
6. API `/api/health` ve readiness sözleşmesi.

Orchestrator yalnızca eksik local servisleri başlatabilir; başlangıçta kapalı olan servisleri koşu sonunda tekrar kapatır. Başlangıçta açık olan servislere dokunmaz.

### Gate 4A.3 — Real User Browser Journeys

Acceptance iki rol üzerinden gerçek UI ile yürütülür.

#### Öğretmen yolculuğu

1. E-posta/parola ile login.
2. Benzersiz run etiketi taşıyan Python ödevi oluşturma.
3. AI assignment assistant ve güvenlik kontrolü.
4. Rubrik oluşturma/önerme/onaylama.
5. Manuel public/hidden test case ekleme.
6. AI test suggestion çağrısı.
7. Seçili generated case'leri promote etme.
8. Read-only algorithm expectation panelini açma.
9. Öğrenci sonucu için teacher-private raporu görüntüleme.

#### Öğrenci yolculuğu

1. Öğrenci numarası/parola ile login.
2. Yetkili ödevi görme.
3. En az üç Python submission çalıştırma:
   - Beklenen yaklaşımla doğru çözüm.
   - Çalışan fakat beklenenden daha karmaşık çözüm.
   - Runtime veya formal-test başarısız çözüm.
4. Analysis job queue/polling akışını bekleme.
5. Birleşik raporu ve ajan kartlarını görüntüleme.
6. Logout ve 401 merkezi auth davranışını doğrulama.

Mevcut kullanıcıların profil veya parolası değiştirilmez. Testin oluşturduğu assignment, rubric, test setleri, submissions, reports, expectation kayıtları ve cache/lock kalıntıları run sonunda temizlenir.

### Gate 4A.4 — Evidence, Privacy and Release Ledger

Her gerçek analiz aşağıdaki ajanları ve sentez katmanlarını kapsar:

- CodeQualityAgent
- AlgorithmAgent
- AIAuthorshipAgent
- SeniorityAgent
- GuidelineAgent
- SecurityAgent
- TestAgent
- EvidenceAgent
- MasterEvaluatorAgent

Release ledger exact doğal dil veya exact LLM skorunu değil, şu invariantları doğrular:

- Her ajan zorunlu output schema alanlarını üretir.
- `llm_status`, provider/model metadata ve fallback nedeni private kanıtta bulunur.
- AlgorithmAgent gerçek AST alt sınırını, verified expectation'ı veya score cap'i geçersiz kılamaz.
- AlgorithmAgent puanı MasterEvaluator rubrik/final wiring'ini değiştirmez.
- TestAgent puanı formal sandbox sonuçlarından türetilir; LLM formal pass/fail'i değiştiremez.
- Sandbox unavailable ise analiz fail-closed olur.
- Hidden test input/expected/actual/stderr/diff/fixture/oracle metadata öğrenci JSON/DOM/cache yüzeyinde bulunmaz.
- Expectation ID/cache/version/provider/model/verifier reason öğrenci yüzeyinde bulunmaz.
- Teacher-private rapor gerekli provenance ve hidden kanıtı yetkili öğretmene gösterir.
- Öğrenci başka öğrencinin sonucunu, başka öğretmenin ödevini veya teacher-private endpoint'i okuyamaz.
- Expectation veya generated test resource'u için yetkisiz mutation route bulunmaz.

## Gerçek LLM Kabul Politikası

Gerçek provider kullanıldığı için doğal dil ve skorlar deterministik kabul edilmez. Acceptance şu kurallara dayanır:

- Exact cümle, sıra veya stil assertion'ı yapılmaz.
- Strict JSON/schema, enum, alan tipi ve server-side guardrail assertion'ı yapılır.
- Provider/model metadata `.env` routing kararıyla eşleşmelidir.
- Provider erişilemiyorsa veya iki bounded denemede geçerli sözleşme üretilemiyorsa gate başarısız olur; fake başarı üretilmez.
- Retry sayıları, timeout'lar ve toplam süre bounded ayarlardan okunur.
- Credential, prompt içindeki öğrenci kodu dışındaki secret veya chain-of-thought loglanmaz.

## Veri Sahipliği ve Temizlik

Her koşu `phase4a-<uuid>` kimliği üretir. Bu kimlik assignment başlığı, QA kayıt metadata'sı, Redis key prefix'i ve cleanup sorgularında kullanılır.

Temizlik sırası:

1. Run-owned analysis jobs ve result kayıtları.
2. Run-owned generated test sets ve promoted/manual test cases.
3. Run-owned algorithm expectations.
4. Run-owned rubric ve assignment.
5. Run-owned Redis cache/lock/job key'leri.
6. Run'ın başlattığı worker/pool/service süreçleri.

Cleanup yalnız doğrulanmış run ownership'i bulunan kayıtlara uygulanır. Kullanıcı hesapları, mevcut ödevler ve başka koşuların verileri korunur. Cleanup başarısızlığı gate'i başarısız yapar ve kalan kaynak kimlikleri secret içermeden raporlanır.

## Hata Yönetimi

- Baseline test failure: yeni feature çalışmasına geçilmez.
- PostgreSQL/Redis unavailable: hangi readiness katmanının kırıldığı açıkça raporlanır.
- Worker heartbeat yok: submission oluşturulmaz; readiness gate fail olur.
- Sandbox unavailable: analiz başarısız sayılır; host simulation kullanılmaz.
- LLM unavailable/invalid schema: bounded retry sonrası gerçek-provider gate fail olur.
- Browser selector/UI değişikliği: API sonucu başarılı olsa bile browser gate fail olur.
- Cleanup failure: ana senaryo başarılı olsa bile release sonucu fail olur.
- Öğrenci projection sentinel leak: kritik release blocker'dır.

## Otomasyon ve Kanıt Çıktısı

Yeni orchestrator `scripts/qa_phase4a_release.py` yapılandırılmış bir ledger üretir:

```text
BASELINE_FAILURE_COUNT=0
BACKEND_FULL_SUITE_FAILED=False
FRONTEND_SUITE_FAILED=False
FRONTEND_BUILD_FAILED=False
POSTGRES_READY=True
REDIS_READY=True
WORKER_READY=True
SANDBOX_REAL_EXECUTION_FAILED=False
REAL_LLM_PROVIDER_MISMATCH=False
TEACHER_JOURNEY_FAILED=False
STUDENT_JOURNEY_FAILED=False
AGENT_CONTRACT_FAILED=False
FORMAL_AUTHORITY_OVERRIDDEN=False
ALGORITHM_GUARDRAIL_OVERRIDDEN=False
STUDENT_PRIVATE_DATA_LEAK=False
UNAUTHORIZED_ACCESS_SUCCEEDED=False
CLEANUP_RESIDUE_FOUND=False
```

Kanıt çıktısı credential, cookie, CSRF token, hidden test verisi, öğrenci kaynak kodunun tamamı veya private LLM prompt'u içermez.

## Test Stratejisi

### TDD

Her baseline bug için:

1. Tek failing test ile mevcut semptom yeniden üretilir.
2. Kök neden veri akışında izlenir.
3. Minimal fix uygulanır.
4. Focused suite çalıştırılır.
5. Full backend karşılaştırılır.
6. Task-scoped commit oluşturulur.

### Otomatik kapılar

- Backend full pytest: sıfır failure.
- Frontend Vitest: sıfır failure.
- Production build: exit 0.
- Python compileall ve `git diff --check`: temiz.
- Phase 1 pool smoke ve soak.
- Phase 2B cache, fixture isolation ve E2E QA.
- Phase 3 expectation/cache/privacy QA.
- Phase 4A birleşik release orchestrator.

### Tarayıcı kabulü

Gerçek kullanıcı adımları in-app browser ile çalıştırılır. Browser kanıtı görünür UI state, network/API sonucu ve rol bazlı DOM görünürlüğünü birlikte doğrular. Tarayıcı session/cookie/local-storage içeriği doğrudan okunmaz; yalnız kullanıcıya gösterilen davranış ve desteklenen browser API'leri kullanılır.

## CI Politikası

`.github/workflows/ci.yml` backend komutu sıfır failure beklemeye devam eder. Xfail/allow-failure/baseline allowlist eklenmez. Gerçek LLM ve gerçek kullanıcı acceptance, credential gerektirdiği için standart PR CI'ı içinde zorunlu secret bağımlılığı oluşturmaz; manuel veya korumalı release workflow olarak çalışır. CI deterministik sözleşme testlerini, release gate ise gerçek provider davranışını doğrular.

## Başarı Kriterleri

Faz 4A yalnız aşağıdaki koşulların tamamı sağlandığında kapanır:

1. Backend full suite sıfır failure.
2. Frontend suite ve production build yeşil.
3. Compile/diff kontrolleri temiz.
4. Gerçek PostgreSQL/Redis/worker/sandbox readiness yeşil.
5. Aktif gerçek LLM provider ile bütün ajanlar geçerli sözleşme üretir.
6. Öğretmen ve öğrenci browser yolculukları tamamlanır.
7. Üç submission senaryosu beklenen formal/algorithm davranışını gösterir.
8. Tüm privacy/authorization adversarial bayrakları güvenli değerdedir.
9. Run-owned veri ve servis kalıntısı yoktur.
10. Branch yalnız task-scoped commit'ler içerir; push ayrıca yetkilendirilmedikçe yapılmaz.
