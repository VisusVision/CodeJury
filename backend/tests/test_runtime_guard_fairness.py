"""Runtime guard fairness when input files are missing from sandbox."""

from __future__ import annotations

import unittest

from backend.agents.master_evaluator import MasterEvaluatorAgent
from backend.agents.test_agent import looks_like_missing_input_file_error


class MissingInputFileDetectionTests(unittest.TestCase):
    def test_detects_filenotfound_in_stderr(self):
        self.assertTrue(
            looks_like_missing_input_file_error(
                "Traceback ... FileNotFoundError: [Errno 2] No such file: 'scores.csv'"
            )
        )

    def test_ignores_unrelated_runtime_errors(self):
        self.assertFalse(looks_like_missing_input_file_error("ValueError: invalid literal"))


class RuntimeGuardFairnessTests(unittest.TestCase):
    def _faculty_result(self) -> dict:
        return {
            "final_score": 88,
            "rubric_breakdown": [
                {"criterion": "c0", "label": "Gereksinimlere Uyum", "weight": 20, "score": 18, "weighted_score": 18},
                {"criterion": "c1", "label": "Calisabilirlik", "weight": 20, "score": 18, "weighted_score": 18},
                {"criterion": "c2", "label": "Guvenlik", "weight": 20, "score": 18, "weighted_score": 18},
            ],
            "weaknesses": [],
        }

    def test_missing_input_file_without_fixtures_uses_softer_cap(self):
        result = self._faculty_result()
        sandbox = {
            "compilation_success": True,
            "exit_code": 1,
            "stderr": "FileNotFoundError: scores.csv",
            "fixtures_provided": False,
        }
        MasterEvaluatorAgent._apply_runtime_guard(
            result,
            sandbox,
            source_code='path = Path("scores.csv")',
            language="python",
            faculty_mode=True,
            task_alignment_factor=0.95,
        )
        self.assertGreaterEqual(result["final_score"], 40)
        self.assertLessEqual(result["final_score"], 65)

    def test_missing_input_file_with_fixtures_keeps_standard_runtime_cap(self):
        result = self._faculty_result()
        sandbox = {
            "compilation_success": True,
            "exit_code": 1,
            "stderr": "FileNotFoundError: scores.csv",
            "fixtures_provided": True,
        }
        MasterEvaluatorAgent._apply_runtime_guard(
            result,
            sandbox,
            source_code='path = Path("scores.csv")',
            language="python",
            faculty_mode=True,
            task_alignment_factor=0.95,
        )
        self.assertLessEqual(result["final_score"], 55)


if __name__ == "__main__":
    unittest.main()
