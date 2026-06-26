import unittest

from backend.agents.ai_authorship import AIAuthorshipAgent
from backend.agents.algorithm import AlgorithmAgent


class AlgorithmAgentTests(unittest.IsolatedAsyncioTestCase):
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
