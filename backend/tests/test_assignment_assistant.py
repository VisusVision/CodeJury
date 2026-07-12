import unittest
from unittest.mock import AsyncMock, patch

from backend.auth.models import AuthPrincipal
from frontend.backend.main import (
    AssignmentExampleRequest,
    AssignmentAssistantSuggestionsRequest,
    _clean_assignment_example,
    _title_from_assignment_hint,
    assignment_assistant_example,
    assignment_assistant_suggestions,
)


_TEACHER_PRINCIPAL = AuthPrincipal(
    user_id="test-teacher", role="teacher", session_hash="x", csrf_hash="y"
)


class AssignmentAssistantTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_brief_fallback_returns_requested_number_of_variants(self):
        with patch("frontend.backend.main.chat_json", new=AsyncMock(return_value=None)):
            result = await assignment_assistant_suggestions(
                AssignmentAssistantSuggestionsRequest(
                    course_hint=(
                        "Python programlama dersi icin orta-zor seviyede bir odev: "
                        "ogrenciler bir CSV dosyasindan ogrenci notlarini okuyup gecme durumunu hesaplasin, "
                        "hatali satirlari raporlasin ve sonucu yeni bir CSV dosyasina yazsin."
                    ),
                    count=5,
                    difficulty="hard",
                    prefer_fresh=True,
                ),
                principal=_TEACHER_PRINCIPAL,
            )

        suggestions = result["suggestions"]
        self.assertEqual(len(suggestions), 5)
        titles = [row["title"] for row in suggestions]
        self.assertEqual(len(set(titles)), 5)
        joined = "\n".join(row["description"] for row in suggestions).lower()
        self.assertIn("csv", joined)
        self.assertIn("not", joined)

    async def test_long_brief_rejects_llm_suggestion_that_drops_required_cli_scope(self):
        with patch(
            "frontend.backend.main.chat_json",
            new=AsyncMock(
                return_value={
                    "suggestions": [
                        {
                            "title": "Log Analizi Arayuzu",
                            "summary": "Log kayitlarini ekranda gosterir.",
                            "description": "Log kayitlarini web arayuzunde grafiklerle inceleyen uygulama.",
                        }
                    ]
                }
            ),
        ):
            result = await assignment_assistant_suggestions(
                AssignmentAssistantSuggestionsRequest(
                    course_hint=(
                        "Veri Yapilari ve Python dersi icin ogrencilere verilecek orta-zor seviyede "
                        "bir odev tasarla: ogrenciler komut satirindan log dosyasi yolu alan bir CLI "
                        "yazsin; INFO, WARNING, ERROR ve CRITICAL satirlarini saysin."
                    ),
                    count=3,
                    difficulty="hard",
                ),
                principal=_TEACHER_PRINCIPAL,
            )

        first = result["suggestions"][0]
        combined = f"{first['title']} {first['summary']} {first['description']}".lower()
        self.assertIn("log", combined)
        self.assertIn("cli", combined)
        self.assertNotIn("arayuz", first["title"].lower())

    async def test_short_prompt_rejects_llm_suggestion_that_drops_technical_anchor(self):
        with patch(
            "frontend.backend.main.chat_json",
            new=AsyncMock(
                return_value={
                    "suggestions": [
                        {
                            "title": "Faktoriyel Hesaplama",
                            "summary": "Temel dongu alistirmasi.",
                            "description": "Ogrenciler faktoriyel hesaplayan basit bir program yazar.",
                        }
                    ]
                }
            ),
        ):
            result = await assignment_assistant_suggestions(
                AssignmentAssistantSuggestionsRequest(
                    course_hint="C++ vector sort min max fonksiyonlari ile temel algoritma odevi hazirla.",
                    count=3,
                    difficulty="easy",
                ),
                principal=_TEACHER_PRINCIPAL,
            )

        combined = "\n".join(
            f"{row['title']} {row['summary']} {row['description']}".lower()
            for row in result["suggestions"]
        )
        self.assertIn("c++", combined)
        self.assertIn("vector", combined)
        self.assertIn("sort", combined)
        self.assertNotIn("faktoriyel", combined)

    async def test_short_prompt_requires_requested_delivery_scope_in_titles(self):
        with patch(
            "frontend.backend.main.chat_json",
            new=AsyncMock(
                return_value={
                    "suggestions": [
                        {
                            "title": "Sarki Listesi Olusturma",
                            "summary": "HTML ve CSS ile responsive sayfa.",
                            "description": "HTML CSS responsive portfolio sayfasi icin farkli bir sarki listesi yapilir.",
                        }
                    ]
                }
            ),
        ):
            result = await assignment_assistant_suggestions(
                AssignmentAssistantSuggestionsRequest(
                    course_hint="HTML CSS responsive portfolio sayfasi: header, section, media query ve sade tasarim.",
                    count=3,
                    difficulty="easy",
                ),
                principal=_TEACHER_PRINCIPAL,
            )

        titles = "\n".join(row["title"].lower() for row in result["suggestions"])
        self.assertIn("html", titles)
        self.assertIn("portfolio", titles)
        self.assertNotIn("sarki", titles)

    async def test_unsafe_phishing_prompt_is_reframed_as_defensive_assignment(self):
        result = await assignment_assistant_suggestions(
            AssignmentAssistantSuggestionsRequest(
                course_hint="Gercek kullanicilardan parola toplayan phishing sitesi yapma odevi oner.",
                count=3,
                difficulty="medium",
            ),
            principal=_TEACHER_PRINCIPAL,
        )

        combined = "\n".join(
            f"{row['title']} {row['summary']} {row['description']}".lower()
            for row in result["suggestions"]
        )
        self.assertIn("farkindalik", combined)
        self.assertIn("savunmaci", combined)
        self.assertNotIn("parola toplayan", combined)
        self.assertNotIn("phishing sitesi yap", combined)

    async def test_assignment_example_uses_llm_expected_output(self):
        with patch(
            "frontend.backend.main.chat_json",
            new=AsyncMock(
                return_value={
                    "example": (
                        "Ornek: Girdi notlar.csv iki gecerli ve bir hatali satir icerir.\n"
                        "Beklenen cikti: gecen=1, kalan=1, hatali_satir=1."
                    )
                }
            ),
        ):
            result = await assignment_assistant_example(
                AssignmentExampleRequest(
                    assignment_title="Not Analizi",
                    assignment_description="CSV dosyasindan notlari okuyup gecme durumunu raporlayan program yazin.",
                ),
                principal=_TEACHER_PRINCIPAL,
            )

        self.assertEqual(result["source"], "llm")
        self.assertIn("notlar.csv", result["example"])
        self.assertIn("Beklenen cikti", result["example"])

    async def test_assignment_example_falls_back_to_output_format(self):
        with patch("frontend.backend.main.chat_json", new=AsyncMock(return_value=None)):
            result = await assignment_assistant_example(
                AssignmentExampleRequest(
                    assignment_title="Log Ozetleme",
                    assignment_description="Log dosyasindaki INFO WARNING ERROR satirlarini sayin ve bozuk satirlari raporlayin.",
                ),
                principal=_TEACHER_PRINCIPAL,
            )

        self.assertEqual(result["source"], "fallback")
        self.assertIn("ornek_log.txt", result["example"])
        self.assertIn("Beklenen cikti", result["example"])

    def test_assignment_example_cleaner_adds_expected_output_anchor_and_translates_leaks(self):
        cleaned = _clean_assignment_example(
            (
                "Input books.csv: B1,Python,3\n"
                "Output: stok=2\n"
                "Failure case: unknown book id"
            ),
            "Kitap Stok Raporu",
            "books.csv ve loans.csv dosyalarindan stok raporu ve hatali satir raporu uretin.",
        )

        self.assertIn("rnek:", cleaned[:10])
        self.assertIn("Beklenen cikti", cleaned)
        self.assertIn("Hata senaryosu", cleaned)
        self.assertNotIn("Input", cleaned)
        self.assertNotIn("Output", cleaned)
        self.assertNotIn("Failure case", cleaned)

    def test_assignment_example_cleaner_treats_console_output_as_expected_output(self):
        cleaned = _clean_assignment_example(
            (
                "Ornek: log dosyasi okunur.\n"
                "Konsol çıktısı: Parola Analizi Sonuçları:\n"
                "Parola1: 12345678 (Uzunluk: 8, Karmaşıklık: Düşük)"
            ),
            "Parola Güvenlik Analizi",
            "Log dosyasindaki parolalari analiz edip konsola yazdirin.",
        )

        self.assertIn("Beklenen cikti: Parola Analizi", cleaned)
        self.assertIn("Parola1: 12345678", cleaned)
        self.assertNotIn("Odev aciklamasinda istenen", cleaned)
        self.assertNotIn("Konsol çıktısı", cleaned)


    def test_assignment_example_cleaner_detects_turkish_expected_output_heading(self):
        cleaned = _clean_assignment_example(
            (
                "Ornek: POST /sikayetler istegi gecerli sikayet kaydi olusturur. "
                "Beklenen \u00e7\u0131kt\u0131: {\"id\": 1, \"mahalle\": \"Merkez\", \"durum\": \"acik\"}"
            ),
            "Belediye Sikayet API",
            "Belediye sikayetlerini endpointlerle yoneten API yazin.",
        )

        self.assertIn("Beklenen cikti:", cleaned)
        self.assertEqual(cleaned.count("Beklenen cikti:"), 1)
        self.assertNotIn("Odev aciklamasinda istenen", cleaned)

    def test_assignment_example_cleaner_normalizes_expected_report_heading(self):
        cleaned = _clean_assignment_example(
            "Ornek: python log_parser.py log.txt calistirilir.\nBeklenen rapor:\nINFO: 1\nERROR: 1",
            "Log CLI",
            "Log dosyasi okuyup rapor ureten CLI yazin.",
        )

        self.assertIn("Beklenen cikti:", cleaned)
        self.assertNotIn("Beklenen rapor:", cleaned)

    def test_assignment_example_cleaner_normalizes_report_output_heading(self):
        cleaned = _clean_assignment_example(
            "Ornek: python log_parser.py app.log\nRapor Ciktisi:\nINFO Sayisi: 2",
            "Log CLI",
            "Log dosyasi okuyup rapor ureten CLI yazin.",
        )

        self.assertIn("Beklenen cikti:", cleaned)
        self.assertNotIn("Rapor Ciktisi:", cleaned)

    def test_long_brief_title_uses_assignment_subject_not_teacher_prompt(self):
        title = _title_from_assignment_hint(
            "Veri Yapilari ve Python dersi icin ogrencilere verilecek orta-zor seviyede bir odev tasarla: "
            "ogrenciler komut satirindan log dosyasi yolu alan bir CLI yazsin; INFO, WARNING, ERROR ve "
            "CRITICAL satirlarini saysin."
        )

        self.assertIn("log", title.lower())
        self.assertIn("cli", title.lower())
        self.assertNotIn("tasarla", title.lower())
        self.assertNotIn("verilecek", title.lower())


