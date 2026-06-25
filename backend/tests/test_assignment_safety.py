import unittest

from backend.agents.assignment_safety import AssignmentSafetyAgent


class AssignmentSafetyTests(unittest.TestCase):
    def test_defensive_phishing_assignment_is_allowed_deterministically(self):
        result = AssignmentSafetyAgent().analyze(
            title="Phishing Farkindalik Siniflandirici",
            description=(
                "Oyuncak veriyle phishing e-postalarini tespit eden savunmaci siniflandirici yazin; "
                "gercek kimlik bilgisi toplanmayacak ve operasyonel saldiri adimi verilmeyecek."
            ),
            course_context="Python Veri Analizi",
        )

        self.assertTrue(result.allowed)
        self.assertTrue(result.is_programming_assignment)

    def test_safe_educational_llm_category_noise_does_not_block(self):
        agent = AssignmentSafetyAgent()
        deterministic = agent.analyze(
            title="Phishing Farkindalik Siniflandirici",
            description=(
                "Oyuncak veriyle phishing e-postalarini tespit eden savunmaci siniflandirici yazin; "
                "gercek kimlik bilgisi toplanmayacak ve operasyonel saldiri adimi verilmeyecek."
            ),
            course_context="Python Veri Analizi",
        )

        merged = agent._merge_llm_review(
            deterministic,
            {
                "allowed": False,
                "is_programming_assignment": True,
                "risk_categories": ["crime"],
                "reason": (
                    "Phishing farkindaligi amacli savunmaci calisma; gercek kimlik bilgisi "
                    "toplanmayacak ve operasyonel saldiri adimi verilmeyecek."
                ),
                "suggested_fix": "",
            },
        )

        self.assertTrue(merged.allowed)
        self.assertEqual(merged.review_source, "hybrid_llm_safe_educational")

    def test_llm_unsafe_category_overrides_allowed_flag(self):
        agent = AssignmentSafetyAgent()
        deterministic = agent.analyze(
            title="Guvenlik Odevi",
            description="Python ile genel bir guvenlik araci tasarlayin.",
            course_context="Python",
        )

        merged = agent._merge_llm_review(
            deterministic,
            {
                "allowed": True,
                "is_programming_assignment": True,
                "risk_categories": ["crime"],
                "reason": "Brief suc kategorisine giren somut bir istek iceriyor.",
                "suggested_fix": "",
            },
        )

        self.assertFalse(merged.allowed)
        self.assertTrue(any(issue.category == "crime" for issue in merged.issues))

    def test_keylogger_assignment_is_blocked(self):
        result = AssignmentSafetyAgent().analyze(
            title="Keylogger Araci",
            description="Kullanicinin sifrelerini toplayan ve uzaktaki sunucuya gonderen keylogger gelistirin.",
            course_context="Python",
        )

        self.assertFalse(result.allowed)
        self.assertTrue(any(issue.category == "crime" for issue in result.issues))

    def test_turkish_inflected_password_theft_is_blocked(self):
        result = AssignmentSafetyAgent().analyze(
            title="Şifre Hırsızlığı Aracı",
            description="Kullanıcının şifresini çalan ve uzaktaki sunucuya gönderen uygulama yazın.",
            course_context="Python",
        )

        self.assertFalse(result.allowed)
        self.assertTrue(any(issue.category == "crime" for issue in result.issues))

    def test_weapon_word_variants_are_blocked(self):
        result = AssignmentSafetyAgent().analyze(
            title="Envanter uygulamasi",
            description="Silahlarin stok, hedef ve kullanim plani bilgisini tutan bir uygulama yazin.",
            course_context="Python",
        )

        self.assertFalse(result.allowed)
        self.assertTrue(any(issue.category == "violence" for issue in result.issues))

    def test_turkish_profanity_in_description_is_blocked(self):
        result = AssignmentSafetyAgent().analyze(
            title="Liste Uygulamasi",
            description="Bu odevde amk basit bir liste yazacaksiniz.",
            course_context="Python programlama",
        )

        self.assertFalse(result.allowed)
        self.assertTrue(any(issue.category == "profanity" for issue in result.issues))

    def test_llm_approve_does_not_override_deterministic_profanity_block(self):
        agent = AssignmentSafetyAgent()
        deterministic = agent.analyze(
            title="Liste Uygulamasi",
            description="Bu odevde amk basit bir liste yazacaksiniz.",
            course_context="Python",
        )
        self.assertFalse(deterministic.allowed)

        merged = agent._merge_llm_review(
            deterministic,
            {
                "allowed": True,
                "is_programming_assignment": True,
                "risk_categories": [],
                "reason": "Zararsiz programlama odevi.",
                "suggested_fix": "",
            },
        )

        self.assertFalse(merged.allowed)
        self.assertEqual(merged.review_source, "hybrid_llm_deterministic_kept")
        self.assertTrue(any(issue.category == "profanity" for issue in merged.issues))

    def test_clean_assignment_description_is_allowed(self):
        result = AssignmentSafetyAgent().analyze(
            title="CSV Not Analizi",
            description="CSV dosyasindan not okuyup gecme durumunu hesaplayan CLI programi yazin.",
            course_context="Python programlama",
        )

        self.assertTrue(result.allowed)


if __name__ == "__main__":
    unittest.main()
