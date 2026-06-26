"""Regression: faculty-mode runtime guard must not raise NameError."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.master_evaluator import MasterEvaluatorAgent


class MasterEvaluatorFacultyRuntimeGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_faculty_mode_apply_runtime_guard_does_not_crash(self):
        agent = MasterEvaluatorAgent()
        faculty = [
            {"criterion": "c0", "label": "Calisabilirlik", "weight": 50, "max_score": 50},
            {"criterion": "c1", "label": "Guvenlik", "weight": 50, "max_score": 50},
        ]
        llm_payload = {
            "final_score": 88,
            "rubric_breakdown": [
                {"criterion": "c0", "label": "Calisabilirlik", "weight": 50, "score": 44},
                {"criterion": "c1", "label": "Guvenlik", "weight": 50, "score": 44},
            ],
            "summary": "Iyi",
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
        }
        with patch.object(agent, "_call_llm", new=AsyncMock(return_value=llm_payload)):
            result = await agent.analyze(
                {
                    "source_code": 'path = Path("scores.csv")',
                    "language": "python",
                    "faculty_rubric_criteria": faculty,
                    "sandbox_result": {
                        "compilation_success": True,
                        "exit_code": 0,
                        "stderr": "",
                        "fixtures_provided": True,
                    },
                    "task_alignment": {"factor": 0.95, "reasons": []},
                    "evidence": {"validated_claims": [], "total_claims_received": 0, "total_claims_validated": 0},
                    "code_quality": {"score": 80, "issues": []},
                    "test_agent": {"score": 80, "runs_successfully": True},
                    "seniority": {"score": 75},
                    "guideline": {"score": 70, "style_violations": []},
                    "security": {"score": 95, "risk_level": "safe", "critical_count": 0, "high_count": 0},
                }
            )
        self.assertIn("final_score", result)

    def test_consensus_rescue_recovers_security_only_collapse(self):
        llm_result = {
            "final_score": 7.0,
            "rubric_breakdown": [
                {"label": "Sinif Tasarimi", "weight": 7, "score": 0, "weighted_score": 0.0, "justification": ""},
                {"label": "Guvenlik", "weight": 7, "score": 7, "weighted_score": 7.0, "justification": ""},
                {"label": "Kodlama Stili", "weight": 7, "score": 0, "weighted_score": 0.0, "justification": ""},
                {"label": "Mantiksal Dogruluk", "weight": 7, "score": 0, "weighted_score": 0.0, "justification": ""},
            ],
            "weaknesses": [],
            "recommendations": [],
        }
        programmatic = {
            "final_score": 86.0,
            "brief_alignment_factor": 0.12,
            "programmatic_alignment_factor": 1.0,
            "capability_match": 0.86,
            "sandbox_runs_ok": True,
            "brief_alignment_reasons": ["llm_task_relevance_off_topic"],
        }
        input_data = {
            "sandbox_result": {"compilation_success": True, "exit_code": 0},
        }
        MasterEvaluatorAgent._apply_brief_alignment_guard(llm_result, programmatic, faculty_mode=True)
        MasterEvaluatorAgent._apply_faculty_consensus_rescue(llm_result, programmatic, input_data)
        self.assertGreaterEqual(float(llm_result["final_score"]), 65.0)
        non_security = [
            int(row["score"])
            for row in llm_result["rubric_breakdown"]
            if "guven" not in str(row.get("label", "")).lower()
        ]
        self.assertGreater(sum(non_security), 0)

    def test_effective_alignment_boosts_relevant_submission(self):
        programmatic = {
            "brief_alignment_factor": 0.12,
            "programmatic_alignment_factor": 1.0,
            "capability_match": 0.86,
            "final_score": 86.0,
            "sandbox_runs_ok": True,
            "brief_alignment_reasons": ["llm_task_relevance_off_topic"],
        }
        effective = MasterEvaluatorAgent._effective_alignment_for_grading(programmatic)
        self.assertGreaterEqual(effective, 0.82)

    def test_faculty_mode_hard_off_topic_caps_below_thirty(self):
        llm_result = {
            "final_score": 90.0,
            "rubric_breakdown": [
                {"label": "Fonksiyonellik", "weight": 40, "score": 36, "weighted_score": 36.0, "justification": ""},
                {"label": "Kod Kalitesi", "weight": 30, "score": 27, "weighted_score": 27.0, "justification": ""},
                {"label": "Test ve Kenar Durumlari", "weight": 30, "score": 27, "weighted_score": 27.0, "justification": ""},
            ],
            "weaknesses": [],
        }
        programmatic = {
            "final_score": 70.0,
            "brief_alignment_factor": 0.40,
            "programmatic_alignment_factor": 0.40,
            "capability_match": 0.20,
            "sandbox_runs_ok": True,
            "brief_alignment_reasons": ["llm_task_relevance_off_topic"],
        }

        MasterEvaluatorAgent._apply_brief_alignment_guard(llm_result, programmatic, faculty_mode=True)

        self.assertLessEqual(float(llm_result["final_score"]), 28.0)
        self.assertTrue(any("alakas" in item.lower() or "gorev" in item.lower() for item in llm_result["weaknesses"]))


if __name__ == "__main__":
    unittest.main()
