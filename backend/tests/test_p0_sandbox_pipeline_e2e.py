"""
P0 end-to-end tests: sandbox fixture injection through the analysis pipeline.

Deterministic layers run without Ollama; the pipeline integration test mocks LLM
agents but executes the real sandbox path (simulate or pool).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.sandbox.executor import run_in_sandbox
from backend.sandbox.fixtures import infer_sandbox_files
from frontend.backend import main

_CSV_BRIEF = (
    "CSV dosyasindan ogrenci adi ve not okuyup gecme/kalma durumunu hesaplayan, "
    "sonucu yeni bir CSV rapor dosyasina yazan CLI programi"
)

_UYGUN_CSV_CODE = '''"""CSV not analizi - odevle uyumlu cozum."""

from __future__ import annotations

import csv
from pathlib import Path


PASS_THRESHOLD = 60


def read_scores(input_path: Path) -> list[dict[str, str]]:
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def summarize(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for row in rows:
        name = row.get("name", "").strip()
        score_text = row.get("score", "0").strip() or "0"
        score = int(score_text)
        status = "passed" if score >= PASS_THRESHOLD else "failed"
        summary.append({"name": name, "score": str(score), "status": status})
    return summary


def export_report(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "score", "status"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    input_path = Path("scores.csv")
    output_path = Path("report.csv")
    rows = read_scores(input_path)
    export_report(summarize(rows), output_path)
    print(f"{output_path} yazildi")


if __name__ == "__main__":
    main()
'''


def _good_agent_payload() -> dict:
    return {
        "score": 85,
        "issues": [],
        "style_violations": [],
        "threats": [],
        "critical_count": 0,
        "high_count": 0,
        "risk_level": "safe",
        "safe": True,
        "compilation_success": True,
        "runs_successfully": True,
        "estimated_level": "mid",
        "naming_quality": "good",
        "time_complexity": "O(n)",
        "validated_claims": [],
        "total_claims_received": 0,
        "total_claims_validated": 0,
        "llm_status": "skipped_no_claims",
    }


def _good_master_payload() -> dict:
    return {
        "final_score": 88,
        "rubric_breakdown": [
            {
                "criterion": "c0",
                "label": "Gereksinimlere Uyum",
                "weight": 25,
                "score": 22,
                "weighted_score": 22,
            },
            {
                "criterion": "c1",
                "label": "Calisabilirlik",
                "weight": 25,
                "score": 22,
                "weighted_score": 22,
            },
            {
                "criterion": "c2",
                "label": "Kod Kalitesi",
                "weight": 25,
                "score": 22,
                "weighted_score": 22,
            },
            {
                "criterion": "c3",
                "label": "Guvenlik",
                "weight": 25,
                "score": 22,
                "weighted_score": 22,
            },
        ],
        "strengths": ["CSV okuma ve rapor yazma dogru."],
        "weaknesses": [],
        "summary": "Odev beklentilerini karsiliyor.",
    }


class P0SandboxChainE2ETests(unittest.TestCase):
    def test_uygun_csv_code_succeeds_when_fixtures_injected(self):
        files = infer_sandbox_files(
            assignment_brief=_CSV_BRIEF,
            source_code=_UYGUN_CSV_CODE,
        )
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "scores.csv")

        result = run_in_sandbox(_UYGUN_CSV_CODE, "python", files=files)
        self.assertEqual(result["exit_code"], 0, result.get("stderr"))
        self.assertTrue(result.get("fixtures_provided"))
        self.assertIn("report.csv yazildi", result.get("stdout", ""))

    def test_uygun_csv_code_fails_without_fixtures(self):
        result = run_in_sandbox(_UYGUN_CSV_CODE, "python", files=[])
        self.assertNotEqual(result["exit_code"], 0)
        self.assertFalse(result.get("fixtures_provided"))


class P0PipelineE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_passes_inferred_fixtures_to_sandbox(self):
        captured: dict = {}

        def _spy_run_in_sandbox(source_code, language, files=None, **kwargs):
            captured["files"] = files
            return run_in_sandbox(source_code, language, files=files, **kwargs)

        with (
            patch("backend.sandbox.executor.run_in_sandbox", side_effect=_spy_run_in_sandbox),
            patch(
                "backend.agents.task_relevance.assess_task_relevance_llm",
                new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []}),
            ),
            patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
        ):
            result = await main.run_analysis_pipeline(
                "submission.py",
                _UYGUN_CSV_CODE,
                assignment_brief=_CSV_BRIEF,
                faculty_rubric_criteria=None,
                report_language="tr",
            )

        files = captured.get("files") or []
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "scores.csv")
        self.assertGreaterEqual(result["totalScore"], 60)

    async def test_pipeline_does_not_cap_score_when_sandbox_succeeds_with_fixtures(self):
        with (
            patch(
                "backend.agents.task_relevance.assess_task_relevance_llm",
                new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []}),
            ),
            patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
        ):
            result = await main.run_analysis_pipeline(
                "submission.py",
                _UYGUN_CSV_CODE,
                assignment_brief=_CSV_BRIEF,
            )

        self.assertGreaterEqual(result["totalScore"], 60)
        agents = {a["id"]: a for a in result.get("agents", []) if isinstance(a, dict)}
        test_agent = agents.get("test_agent", {})
        self.assertNotIn("FileNotFound", str(test_agent.get("summary", "")))

    async def test_pipeline_passes_explicit_test_cases_to_sandbox_and_test_agent(self):
        captured: dict = {}
        test_cases = [
            {"name": "normal_case", "stdin": "6\n", "expected_stdout": "36\n"},
            {"name": "zero_case", "stdin": "0\n", "expected_stdout": "0\n"},
        ]

        def _spy_run_in_sandbox(source_code, language, files=None, test_cases=None, **kwargs):
            captured["sandbox_test_cases"] = test_cases
            return {
                "compilation_success": True,
                "exit_code": 0,
                "stdout": "36\n",
                "stderr": "",
                "execution_time_ms": 5,
                "peak_memory_mb": 1.0,
                "test_results": [
                    {
                        "name": "normal_case",
                        "stdin": "6\n",
                        "expected_stdout": "36\n",
                        "actual_stdout": "36\n",
                        "passed": True,
                    },
                    {
                        "name": "zero_case",
                        "stdin": "0\n",
                        "expected_stdout": "0\n",
                        "actual_stdout": "0\n",
                        "passed": True,
                    },
                ],
            }

        async def _spy_test_agent(self, payload):
            captured["test_agent_expected_output"] = payload.get("expected_output")
            captured["test_agent_sandbox_results"] = payload["sandbox_result"].get("test_results")
            return _good_agent_payload() | {
                "passed_tests": 2,
                "failed_tests": 0,
                "total_tests": 2,
                "test_results": payload["sandbox_result"].get("test_results", []),
            }

        with (
            patch("backend.sandbox.executor.run_in_sandbox", side_effect=_spy_run_in_sandbox),
            patch(
                "backend.agents.task_relevance.assess_task_relevance_llm",
                new=AsyncMock(return_value={"skipped": True, "relevance_factor": 1.0}),
            ),
            patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.TestAgent, "analyze", new=_spy_test_agent),
            patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
        ):
            result = await main.run_analysis_pipeline(
                "submission.py",
                "print(int(input()) ** 2)\n",
                assignment_brief="Girilen sayinin karesini yazdiran Python programi.",
                test_cases=test_cases,
            )

        self.assertEqual(captured["sandbox_test_cases"], test_cases)
        self.assertEqual(captured["test_agent_expected_output"], test_cases)
        self.assertEqual(captured["test_agent_sandbox_results"][0]["actual_stdout"], "36\n")
        testing = next(agent for agent in result["agents"] if agent["id"] == "testing")
        self.assertIn("2 test gecti", testing["summary"])

    async def test_pipeline_reports_algorithm_and_authorship_without_authorship_score_penalty(self):
        with (
            patch("backend.sandbox.executor.run_in_sandbox", return_value={"compilation_success": True, "exit_code": 0, "stdout": "", "stderr": ""}),
            patch(
                "backend.agents.task_relevance.assess_task_relevance_llm",
                new=AsyncMock(return_value={"skipped": True, "relevance_factor": 1.0}),
            ),
            patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.AlgorithmAgent, "analyze", new=AsyncMock(return_value={
                "detected_algorithms": ["nested_loop"],
                "data_structures": ["list"],
                "time_complexity": "O(n^2)",
                "space_complexity": "O(1)",
                "expected_complexity": "O(n)",
                "complexity_gap": "worse_than_expected",
                "issues": [{"type": "complexity_gap", "description": "Beklenenden karmasik", "severity": "high"}],
                "score": 55,
            })),
            patch.object(main.AIAuthorshipAgent, "analyze", new=AsyncMock(return_value={
                "risk_level": "high",
                "confidence": 0.9,
                "signals": ["AI kalibi"],
                "counter_signals": [],
                "recommendation": "Notu otomatik dusurme.",
            })),
            patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
        ):
            result = await main.run_analysis_pipeline(
                "submission.py",
                "print('ok')\n",
                assignment_brief="Listeyi O(n) karmasiklikla isleyin.",
            )

        self.assertEqual(result["totalScore"], 88)
        agent_ids = {agent["id"] for agent in result["agents"]}
        self.assertIn("algorithm", agent_ids)
        self.assertIn("ai_authorship", agent_ids)


if __name__ == "__main__":
    unittest.main()