class AssignmentSuggestionDiversityTests(unittest.TestCase):
    def test_hash_table_title_is_concrete_not_generic(self):
        from frontend.backend.main import _is_generic_assignment_title

        self.assertFalse(_is_generic_assignment_title("Hash Tablosu Sayaci"))
        self.assertTrue(_is_generic_assignment_title("Programlama Odevi"))

    def test_clean_assignment_suggestion_items_drops_near_duplicate_descriptions(self):
        from frontend.backend.main import _clean_assignment_suggestion_items

        raw = [
            {
                "title": "CSV Not Analizi A",
                "description": "CSV dosyasindan ogrenci notlarini okuyup gecme durumunu hesaplayan CLI.",
            },
            {
                "title": "CSV Not Analizi B",
                "description": "CSV dosyasindan ogrenci notlarini okuyup gecme durumunu hesaplayan program.",
            },
            {
                "title": "Hash Tablosu Sayaci",
                "description": "Metin dosyasinda kelime frekansini hash tablosu ile sayan program.",
            },
        ]

        cleaned = _clean_assignment_suggestion_items(raw, 3)

        self.assertEqual(len(cleaned), 2)
        titles = {row["title"] for row in cleaned}
        self.assertIn("CSV Not Analizi A", titles)
        self.assertIn("Hash Tablosu Sayaci", titles)
        self.assertNotIn("CSV Not Analizi B", titles)


