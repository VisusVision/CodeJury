import unittest
from unittest.mock import AsyncMock, patch

from frontend.backend.main import (
    AssignmentAssistantSuggestionsRequest,
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
