import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.ai_authorship import AIAuthorshipAgent
from backend.agents.algorithm import AlgorithmAgent
from backend.agents.base import LLMInferenceError
from backend.core.config import settings


class AlgorithmAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._ollama_patch = patch.object(settings, "ollama_enabled", False)
        self._ollama_patch.start()
        self.addCleanup(self._ollama_patch.stop)

    async def test_uses_llm_algorithm_names_but_keeps_programmatic_complexity_guard(self):
        code = """
def two_sum(values, target):
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] + values[j] == target:
                return i, j
    return None
"""

        llm_payload = {
            "detected_algorithms": ["brute_force_pair_search"],
            "data_structures": ["list"],
            "time_complexity": "O(n)",
            "space_complexity": "O(1)",
            "expected_complexity": "O(n)",
            "complexity_gap": "matches_expected",
            "algorithm_analysis": "LLM algoritmayi brute force pair search olarak adlandirdi.",
            "data_structure_analysis": "Liste uzerinde indeks taramasi kullaniyor.",
            "issues": [
                {
                    "type": "complexity_gap",
                    "description": "Cozum O(n^2); odev beklentisi O(n) gorunuyor.",
                    "severity": "high",
                    "suggested_fix": "Tekrarlayan taramalari dict/set tabanli tek gecis yaklasimina indirin.",
                },
                {
                    "type": "nested_loop",
                    "description": "Ic ice dongu karmasikligi artiriyor.",
                    "severity": "medium",
                    "suggested_fix": "Lookup veya indeksleme icin uygun veri yapisi kullanin.",
                },
            ],
            "score": 95,
        }

        with (
            patch.object(settings, "ollama_enabled", True),
            patch("backend.agents.base.chat_json", new=AsyncMock(return_value=llm_payload)),
        ):
            result = await AlgorithmAgent().analyze(
                {
                    "source_code": code,
                    "language": "python",
                    "assignment_description": "Two Sum icin dict tabanli tek gecis O(n) cozum yazin.",
                }
            )

        self.assertIn("brute_force_pair_search", result["detected_algorithms"])
        self.assertEqual(result["time_complexity"], "O(n^2)")
        self.assertEqual(result["expected_complexity"], "O(n)")
        self.assertEqual(result["complexity_gap"], "worse_than_expected")
        self.assertTrue(any(issue["type"] == "complexity_gap" for issue in result["issues"]))
        issue_types = [issue["type"] for issue in result["issues"]]
        self.assertEqual(issue_types.count("complexity_gap"), 1)
        self.assertEqual(issue_types.count("nested_loop"), 1)
        self.assertLessEqual(result["score"], 55)
        self.assertEqual(result["llm_status"], "ok")

    async def test_falls_back_to_programmatic_analysis_when_llm_fails(self):
        code = """
def has_duplicate(values):
    seen = set()
    for value in values:
        if value in seen:
            return True
        seen.add(value)
    return False
"""

        agent = AlgorithmAgent()
        with patch.object(
            agent,
            "_call_llm",
            new=AsyncMock(side_effect=LLMInferenceError("bad json")),
        ):
            result = await agent.analyze(
                {
                    "source_code": code,
                    "language": "python",
                    "assignment_description": "Listeyi tek geciste O(n) karmasiklikla kontrol edin.",
                }
            )

        self.assertEqual(result["time_complexity"], "O(n)")
        self.assertIn("set", result["data_structures"])
        self.assertEqual(result["llm_status"], "fallback")
        self.assertIn("llm_inference_fallback", result["guardrail_flags"])
        self.assertEqual(result["schema_repair_count"], 0)
        self.assertIsNone(result["confidence"])

    async def test_flags_quadratic_solution_when_assignment_expects_linear(self):
        code = """
def has_duplicate(values):
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] == values[j]:
                return True
    return False
"""

        result = await AlgorithmAgent().analyze(
            {
                "source_code": code,
                "language": "python",
                "assignment_description": "Listeyi tek geciste O(n) karmasiklikla kontrol edin.",
            }
        )

        self.assertEqual(result["time_complexity"], "O(n^2)")
        self.assertEqual(result["expected_complexity"], "O(n)")
        self.assertEqual(result["complexity_gap"], "worse_than_expected")
        self.assertTrue(any(issue["type"] == "complexity_gap" for issue in result["issues"]))

    async def test_expected_complexity_prefers_declared_expected_over_rejected_slower_bound(self):
        code = """
def two_sum(values, target):
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] + values[j] == target:
                return i, j
    return None
"""

        result = await AlgorithmAgent().analyze(
            {
                "source_code": code,
                "language": "python",
                "assignment_description": (
                    "Beklenen algoritma: dict/set tabanli tek gecis O(n). "
                    "Ic ice dongu O(n^2) cozum beklenenden daha yavas kabul edilir."
                ),
            }
        )

        self.assertEqual(result["time_complexity"], "O(n^2)")
        self.assertEqual(result["expected_complexity"], "O(n)")
        self.assertEqual(result["complexity_gap"], "worse_than_expected")

    async def test_detects_binary_search_as_logarithmic(self):
        code = """
def binary_search(values, target):
    lo, hi = 0, len(values) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if values[mid] == target:
            return True
        if values[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return False
"""

        result = await AlgorithmAgent().analyze(
            {
                "source_code": code,
                "language": "python",
                "assignment_description": "Sirali listede O(log n) ikili arama yapin.",
            }
        )

        self.assertEqual(result["time_complexity"], "O(log n)")
        self.assertEqual(result["expected_complexity"], "O(log n)")
        self.assertEqual(result["complexity_gap"], "matches_expected")
        self.assertIn("binary_search", result["detected_algorithms"])
        self.assertNotIn("tuple", result["data_structures"])

    async def test_detects_recursion_without_general_iteration_fallback(self):
        code = """
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
"""

        result = await AlgorithmAgent().analyze(
            {
                "source_code": code,
                "language": "python",
                "assignment_description": "Faktoriyel fonksiyonu yazin.",
            }
        )

        self.assertEqual(result["time_complexity"], "O(recursive)")
        self.assertIn("recursion", result["detected_algorithms"])
        self.assertNotEqual(result["detected_algorithms"], ["general_iteration"])

    async def test_normalizes_malformed_llm_issue_objects_before_schema_validation(self):
        code = """
def two_sum(values, target):
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] + values[j] == target:
                return i, j
    return None
"""

        llm_payload = {
            "detected_algorithms": ["brute_force_pair_search"],
            "data_structures": ["list"],
            "time_complexity": "O(n)",
            "space_complexity": "O(1)",
            "expected_complexity": "O(n)",
            "complexity_gap": "matches_expected",
            "algorithm_analysis": "Ham issue nesneleri eksik alanlarla dondu.",
            "data_structure_analysis": "Liste kullaniliyor.",
            "issues": [
                {"message": "Ic ice dongu karmasikligi artiriyor.", "severity": 3},
                {"description": "Beklenenden daha yavas.", "suggestion": "Dict kullanin."},
            ],
            "score": 95,
        }

        with (
            patch.object(settings, "ollama_enabled", True),
            patch("backend.agents.base.chat_json", new=AsyncMock(return_value=llm_payload)),
        ):
            result = await AlgorithmAgent().analyze(
                {
                    "source_code": code,
                    "language": "python",
                    "assignment_description": "Two Sum icin dict tabanli tek gecis O(n) cozum yazin.",
                }
            )

        self.assertEqual(result["llm_status"], "ok")
        self.assertTrue(all("type" in issue for issue in result["issues"]))
        self.assertTrue(all("suggested_fix" in issue for issue in result["issues"]))
        self.assertTrue(all(isinstance(issue["severity"], str) for issue in result["issues"]))

    async def test_data_structure_detection_avoids_tuple_noise_from_parentheses(self):
        code = """
def first(values):
    return values[0] if values else None
"""

        result = await AlgorithmAgent().analyze(
            {
                "source_code": code,
                "language": "python",
                "assignment_description": "Ilk elemani O(1) sabit zamanda dondurun.",
            }
        )

        self.assertNotIn("tuple", result["data_structures"])


class AIAuthorshipAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_risk_without_emitting_grade_fields(self):
        code = """
def solve(data):
    # As an AI language model, I will provide the complete optimized solution.
    return sorted(data)
"""

        result = await AIAuthorshipAgent().analyze({"source_code": code, "language": "python"})

        self.assertEqual(result["risk_level"], "high")
        self.assertGreaterEqual(result["confidence"], 0.7)
        self.assertTrue(result["signals"])
        self.assertNotIn("score", result)
        self.assertNotIn("final_score", result)


if __name__ == "__main__":
    unittest.main()
