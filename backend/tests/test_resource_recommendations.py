import unittest
from unittest.mock import AsyncMock, patch

from frontend.backend import main


class ResourceRecommendationTests(unittest.TestCase):
    def test_fallback_resources_prioritize_off_topic_guidance(self):
        recommendations = main._fallback_resource_recommendations(
            category_keys=["off-topic", "testing"],
            report_language="tr",
            assignment_brief="CSV dosyasindan rapor ureten Python odevi",
            summary="Teslim alakasiz.",
            weaknesses=["Kod odevle alakasiz."],
            recommendations=["Odev gereksinimlerini tekrar okuyun."],
        )

        self.assertGreaterEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0]["priority"], "high")
        self.assertIn("odev", recommendations[0]["reason"].lower())
        self.assertTrue(recommendations[0]["url"].startswith("https://"))

    def test_risk_detection_marks_runtime_security_and_low_alignment(self):
        categories = main._resource_recommendation_categories(
            total_score=34,
            relevance_score_warning="Gorev uyumu dusuk.",
            task_alignment={
                "factor": 0.18,
                "llm_off_topic": True,
                "reasons": ["llm_task_relevance_off_topic"],
            },
            test_agent={
                "compilation_success": False,
                "runs_successfully": False,
                "runtime_errors": ["Traceback"],
            },
            security_result={
                "risk_level": "high",
                "critical_count": 0,
                "high_count": 2,
            },
            source_code="pass",
        )

        self.assertIn("off-topic", categories)
        self.assertIn("runtime", categories)
        self.assertIn("security", categories)


class ResourceRecommendationNimTests(unittest.IsolatedAsyncioTestCase):
    async def test_nim_generation_requests_nvidia_provider_and_normalizes_cards(self):
        with patch.object(
            main,
            "chat_json",
            new=AsyncMock(
                return_value={
                    "resources": [
                        {
                            "title": "Python argparse",
                            "url": "https://docs.python.org/3/library/argparse.html",
                            "reason": "CLI akisini tamamlamak icin.",
                            "resourceType": "docs",
                            "priority": "high",
                        }
                    ]
                }
            ),
        ) as chat_json_mock:
            cards = await main._generate_resource_recommendations_with_nim(
                report_language="tr",
                assignment_brief="CLI odevi",
                rubric_summary="Fonksiyonellik, test ve hata yonetimi",
                summary="CLI eksik.",
                weaknesses=["Komut satiri argumanlari yok."],
                recommendations=["argparse ekleyin"],
                category_keys=["runtime", "testing"],
            )

        self.assertEqual(cards[0]["resourceType"], "docs")
        self.assertEqual(cards[0]["priority"], "high")
        self.assertTrue(cards[0]["url"].startswith("https://"))
        self.assertEqual(chat_json_mock.await_args.kwargs["provider_override"], "nvidia_nim")


if __name__ == "__main__":
    unittest.main()