class RelevanceWarningTests(unittest.TestCase):
    def test_partial_fulfillment_does_not_emit_off_topic_warning(self):
        from frontend.backend.main import (
            _compute_relevance_warning,
            _RELEVANCE_WARNING_OFF_TOPIC,
            _RELEVANCE_WARNING_PARTIAL,
        )

        warning = _compute_relevance_warning(
            ctx_len=200,
            align_factor=0.55,
            llm_off_topic=False,
            reasons=["llm_task_not_fulfilled"],
            total_score=0,
        )

        self.assertEqual(warning, _RELEVANCE_WARNING_PARTIAL)
        self.assertNotEqual(warning, _RELEVANCE_WARNING_OFF_TOPIC)
        self.assertNotIn("alakasiz", warning.split(".")[0])

    def test_low_capability_not_fulfilled_submission_emits_off_topic_warning(self):
        from frontend.backend.main import (
            _compute_relevance_warning,
            _RELEVANCE_WARNING_OFF_TOPIC,
        )

        warning = _compute_relevance_warning(
            ctx_len=200,
            align_factor=0.55,
            llm_off_topic=False,
            reasons=["llm_task_not_fulfilled"],
            total_score=16,
            capability_match=0.59,
        )

        self.assertEqual(warning, _RELEVANCE_WARNING_OFF_TOPIC)

    def test_true_off_topic_emits_off_topic_warning(self):
        from frontend.backend.main import (
            _compute_relevance_warning,
            _RELEVANCE_WARNING_OFF_TOPIC,
        )

        warning = _compute_relevance_warning(
            ctx_len=200,
            align_factor=0.05,
            llm_off_topic=True,
            reasons=["llm_task_relevance_off_topic"],
            total_score=8,
        )

        self.assertEqual(warning, _RELEVANCE_WARNING_OFF_TOPIC)

    def test_aligned_submission_has_no_warning(self):
        from frontend.backend.main import _compute_relevance_warning

        warning = _compute_relevance_warning(
            ctx_len=200,
            align_factor=0.85,
            llm_off_topic=False,
            reasons=[],
            total_score=90,
        )

        self.assertIsNone(warning)

    def test_short_brief_suppresses_warning(self):
        from frontend.backend.main import _compute_relevance_warning

        warning = _compute_relevance_warning(
            ctx_len=5,
            align_factor=0.05,
            llm_off_topic=True,
            reasons=["llm_task_relevance_off_topic"],
            total_score=0,
        )

        self.assertIsNone(warning)


