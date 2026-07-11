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

    async def test_evidence_first_merge_caps_llm_score_and_preserves_ast_facts(self):
        """Supersedes stale ``test_uses_llm_algorithm_names_and_score_with_programmatic_complexity_facts``.

        Baseline transition: LLM may enrich explanation but cannot lower proven complexity,
        override verified expectation, or exceed deterministic score caps.
        """
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
            "expected_complexity": "O(n^2)",
            "complexity_gap": "matches_expected",
            "algorithm_analysis": "LLM algoritmayi brute force pair search olarak adlandirdi.",
            "data_structure_analysis": "Liste uzerinde indeks taramasi kullaniyor.",
            "recommended_approach": "Dict tabanli tek gecis hash lookup kullanin.",
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
                    "algorithm_expectation": {
                        "expected_complexity": {
                            "expression": "O(n)",
                            "family": "single_variable",
                            "rank": 2,
                            "confidence": 1.0,
                            "source": "verified_expectation",
                        },
                        "algorithm_families": ["hash_lookup"],
                        "expected_approach": "hash lookup",
                        "verification_status": "verified",
                        "version": 3,
                    },
                }
            )

        self.assertIn("brute_force_nested_scan", result["detected_algorithms"])
        self.assertNotIn("brute_force_pair_search", result["detected_algorithms"])
        self.assertEqual(result["time_complexity"], "O(n^2)")
        self.assertEqual(result["expected_complexity"], "O(n)")
        self.assertEqual(result["expected_source"], "verified_expectation")
        self.assertEqual(result["complexity_gap"], "worse_than_expected")
        self.assertLessEqual(result["score"], 65)
        self.assertIn("algorithm_llm_score_capped", result["guardrail_flags"])
        self.assertEqual(result["llm_status"], "ok")

    async def test_cpp_java_unknown_gap_without_penalty(self):
        code = """
#include <vector>
#include <algorithm>

std::vector<int> sorted_values(std::vector<int> values) {
    std::sort(values.begin(), values.end());
    return values;
}
"""
        result = await AlgorithmAgent().analyze(
            {
                "source_code": code,
                "language": "cpp",
                "assignment_description": "Sort vector values in O(n log n).",
            }
        )

        self.assertEqual(result["complexity_gap"], "unknown")
        self.assertLess(result["actual_confidence"], 0.5)
        self.assertNotIn("algorithm_gap_penalty", result.get("guardrail_flags", []))

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

    async def test_verified_expectation_overrides_llm_expected_complexity(self):
        code = """
def two_sum(values, target):
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] + values[j] == target:
                return i, j
    return None
"""
        llm_payload = {
            "detected_algorithms": ["nested_loop"],
            "data_structures": ["list"],
            "time_complexity": "O(n^2)",
            "space_complexity": "O(1)",
            "expected_complexity": "O(n^2)",
            "complexity_gap": "matches_expected",
            "algorithm_analysis": "LLM bekleneni O(n^2) olarak degistirdi.",
            "data_structure_analysis": "Liste kullaniliyor.",
            "recommended_approach": "Degistirilmis yaklasim.",
            "issues": [],
            "score": 90,
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
                    "algorithm_expectation": {
                        "expected_complexity": {
                            "expression": "O(n)",
                            "family": "single_variable",
                            "rank": 2,
                            "confidence": 1.0,
                            "source": "verified_expectation",
                        },
                        "algorithm_families": ["hash_lookup"],
                        "verification_status": "verified",
                    },
                }
            )

        self.assertEqual(result["expected_complexity"], "O(n)")
        self.assertEqual(result["complexity_gap"], "worse_than_expected")

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

        self.assertEqual(result["time_complexity"], "O(n)")
        self.assertIn("recursion", result["detected_algorithms"])
        self.assertNotEqual(result["detected_algorithms"], ["general_iteration"])

    async def test_stack_wrapper_methods_do_not_look_recursive(self):
        code = """
class Stack:
    def __init__(self):
        self._items = []

    def push(self, item):
        self._items.append(item)

    def remove_top(self):
        if self.is_empty():
            raise IndexError("empty stack")
        return self._items.pop()

    def peek(self):
        if self.is_empty():
            raise IndexError("empty stack")
        return self._items[-1]

    def is_empty(self):
        return len(self._items) == 0
"""

        result = await AlgorithmAgent().analyze(
            {
                "source_code": code,
                "language": "python",
                "assignment_description": "Stack LIFO veri yapisi yazin; push islemi O(1) olmalidir.",
            }
        )

        self.assertIn("stack", result["detected_algorithms"])
        self.assertNotIn("recursion", result["detected_algorithms"])
        self.assertNotIn("branching_recursion", result["detected_algorithms"])

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
            "recommended_approach": "Dict tabanli tek gecis kullanin.",
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

    def test_merge_algorithm_results_caps_llm_score_via_guardrail(self):
        from backend.agents.algorithm import _merge_algorithm_results
        from backend.agents.algorithm_evidence import build_evidence_algorithm_result

        code = """
def two_sum(values, target):
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] + values[j] == target:
                return i, j
    return None
"""
        evidence = build_evidence_algorithm_result(
            code,
            "python",
            algorithm_expectation={
                "expected_complexity": {
                    "expression": "O(n)",
                    "family": "single_variable",
                    "rank": 2,
                    "confidence": 1.0,
                    "source": "verified_expectation",
                },
                "algorithm_families": ["hash_lookup"],
            },
        )
        programmatic = {
            "score": 90,
            "time_complexity": "O(n^2)",
            "expected_complexity": "O(n)",
            "issues": [],
            "detected_algorithms": list(evidence.detected_algorithms),
            "data_structures": list(evidence.data_structures),
        }
        merged = _merge_algorithm_results(
            programmatic,
            {"score": 88, "algorithm_analysis": "LLM analizi", "issues": []},
            source=code,
            evidence=evidence,
        )
        self.assertLessEqual(merged["score"], 65)
        self.assertIn("algorithm_llm_score_capped", merged["guardrail_flags"])

    def test_empty_complexity_gap_normalizes_to_unknown_before_schema(self):
        agent = AlgorithmAgent()
        normalized = agent._pre_schema_normalize({"complexity_gap": "", "issues": []}, None)
        self.assertEqual(normalized["complexity_gap"], "unknown")
        normalized2 = agent._pre_schema_normalize({"complexity_gap": "not-a-valid-gap", "issues": []}, None)
        self.assertEqual(normalized2["complexity_gap"], "unknown")


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
