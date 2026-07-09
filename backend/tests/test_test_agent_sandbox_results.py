"""TestAgent uses orchestrator sandbox test_results when present."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.base import LLMInferenceError
from backend.agents.test_agent import TestAgent, _programmatic_from_sandbox_tests
from frontend.backend.main import _build_agents_list


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

    def test_empty_expected_output_list_uses_smoke_result(self):
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "ok\n",
            "stderr": "",
            "execution_time_ms": 5,
            "peak_memory_mb": 0.5,
            "test_results": [],
        }

        result = TestAgent()._programmatic_analysis(
            sandbox,
            [],
            "print('ok')\n",
            "python",
            assignment_description="Basit calisan Python programi.",
            task_alignment={"factor": 0.9, "reasons": []},
        )

        self.assertEqual(result["passed_tests"], 1)
        self.assertEqual(result["failed_tests"], 0)
        self.assertEqual(result["total_tests"], 1)
        self.assertGreaterEqual(result["score"], 80)

    def test_analyze_drops_llm_runtime_error_when_formal_tests_pass(self):
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "execution_time_ms": 5,
            "peak_memory_mb": 0.5,
            "test_results": [
                {
                    "name": "case_a",
                    "stdin": "6\n",
                    "passed": True,
                    "actual_stdout": "36",
                    "expected_stdout": "36\n",
                    "actual_exit_code": 0,
                },
                {
                    "name": "case_b",
                    "stdin": "0\n",
                    "passed": True,
                    "actual_stdout": "0",
                    "expected_stdout": "0\n",
                    "actual_exit_code": 0,
                },
            ],
        }
        expected = [
            {"name": "case_a", "stdin": "6\n", "expected_stdout": "36\n"},
            {"name": "case_b", "stdin": "0\n", "expected_stdout": "0\n"},
        ]
        agent = TestAgent()

        async def run_case():
            with patch.object(
                agent,
                "_call_llm",
                new=AsyncMock(
                    return_value={
                        "compilation_success": True,
                        "runs_successfully": False,
                        "passed_tests": 0,
                        "failed_tests": 1,
                        "test_failures": [{"test_name": "smoke", "reason": "EOFError"}],
                        "runtime_errors": ["EOFError: EOF when reading a line"],
                        "edge_case_handling": "poor",
                        "edge_cases_observed": [],
                        "performance_notes": "llm noise",
                        "score": 50,
                    }
                ),
            ):
                return await agent.analyze(
                    {
                        "sandbox_result": sandbox,
                        "expected_output": expected,
                        "source_code": "n=int(input())\nprint(n*n)\n",
                        "language": "python",
                        "assignment_description": "Sayinin karesini yazdirin.",
                    }
                )

        result = asyncio.run(run_case())

        self.assertEqual(result["runtime_errors"], [])
        self.assertEqual(result["test_failures"], [])
        self.assertTrue(result["runs_successfully"])
        self.assertGreaterEqual(result["score"], 85)
        self.assertIn("test_agent_score_repaired_programmatic_floor", result.get("guardrail_flags", []))

    def test_analyze_repairs_zero_llm_score_when_sandbox_tests_pass(self):
        sandbox = {
            "compilation_success": True,
            "exit_code": 2,
            "stdout": "",
            "stderr": (
                "usage: submission.py [-h] log_file\n"
                "submission.py: error: the following arguments are required: log_file\n"
            ),
            "execution_time_ms": 8,
            "peak_memory_mb": 0.5,
            "test_results": [
                {
                    "name": "cli_usage",
                    "stdin": "",
                    "passed": True,
                    "actual_stdout": "",
                    "actual_stderr": (
                        "usage: submission.py [-h] log_file\n"
                        "submission.py: error: the following arguments are required: log_file\n"
                    ),
                    "expected_stdout": "CLI argumani istendiginde kullanim mesaji uretilmesi",
                    "actual_exit_code": 2,
                },
            ],
        }
        agent = TestAgent()

        async def run_case():
            with patch.object(
                agent,
                "_call_llm",
                new=AsyncMock(
                    return_value={
                        "compilation_success": True,
                        "runs_successfully": True,
                        "passed_tests": 1,
                        "failed_tests": 0,
                        "test_failures": [],
                        "runtime_errors": [],
                        "edge_case_handling": "fair",
                        "edge_cases_observed": [],
                        "performance_notes": "Calisti.",
                        "score": 0,
                    }
                ),
            ):
                return await agent.analyze(
                    {
                        "sandbox_result": sandbox,
                        "expected_output": [],
                        "source_code": "import argparse\nparser=argparse.ArgumentParser()\nparser.add_argument('log_file')\n",
                        "language": "python",
                        "assignment_description": "Log dosyasini okuyup ERROR, WARNING ve INFO sayilarini raporlayan CLI yazin.",
                        "task_alignment": {"factor": 1.0, "reasons": []},
                    }
                )

        result = asyncio.run(run_case())

        self.assertTrue(result["runs_successfully"])
        self.assertEqual(result["passed_tests"], 1)
        self.assertGreaterEqual(result["score"], 50)
        self.assertIn("test_agent_score_repaired_sandbox_pass", result.get("guardrail_flags", []))

    def test_service_timeout_llm_score_repaired_from_programmatic(self):
        code = (
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "class H(BaseHTTPRequestHandler):\n"
            "    pass\n"
            "HTTPServer(('127.0.0.1', 8080), H).serve_forever()\n"
        )
        sandbox = {
            "compilation_success": True,
            "exit_code": 1,
            "stdout": "",
            "stderr": "TimeoutError: code did not finish within 10 seconds",
            "timed_out": True,
            "execution_time_ms": 10000,
            "peak_memory_mb": 12,
            "test_results": [],
        }
        agent = TestAgent()

        async def run_case():
            with patch.object(
                agent,
                "_call_llm",
                new=AsyncMock(
                    return_value={
                        "compilation_success": True,
                        "runs_successfully": True,
                        "passed_tests": 1,
                        "failed_tests": 0,
                        "test_failures": [],
                        "runtime_errors": [],
                        "edge_case_handling": "fair",
                        "edge_cases_observed": [],
                        "performance_notes": "Timeout.",
                        "score": 10,
                    }
                ),
            ):
                return await agent.analyze(
                    {
                        "sandbox_result": sandbox,
                        "expected_output": [],
                        "source_code": code,
                        "language": "python",
                        "assignment_description": "POST /clean ve PUT /beautify endpointleri sunan mini API gelistirin.",
                        "task_alignment": {"factor": 1.0, "reasons": []},
                    }
                )

        result = asyncio.run(run_case())

        self.assertTrue(result["runs_successfully"])
        self.assertGreaterEqual(result["score"], 50)
        self.assertIn("test_agent_score_repaired_service_runtime", result.get("guardrail_flags", []))

    def test_service_sandbox_tests_failure_accepted_as_runtime(self):
        code = (
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "class H(BaseHTTPRequestHandler):\n"
            "    pass\n"
            "HTTPServer(('127.0.0.1', 8080), H).serve_forever()\n"
        )
        sandbox = {
            "compilation_success": True,
            "exit_code": 1,
            "stdout": "",
            "stderr": "Connection refused",
            "timed_out": False,
            "execution_time_ms": 1200,
            "peak_memory_mb": 12,
            "test_results": [
                {
                    "name": "post_clean",
                    "passed": False,
                    "error": "Connection refused",
                    "actual_stderr": "Connection refused",
                }
            ],
        }
        agent = TestAgent()

        async def run_case():
            with patch.object(
                agent,
                "_call_llm",
                new=AsyncMock(
                    return_value={
                        "compilation_success": True,
                        "runs_successfully": False,
                        "passed_tests": 0,
                        "failed_tests": 1,
                        "test_failures": [],
                        "runtime_errors": ["Connection refused"],
                        "edge_case_handling": "poor",
                        "edge_cases_observed": [],
                        "performance_notes": "Ag testi basarisiz.",
                        "score": 15,
                    }
                ),
            ):
                return await agent.analyze(
                    {
                        "sandbox_result": sandbox,
                        "expected_output": [],
                        "source_code": code,
                        "language": "python",
                        "assignment_description": "POST /clean ve PUT /beautify endpointleri sunan mini API gelistirin.",
                        "task_alignment": {"factor": 1.0, "reasons": []},
                    }
                )

        result = asyncio.run(run_case())

        self.assertTrue(result["runs_successfully"])
        self.assertTrue(result.get("service_runtime_accepted"))
        self.assertGreaterEqual(result["score"], 50)

    def test_http_client_smoke_exit_zero_accepted(self):
        code = (
            "import os\n"
            "import urllib.request\n\n"
            "def fetch_status():\n"
            "    with urllib.request.urlopen('https://example.com/health', timeout=5) as r:\n"
            "        return int(r.status)\n\n"
            "if __name__ == '__main__':\n"
            "    print(os.environ.get('API_URL', 'https://example.com'))\n"
        )
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "https://example.com\n",
            "stderr": "",
            "execution_time_ms": 40,
            "peak_memory_mb": 8,
            "test_results": [
                {
                    "name": "fetch_status",
                    "passed": False,
                    "error": "urlopen error [Errno 11001] getaddrinfo failed",
                }
            ],
        }
        agent = TestAgent()

        async def run_case():
            with patch.object(
                agent,
                "_call_llm",
                new=AsyncMock(
                    return_value={
                        "compilation_success": True,
                        "runs_successfully": False,
                        "passed_tests": 0,
                        "failed_tests": 1,
                        "test_failures": [],
                        "runtime_errors": [],
                        "edge_case_handling": "fair",
                        "edge_cases_observed": [],
                        "performance_notes": "",
                        "score": 0,
                    }
                ),
            ):
                return await agent.analyze(
                    {
                        "sandbox_result": sandbox,
                        "expected_output": [],
                        "source_code": code,
                        "language": "python",
                        "assignment_description": "Harici API'den yapilandirma ceken ve sonucu yazdiran istemci yazin.",
                        "task_alignment": {"factor": 1.0, "reasons": []},
                    }
                )

        result = asyncio.run(run_case())

        self.assertTrue(result["runs_successfully"])
        self.assertTrue(result.get("service_runtime_accepted"))
        self.assertGreaterEqual(result["score"], 58)

    def test_analyze_falls_back_when_llm_response_missing_score(self):
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "ok\n",
            "stderr": "",
            "execution_time_ms": 5,
            "peak_memory_mb": 0.5,
            "test_results": [
                {
                    "name": "case_a",
                    "stdin": "",
                    "passed": True,
                    "actual_stdout": "ok",
                    "expected_stdout": "ok\n",
                    "actual_exit_code": 0,
                },
            ],
        }
        agent = TestAgent()

        async def run_case():
            with patch.object(
                agent,
                "_call_llm",
                new=AsyncMock(
                    side_effect=LLMInferenceError(
                        "[test_agent] Missing required keys in LLM response: score"
                    )
                ),
            ):
                return await agent.analyze(
                    {
                        "sandbox_result": sandbox,
                        "expected_output": [{"name": "case_a", "expected_stdout": "ok\n"}],
                        "source_code": "print('ok')\n",
                        "language": "python",
                        "assignment_description": "ok yazdirin.",
                    }
                )

        result = asyncio.run(run_case())

        self.assertEqual(result["llm_status"], "fallback")
        self.assertIn("llm_inference_fallback", result["guardrail_flags"])
        self.assertEqual(result["schema_repair_count"], 0)
        self.assertIsNone(result["confidence"])
        self.assertTrue(result["runs_successfully"])
        self.assertEqual(result["passed_tests"], 1)
        self.assertGreaterEqual(result["score"], 85)

    def test_analyze_normalizes_parseable_llm_response_missing_score(self):
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "ok\n",
            "stderr": "",
            "execution_time_ms": 5,
            "peak_memory_mb": 0.5,
            "test_results": [
                {
                    "name": "case_a",
                    "stdin": "",
                    "passed": True,
                    "actual_stdout": "ok",
                    "expected_stdout": "ok\n",
                    "actual_exit_code": 0,
                },
            ],
        }
        agent = TestAgent()
        llm_payload_without_score = {
            "compilation_success": True,
            "runs_successfully": True,
            "passed_tests": 1,
            "failed_tests": 0,
            "test_failures": [],
            "runtime_errors": [],
            "edge_case_handling": "fair",
            "edge_cases_observed": [],
            "performance_notes": "Calisti.",
        }

        async def run_case():
            with (
                patch("backend.agents.base.settings.ollama_enabled", True),
                patch("backend.agents.base.chat_json", new=AsyncMock(return_value=llm_payload_without_score)) as chat,
            ):
                result = await agent.analyze(
                    {
                        "sandbox_result": sandbox,
                        "expected_output": [{"name": "case_a", "expected_stdout": "ok\n"}],
                        "source_code": "print('ok')\n",
                        "language": "python",
                        "assignment_description": "ok yazdirin.",
                    }
                )
                return result, chat.await_count

        result, call_count = asyncio.run(run_case())

        self.assertNotEqual(result.get("llm_status"), "fallback")
        self.assertIn("test_agent_score_defaulted", result.get("guardrail_flags", []))
        self.assertEqual(call_count, 1)
        self.assertTrue(result["runs_successfully"])
        self.assertEqual(result["passed_tests"], 1)
        self.assertGreaterEqual(result["score"], 80)
        self.assertIn("test_agent_score_repaired_programmatic_floor", result.get("guardrail_flags", []))

    def test_failed_sandbox_case_preserves_input_expected_actual_evidence(self):
        built = _programmatic_from_sandbox_tests(
            [
                {
                    "name": "divide_by_zero_edge",
                    "stdin": "10 0\n",
                    "passed": False,
                    "actual_stdout": "",
                    "actual_stderr": "Traceback...\nZeroDivisionError: division by zero",
                    "expected_stdout": "HATA: sifira bolme\n",
                    "error": "Exit code: expected=0, actual=1",
                },
            ],
            exit_code=1,
            exec_time_ms=8,
            peak_memory_mb=1.0,
            stderr="",
        )

        self.assertIsNotNone(built)
        assert built is not None
        self.assertFalse(built["runs_successfully"])
        self.assertEqual(built["passed_tests"], 0)
        self.assertEqual(built["failed_tests"], 1)
        self.assertEqual(built["test_results"][0]["input"], "10 0\n")
        self.assertEqual(built["test_results"][0]["expected"], "HATA: sifira bolme\n")
        self.assertIn("ZeroDivisionError", built["test_results"][0]["actual"])
        self.assertTrue(any("ZeroDivisionError" in err for err in built["runtime_errors"]))
        self.assertLessEqual(built["score"], 35)

    def test_mixed_pass_fail_sandbox_cases_get_partial_credit(self):
        built = _programmatic_from_sandbox_tests(
            [
                {
                    "name": "normal_case",
                    "stdin": "4\n",
                    "passed": True,
                    "actual_stdout": "16\n",
                    "expected_stdout": "16\n",
                },
                {
                    "name": "zero_division_edge",
                    "stdin": "10 0\n",
                    "passed": False,
                    "actual_stderr": "ZeroDivisionError: division by zero",
                    "expected_stdout": "HATA\n",
                    "error": "Exit code: expected=0, actual=1",
                },
            ],
            exit_code=1,
            exec_time_ms=8,
            peak_memory_mb=1.0,
            stderr="",
        )

        self.assertIsNotNone(built)
        assert built is not None
        self.assertFalse(built["runs_successfully"])
        self.assertEqual(built["passed_tests"], 1)
        self.assertEqual(built["failed_tests"], 1)
        self.assertGreaterEqual(built["score"], 22)
        self.assertLessEqual(built["score"], 55)

    def test_programmatic_analysis_marks_hidden_sandbox_cases_from_expected_metadata(self):
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "execution_time_ms": 5,
            "peak_memory_mb": 1.0,
            "test_results": [
                {
                    "name": "hidden_edge",
                    "stdin": "10 0\n",
                    "expected_stdout": "HATA\n",
                    "actual_stdout": "HATA\n",
                    "passed": True,
                }
            ],
        }
        expected = [
            {
                "name": "hidden_edge",
                "stdin": "10 0\n",
                "expected_stdout": "HATA\n",
                "visibility": "hidden",
            }
        ]

        result = TestAgent()._programmatic_analysis(sandbox, expected, "print('x')", "python")

        self.assertEqual(result["test_results"][0]["visibility"], "hidden")

    def test_frontend_testing_agent_shows_input_expected_actual_for_cases(self):
        agents = _build_agents_list(
            {"time_complexity": "O(n)", "score": 80, "issues": []},
            {"estimated_level": "mid", "score": 70, "immaturity_indicators": [], "maturity_indicators": []},
            {"naming_quality": "good", "score": 75, "style_violations": []},
            {"risk_level": "safe", "total_threats": 0, "score": 100, "threats": []},
            {
                "compilation_success": True,
                "runs_successfully": False,
                "passed_tests": 1,
                "failed_tests": 1,
                "score": 45,
                "test_results": [
                    {
                        "test_name": "normal_case",
                        "input": "4\n",
                        "expected": "16\n",
                        "actual": "16\n",
                        "passed": True,
                    },
                    {
                        "test_name": "zero_division_edge",
                        "input": "10 0\n",
                        "expected": "HATA\n",
                        "actual": "ZeroDivisionError\n",
                        "passed": False,
                    },
                ],
                "test_failures": [
                    "ZeroDivisionError: division by zero",
                    {"test_name": "zero_division_edge", "reason": "ZeroDivisionError"},
                ],
                "runtime_errors": ["ZeroDivisionError: sifira bolme hatasi"],
            },
            {"total_claims_received": 0, "total_claims_validated": 0, "validated_claims": []},
        )

        testing = next(agent for agent in agents if agent["id"] == "testing")
        messages = "\n".join(finding["message"] for finding in testing["findings"])
        self.assertEqual(len(testing["testResults"]), 2)
        self.assertEqual(testing["testResults"][0]["name"], "normal_case")
        self.assertEqual(testing["testResults"][0]["input"], "4\n")
        self.assertEqual(testing["testResults"][1]["actual"], "ZeroDivisionError\n")
        self.assertIn("normal_case", messages)
        self.assertIn("Girdi: 4", messages)
        self.assertIn("Beklenen: 16", messages)
        self.assertIn("Gercek: 16", messages)
        self.assertIn("zero_division_edge", messages)
        self.assertIn("ZeroDivisionError", messages)

    def test_frontend_testing_agent_hides_hidden_case_io(self):
        agents = _build_agents_list(
            {"time_complexity": "O(n)", "score": 80, "issues": []},
            {"estimated_level": "mid", "score": 70, "immaturity_indicators": [], "maturity_indicators": []},
            {"naming_quality": "good", "score": 75, "style_violations": []},
            {"risk_level": "safe", "total_threats": 0, "score": 100, "threats": []},
            {
                "compilation_success": True,
                "runs_successfully": False,
                "passed_tests": 0,
                "failed_tests": 1,
                "score": 30,
                "test_results": [
                    {
                        "test_name": "hidden_edge",
                        "input": "10 0\n",
                        "expected": "HATA\n",
                        "actual": "ZeroDivisionError\n",
                        "passed": False,
                        "visibility": "hidden",
                    },
                ],
                "test_failures": [],
                "runtime_errors": ["ZeroDivisionError: sifira bolme hatasi"],
            },
            {"total_claims_received": 0, "total_claims_validated": 0, "validated_claims": []},
        )

        testing = next(agent for agent in agents if agent["id"] == "testing")
        messages = "\n".join(finding["message"] for finding in testing["findings"])
        self.assertEqual(testing["testResults"][0]["visibility"], "hidden")
        self.assertEqual(testing["testResults"][0]["input"], "10 0\n")
        self.assertEqual(testing["testResults"][0]["expected"], "HATA\n")
        self.assertEqual(testing["testResults"][0]["actual"], "ZeroDivisionError\n")
        self.assertIn("hidden_edge", messages)
        self.assertIn("Gizli test", messages)
        self.assertIn("Girdi: 10 0", messages)
        self.assertIn("Beklenen: HATA", messages)
        self.assertIn("Gercek: ZeroDivisionError", messages)

    def test_smoke_stack_solution_gets_static_coverage_and_higher_score(self):
        from pathlib import Path

        code = Path("scripts/demo/stack_uygun.py").read_text(encoding="utf-8")
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "2\n2\n1\n",
            "stderr": "",
            "execution_time_ms": 8,
            "peak_memory_mb": 0.5,
            "test_results": [],
        }
        agent = TestAgent()

        async def run_case():
            with patch.object(
                agent,
                "_call_llm",
                new=AsyncMock(
                    return_value={
                        "compilation_success": True,
                        "runs_successfully": True,
                        "passed_tests": 1,
                        "failed_tests": 0,
                        "test_failures": [],
                        "runtime_errors": [],
                        "edge_case_handling": "fair",
                        "edge_cases_observed": [],
                        "performance_notes": "Smoke only.",
                        "score": 60,
                    }
                ),
            ):
                return await agent.analyze(
                    {
                        "sandbox_result": sandbox,
                        "expected_output": [],
                        "source_code": code,
                        "language": "python",
                        "assignment_description": Path("scripts/demo/stack_brief.txt").read_text(encoding="utf-8"),
                        "task_alignment": {"factor": 1.0, "reasons": []},
                    }
                )

        result = asyncio.run(run_case())

        self.assertTrue(result["runs_successfully"])
        self.assertGreaterEqual(result.get("static_checks_passed", 0), 3)
        self.assertGreaterEqual(result["passed_tests"], 4)
        self.assertIn("static:", result["test_results"][1]["test_name"])
        self.assertGreaterEqual(result["score"], 82)
        self.assertIn("test_agent_score_repaired_programmatic_floor", result.get("guardrail_flags", []))

    def test_unsafe_stack_gets_low_test_score(self):
        from pathlib import Path

        code = Path("scripts/demo/stack_guvensiz.py").read_text(encoding="utf-8")
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "pwned\n",
            "stderr": "",
            "execution_time_ms": 8,
            "peak_memory_mb": 0.5,
            "test_results": [],
        }
        result = TestAgent()._programmatic_analysis(
            sandbox,
            [],
            code,
            "python",
            assignment_description=Path("scripts/demo/stack_brief.txt").read_text(encoding="utf-8"),
            task_alignment={"factor": 0.2, "reasons": ["eval"], "llm_off_topic": True},
        )
        self.assertFalse(result["runs_successfully"])
        self.assertLessEqual(result["score"], 40)
        self.assertEqual(result["edge_case_handling"], "poor")
        self.assertTrue(any(t.get("test_name") == "security:unsafe_runtime" for t in result["test_results"]))

    def test_off_topic_stack_html_gets_capped_test_score(self):
        from pathlib import Path

        code = Path("scripts/demo/stack_alakasiz.py").read_text(encoding="utf-8")
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "<!doctype html>",
            "stderr": "",
            "execution_time_ms": 8,
            "peak_memory_mb": 0.5,
            "test_results": [],
        }
        result = TestAgent()._programmatic_analysis(
            sandbox,
            [],
            code,
            "python",
            assignment_description=Path("scripts/demo/stack_brief.txt").read_text(encoding="utf-8"),
            task_alignment={"factor": 0.1, "reasons": ["off topic"], "llm_off_topic": True},
        )
        self.assertLessEqual(result["score"], 40)
        self.assertEqual(result["edge_case_handling"], "poor")


if __name__ == "__main__":
    unittest.main()
