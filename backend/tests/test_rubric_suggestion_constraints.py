import unittest
from unittest.mock import AsyncMock, patch

from frontend.backend.main import (
    _ensure_mandatory_rubric_criteria,
    _polish_rubric_criteria,
    _project_specific_rubric_description,
    RubricSuggestionRequest,
    suggest_rubric,
)


class RubricSuggestionConstraintTests(unittest.IsolatedAsyncioTestCase):
    async def test_hard_assignment_gets_more_criteria_and_required_rows(self):
        payload = {
            "criteria": [
                {
                    "name": "Algoritma Tasarimi",
                    "description": "Cok asamali algoritmalarin dogru kurulmasi.",
                    "max_score": 10,
                }
            ]
        }

        with patch("frontend.backend.main.chat_json", new=AsyncMock(return_value=payload)) as chat:
            result = await suggest_rubric(
                RubricSuggestionRequest(
                    assignment_title="Zor veri isleme projesi",
                    assignment_description=(
                        "Ogrenciler cok parcali bir veri isleme sistemi gelistirecek; "
                        "moduler mimari, hata/kenar durumlari, test senaryolari, raporlama "
                        "ve tasarim kararlarini gerekcelendirme beklenir."
                    ),
                )
            )

        criteria = result["criteria"]
        names = {row["name"] for row in criteria}
        self.assertGreater(len(criteria), 10)
        self.assertLessEqual(len(criteria), 20)
        self.assertEqual(sum(row["max_score"] for row in criteria), 100)
        self.assertTrue(all(5 <= row["max_score"] <= 10 for row in criteria))
        self.assertTrue(
            {
                "Dokumantasyon",
                "Guvenlik",
                "Mantiksal Dogruluk",
                "Gereksinimlere Uyum",
                "Kodlama Stili",
            }.issubset(names)
        )
        self.assertIn("exactly", chat.await_args.kwargs["user_prompt"])

    async def test_mandatory_rows_are_specialized_to_assignment_project(self):
        payload = {
            "criteria": [
                {
                    "name": "Endpoint Tasarimi",
                    "description": "Kitap, uye, odunc ve iade endpointleri dogru tasarlanir.",
                    "max_score": 10,
                }
            ]
        }

        with patch("frontend.backend.main.chat_json", new=AsyncMock(return_value=payload)) as chat:
            result = await suggest_rubric(
                RubricSuggestionRequest(
                    assignment_title="Kutuphane Odunc Takip API",
                    assignment_description=(
                        "FastAPI ile kitap, uye, odunc ve iade kayitlarini yoneten REST API gelistirin. "
                        "POST /books, POST /members, POST /loans ve POST /returns endpointleri olsun; "
                        "olmayan kitap id'si, stokta olmayan kitap ve gecikmis iade durumlari icin JSON hata yanitlari uretin."
                    ),
                )
            )

        criteria = result["criteria"]
        by_name = {row["name"]: row["description"].lower() for row in criteria}
        self.assertIn("endpoint", by_name["Gereksinimlere Uyum"])
        self.assertIn("kitap", by_name["Mantiksal Dogruluk"])
        self.assertIn("json", by_name["Guvenlik"])
        self.assertIn("proje terimleri", chat.await_args.kwargs["user_prompt"].lower())

    async def test_existing_mandatory_rows_are_rewritten_when_generic(self):
        payload = {
            "criteria": [
                {
                    "name": "Gereksinimlere Uyum",
                    "description": "Tum gereksinimler karsilanir.",
                    "max_score": 10,
                },
                {
                    "name": "Mantiksal Dogruluk",
                    "description": "Cozum dogru calisir.",
                    "max_score": 10,
                },
                {
                    "name": "Kodlama Stili",
                    "description": "Kod okunabilir olur.",
                    "max_score": 10,
                },
                {
                    "name": "Dokumantasyon",
                    "description": "Dokumantasyon bulunur.",
                    "max_score": 10,
                },
                {
                    "name": "Guvenlik",
                    "description": "SQL injection, XSS ve CSRF onlenir.",
                    "max_score": 10,
                },
                *[
                    {
                        "name": f"Alan Kriteri {index}",
                        "description": "Odeve ozgu teknik kapsam.",
                        "max_score": 10,
                    }
                    for index in range(1, 6)
                ],
            ]
        }

        with patch("frontend.backend.main.chat_json", new=AsyncMock(return_value=payload)):
            result = await suggest_rubric(
                RubricSuggestionRequest(
                    assignment_title="Not Analizi CSV Raporu",
                    assignment_description=(
                        "CSV dosyasindan ogrenci notlarini okuyup gecen kalan sayisini, sinif ortalamasini "
                        "ve hatali satirlari raporlayan CLI uygulamasi gelistirin."
                    ),
                )
            )

        by_name = {row["name"]: row["description"].lower() for row in result["criteria"]}
        self.assertIn("csv", by_name["Guvenlik"])
        self.assertIn("hatali", by_name["Guvenlik"])
        self.assertNotIn("xss", by_name["Guvenlik"])

    async def test_generic_non_mandatory_descriptions_are_project_specialized(self):
        payload = {
            "criteria": [
                {
                    "name": "Veri Modeli",
                    "description": "Veri modeli dogru ve kaliteli olmalidir.",
                    "max_score": 10,
                }
            ]
        }

        with patch("frontend.backend.main.chat_json", new=AsyncMock(return_value=payload)):
            result = await suggest_rubric(
                RubricSuggestionRequest(
                    assignment_title="Sistem Log Ozetleme Araci",
                    assignment_description="Log dosyasini okuyup ERROR, WARNING ve INFO sayilarini raporlayan CLI yazin.",
                )
            )

        joined = "\n".join(row["description"].lower() for row in result["criteria"])
        self.assertIn("log", joined)
        self.assertIn("cli", joined)

    def test_common_rubric_fallback_descriptions_are_specific_not_template_noise(self):
        title = "Kitap Stok ve Odunc Verme Kayitlari Isleme"
        description = (
            "books.csv ve loans.csv dosyalarini okuyup stokta kalan kopyalari hesaplayin, "
            "geciken iadeleri bulun, kategori bazli rapor ve hatali satir raporu uretin."
        )

        csv_desc = _project_specific_rubric_description("CSV Dosya Isleme", title, description).lower()
        error_desc = _project_specific_rubric_description("Hata Yonetimi", title, description).lower()
        test_desc = _project_specific_rubric_description("Test Edilebilirlik", title, description).lower()

        self.assertIn("books.csv", csv_desc)
        self.assertIn("loans.csv", csv_desc)
        self.assertIn("hatali", error_desc)
        self.assertIn("geciken", error_desc)
        self.assertIn("test", test_desc)
        self.assertNotIn("kriteri", csv_desc)
        self.assertNotIn("somut girdi", error_desc)

    def test_rubric_polish_removes_english_quality_leaks(self):
        polished = _polish_rubric_criteria(
            [
                {
                    "name": "CSV Dosya Isleme",
                    "description": (
                        "Program books.csv ve loans.csv dosyalarini islemelidir. "
                        "Excellence gostermek icin CSV dosyalari handled edilir."
                    ),
                    "max_score": 10,
                }
            ],
            assignment_title="Kitap Stok Raporu",
            assignment_description="CSV dosyalarindan kitap stok raporu uretin.",
        )

        desc = polished[0]["description"].lower()
        self.assertIn("tam puan", desc)
        self.assertIn("ele alinir", desc)
        self.assertNotIn("excellence", desc)
        self.assertNotIn("handled", desc)

    def test_rubric_polish_replaces_template_noise_even_when_context_terms_exist(self):
        polished = _polish_rubric_criteria(
            [
                {
                    "name": "Metot Kapsami",
                    "description": (
                        "Metot Kapsami kriteri kitap, stok, csv projesindeki somut girdi, cikti, "
                        "is akisi ve hata durumlari uzerinden olculebilir kanitlarla degerlendirilir."
                    ),
                    "max_score": 10,
                }
            ],
            assignment_title="Kitap Stok Raporu",
            assignment_description="books.csv ve loans.csv dosyalarindan stok ve geciken iade raporu uretin.",
        )

        desc = polished[0]["description"].lower()
        self.assertIn("fonksiyon", desc)
        self.assertIn("books.csv", desc)
        self.assertNotIn("kriteri", desc)
        self.assertNotIn("somut girdi", desc)

    def test_rubric_polish_replaces_stale_library_csv_domain_leaks(self):
        polished = _polish_rubric_criteria(
            [
                {
                    "name": "Metot Kapsami",
                    "description": (
                        "Fonksiyonlar books.csv/loans.csv ayristirma, okuma, hesaplama, raporlama "
                        "sorumluluklarina ayrilir. Baglam: belediye, sikayet, csv, sqlite."
                    ),
                    "max_score": 10,
                }
            ],
            assignment_title="Belediye Sikayet Takip Sistemi",
            assignment_description=(
                "Belediye sikayetlerini CSV import, SQLite ve endpointlerle yoneten uygulama gelistirin."
            ),
        )

        desc = polished[0]["description"].lower()
        self.assertIn("csv", desc)
        self.assertIn("belediye", desc)
        self.assertNotIn("books.csv", desc)
        self.assertNotIn("loans.csv", desc)

    def test_project_specific_data_model_does_not_invent_library_domain(self):
        desc = _project_specific_rubric_description(
            "Veri Modeli",
            "Belediye Sikayet Takip Sistemi",
            "Belediye sikayetlerini CSV import, SQLite ve endpointlerle yoneten uygulama gelistirin.",
        ).lower()

        self.assertIn("belediye", desc)
        self.assertIn("sikayet", desc)
        self.assertNotIn("kitap", desc)

    async def test_log_cli_rubric_does_not_invent_oop_or_endpoint_scope(self):
        payload = {
            "criteria": [
                {
                    "name": "Sınıf Tasarımı",
                    "description": "Log araci icin sinif yapisi, kapsulleme ve kalitim dogru tasarlanir.",
                    "max_score": 10,
                },
                {
                    "name": "Endpoint Kapsamı",
                    "description": "API endpointleri, HTTP durumlari ve JSON hata yanitlari dogru uygulanir.",
                    "max_score": 10,
                },
                {
                    "name": "Gereksinimlere Uyum",
                    "description": "Tum gereksinimler karsilanir.",
                    "max_score": 10,
                },
            ]
        }

        with patch("frontend.backend.main.chat_json", new=AsyncMock(return_value=payload)):
            result = await suggest_rubric(
                RubricSuggestionRequest(
                    assignment_title="Sistem Log Ozetleme Araci",
                    assignment_description=(
                        "Bir log dosyasini okuyup ERROR, WARNING ve INFO sayilarini raporlayan "
                        "komut satiri CLI uygulamasi yazin. Program dosya yolunu arguman olarak alir "
                        "ve hatali satirlari raporda belirtir."
                    ),
                )
            )

        joined = "\n".join(
            f"{row['name']} {row['description']}".lower()
            for row in result["criteria"]
        )
        self.assertIn("log", joined)
        self.assertIn("cli", joined)
        for invented_term in ("endpoint", "api", "http", "sinif", "sınıf", "kapsul", "kapsül", "kalitim"):
            self.assertNotIn(invented_term, joined)

    async def test_rubric_generation_budget_scales_with_requested_criteria(self):
        payload = {
            "criteria": [
                {
                    "name": f"Kriter {index}",
                    "description": f"Log CLI odevindeki somut beklenti {index}.",
                    "max_score": 10,
                }
                for index in range(10)
            ]
        }

        with patch("frontend.backend.main.chat_json", new=AsyncMock(return_value=payload)) as chat:
            await suggest_rubric(
                RubricSuggestionRequest(
                    assignment_title="Sistem Log Ozetleme Araci",
                    assignment_description="Log dosyasindan CLI raporu uret.",
                    criterion_count=10,
                )
            )

        self.assertLessEqual(chat.await_args.kwargs["num_predict"], 1800)

    def test_mandatory_criteria_are_canonicalized_without_semantic_duplicates(self):
        criteria = [
            {
                "name": "Mantıksal Doğruluk",
                "description": "Algoritma ve karar akislari dogru olmali.",
                "max_score": 10,
            },
            {
                "name": "Dokümantasyon",
                "description": "Kurulum ve calistirma aciklanmali.",
                "max_score": 10,
            },
            {
                "name": "Güvenlik",
                "description": "Girdi dogrulama ve guvenli varsayimlar ele alinmali.",
                "max_score": 10,
            },
            {
                "name": "Gereksinimlere Uyum",
                "description": "Istenen tum maddeler karsilanmali.",
                "max_score": 10,
            },
            {
                "name": "Kodlama Stili",
                "description": "Kod okunabilir ve tutarli olmali.",
                "max_score": 10,
            },
            *[
                {
                    "name": f"Alan Kriteri {index}",
                    "description": "Odeve ozgu teknik kapsam.",
                    "max_score": 10,
                }
                for index in range(1, 6)
            ],
        ]

        sanitized = _ensure_mandatory_rubric_criteria(criteria)
        names = [row["name"] for row in sanitized]

        self.assertIn("Mantiksal Dogruluk", names)
        self.assertIn("Dokumantasyon", names)
        self.assertIn("Guvenlik", names)
        self.assertNotIn("Mantıksal Doğruluk", names)
        self.assertNotIn("Dokümantasyon", names)
        self.assertNotIn("Güvenlik", names)
        self.assertEqual(len(names), len(set(names)))

    def test_mandatory_criteria_with_replacement_characters_are_canonicalized(self):
        criteria = [
            {
                "name": "Mant?ksal Do?ruluk",
                "description": "Dogru sonuc.",
                "max_score": 10,
            },
            {
                "name": "Dok?mantasyon",
                "description": "Kurulum aciklamasi.",
                "max_score": 10,
            },
            {
                "name": "G?venlik",
                "description": "Girdi dogrulama.",
                "max_score": 10,
            },
            {
                "name": "Gereksinimlere Uyum",
                "description": "Istenen tum maddeler.",
                "max_score": 10,
            },
            {
                "name": "Kodlama Stili",
                "description": "Okunabilir kod.",
                "max_score": 10,
            },
            *[
                {
                    "name": f"Alan Kriteri {index}",
                    "description": "Odeve ozgu teknik kapsam.",
                    "max_score": 10,
                }
                for index in range(1, 6)
            ],
        ]

        sanitized = _ensure_mandatory_rubric_criteria(criteria)
        names = [row["name"] for row in sanitized]

        self.assertIn("Mantiksal Dogruluk", names)
        self.assertIn("Dokumantasyon", names)
        self.assertIn("Guvenlik", names)
        self.assertNotIn("Mant?ksal Do?ruluk", names)
        self.assertNotIn("Dok?mantasyon", names)
        self.assertNotIn("G?venlik", names)
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
