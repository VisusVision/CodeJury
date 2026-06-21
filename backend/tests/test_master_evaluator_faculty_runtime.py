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


if __name__ == "__main__":
    unittest.main()