class AssignmentLanguageDetectionTests(unittest.TestCase):
    def test_detects_python_from_course_hint(self):
        from frontend.backend.main import _detect_assignment_language

        lang = _detect_assignment_language(
            "Python programlama (PRO101), 3.sinif",
            "CSV not analizi",
            "Ogrenci notlarini okuyup gecme durumunu hesapla.",
        )

        self.assertEqual(lang, "Python")

    def test_detects_java(self):
        from frontend.backend.main import _detect_assignment_language

        self.assertEqual(
            _detect_assignment_language("Java ile Nesne Tabanli Programlama"),
            "Java",
        )

    def test_unknown_language_returns_empty(self):
        from frontend.backend.main import _detect_assignment_language

        self.assertEqual(_detect_assignment_language("Genel algoritma odevi"), "")

    async def _run_example_prompt_capture(self):
        from frontend.backend.main import (
            AssignmentExampleRequest,
            assignment_assistant_example,
        )

        captured: dict[str, str] = {}

        async def fake_chat_json(*, system_prompt, user_prompt, **kwargs):
            captured["system"] = system_prompt
            captured["user"] = user_prompt
            return {"example": "Örnek: python main.py ogrenciler.csv"}

        with patch("frontend.backend.main.chat_json", new=fake_chat_json):
            await assignment_assistant_example(
                AssignmentExampleRequest(
                    assignment_title="CSV Not Analizi",
                    assignment_description=(
                        "CSV dosyasindan ogrenci adi ve not okuyup gecme/kalma durumunu hesaplayan "
                        "ve sonucu yeni bir CSV rapor dosyasina yazan program."
                    ),
                    course_hint="Python programlama (PRO101), 3.sinif",
                ),
                principal=_TEACHER_PRINCIPAL,
            )
        return captured

    def test_example_prompt_includes_detected_language(self):
        import asyncio

        captured = asyncio.run(self._run_example_prompt_capture())
        self.assertIn("Programming language: Python", captured["user"])


if __name__ == "__main__":
    unittest.main()
