import unittest

from backend.agents.algorithm import _build_programmatic_algorithm_result, _merge_algorithm_results
from backend.agents.code_utils import (
    build_focused_code_excerpt,
    enrich_issue_with_line,
    enrich_seniority_indicators,
    enrich_text_indicator,
    find_relevant_lines,
)
from backend.agents.evidence import _collect_evidence_focus_lines
from backend.agents.seniority import SeniorityAgent


NESTED_LOOP_CODE = """
def find_pair(nums, target):
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                return (i, j)
    return None
""".strip()


class EvidenceLineHintTests(unittest.TestCase):
    def test_find_relevant_lines_matches_identifier(self):
        lines = ["def add(a, b):", "    return a + b"]
        found = find_relevant_lines("add fonksiyonu cok kisa", lines)
        self.assertIn(1, found)

    def test_enrich_issue_with_line_from_description(self):
        lines = NESTED_LOOP_CODE.splitlines()
        issue = enrich_issue_with_line(
            {"description": "find_pair fonksiyonunda ic ice dongu var.", "severity": "medium"},
            lines,
        )
        self.assertGreaterEqual(issue.get("line", 0), 1)

    def test_programmatic_algorithm_nested_loop_gets_line(self):
        result = _build_programmatic_algorithm_result(NESTED_LOOP_CODE, "python", "O(n) bekleniyor")
        nested = next(i for i in result["issues"] if i.get("type") == "nested_loop")
        self.assertIsInstance(nested.get("line"), int)
        self.assertGreater(nested["line"], 0)

    def test_merge_algorithm_enriches_llm_issues(self):
        programmatic = _build_programmatic_algorithm_result(NESTED_LOOP_CODE, "python", "O(n) bekleniyor")
        llm_result = {
            "detected_algorithms": ["nested_loop"],
            "data_structures": ["list"],
            "time_complexity": "O(n^2)",
            "space_complexity": "O(1)",
            "expected_complexity": "O(n)",
            "complexity_gap": "worse_than_expected",
            "algorithm_analysis": "Nested scan.",
            "data_structure_analysis": "List only.",
            "issues": [
                {
                    "type": "algorithm_observation",
                    "description": "find_pair ic ice dongu kullaniyor.",
                    "severity": "medium",
                }
            ],
            "score": 55,
        }
        merged = _merge_algorithm_results(programmatic, llm_result, source=NESTED_LOOP_CODE)
        issue = next(i for i in merged["issues"] if "find_pair" in i.get("description", ""))
        self.assertIsInstance(issue.get("line"), int)
        self.assertGreater(issue["line"], 0)

    def test_seniority_indicators_receive_line_hints(self):
        code = "def process(items):\n    return [x * 2 for x in items]\n"
        enriched = enrich_seniority_indicators(
            {"immaturity_indicators": ["process fonksiyonunda type hint yok"]},
            code,
        )
        self.assertRegex(enriched["immaturity_indicators"][0], r"satir\s+\d+", enriched["immaturity_indicators"][0])

    def test_seniority_programmatic_enriched_on_fallback(self):
        agent = SeniorityAgent()
        result = agent._programmatic_analysis(
            "def foo():\n    pass\n",
            "python",
        )
        enriched = enrich_seniority_indicators(result, "def foo():\n    pass\n")
        self.assertTrue(enriched.get("immaturity_indicators") or enriched.get("maturity_indicators"))

    def test_build_focused_code_excerpt_keeps_middle_claim_window(self):
        lines = [f"x = {i}" for i in range(400)]
        source = "\n".join(lines)
        excerpt = build_focused_code_excerpt(source, [210], max_lines=280)
        self.assertIn("x = 210", excerpt)
        self.assertIn("x = 0", excerpt)
        self.assertIn("x = 399", excerpt)

    def test_collect_evidence_focus_lines_from_findings(self):
        focus = _collect_evidence_focus_lines(
            {
                "algorithm": {
                    "issues": [{"description": "nested loop", "line": 12}],
                },
                "seniority": {
                    "immaturity_indicators": ["type hint yok (satir 4)"],
                },
            },
            {"validated_claims": [{"lines": [7], "feedback": "x"}]},
        )
        self.assertEqual(sorted(focus), [4, 7, 12])


if __name__ == "__main__":
    unittest.main()
