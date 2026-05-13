import unittest
from unittest.mock import AsyncMock, patch

from frontend.backend.main import (
    AssignmentExampleRequest,
    AssignmentAssistantSuggestionsRequest,
    _clean_assignment_example,
    assignment_assistant_example,
    assignment_assistant_suggestions,
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
                )
            )

        suggestions = result["suggestions"]
        self.assertEqual(len(suggestions), 5)
        titles = [row["title"] for row in suggestions]
        self.assertEqual(len(set(titles)), 5)
        joined = "\n".join(row["description"] for row in suggestions).lower()
        self.assertIn("csv", joined)
        self.assertIn("not", joined)

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
                )
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
                )
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


if __name__ == "__main__":
    unittest.main()
