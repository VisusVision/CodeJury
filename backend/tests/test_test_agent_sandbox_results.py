"""TestAgent uses orchestrator sandbox test_results when present."""

from __future__ import annotations

import unittest

from backend.agents.test_agent import TestAgent, _programmatic_from_sandbox_tests


class TestAgentSandboxResultsTests(unittest.TestCase):
    def test_programmatic_from_sandbox_tests_scores_pass_and_fail(self):
        built = _programmatic_from_sandbox_tests(
            [
                {
                    "name": "stdin_smoke",
                    "passed": True,
                    "actual_stdout": "ok",
                    "expected_stdout": "ok",
                },
                {
                    "name": "edge_case",
                    "passed": False,
                    "actual_stdout": "bad",
                    "expected_stdout": "good",
                    "error": "stdout mismatch",
                },
            ],
            exit_code=0,
            exec_time_ms=12,
            peak_memory_mb=1.2,
        )

        self.assertIsNotNone(built)
        assert built is not None
        self.assertEqual(built["passed_tests"], 1)
        self.assertEqual(built["failed_tests"], 1)
        self.assertEqual(len(built["test_results"]), 2)
        self.assertFalse(built["runs_successfully"])
        self.assertLess(built["score"], 60)

    def test_programmatic_analysis_prefers_sandbox_test_results(self):
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "ignored",
            "stderr": "",
            "execution_time_ms": 5,
            "peak_memory_mb": 0.5,
            "test_results": [
                {
                    "name": "case_a",
                    "passed": True,
                    "actual_stdout": "1",
                    "expected_stdout": "1",
                },
                {
                    "name": "case_b",
                    "passed": True,
                    "actual_stdout": "2",
                    "expected_stdout": "2",
                },
            ],
        }
        code = "print('ok')\n"

        result = TestAgent()._programmatic_analysis(
            sandbox,
            None,
            code,
            "python",
            assignment_description="Basit CLI",
            task_alignment={"factor": 0.9, "reasons": []},
        )

        self.assertEqual(result["passed_tests"], 2)
        self.assertEqual(result["failed_tests"], 0)
        self.assertTrue(result["runs_successfully"])
        self.assertGreaterEqual(result["score"], 70)
        self.assertEqual(len(result["test_results"]), 2)


if __name__ == "__main__":
    unittest.main()
