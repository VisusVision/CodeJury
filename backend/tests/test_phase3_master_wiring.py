"""Phase 3: AlgorithmAgent score must not affect MasterEvaluator rubric/final."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from backend.agents.master_evaluator import MasterEvaluatorAgent


def _shared_master_input(*, algorithm_score: int) -> dict[str, Any]:
    return {
        "source_code": (
            "def binary_search(xs, target):\n"
            "    lo, hi = 0, len(xs) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if xs[mid] == target:\n"
            "            return mid\n"
            "        if xs[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n"
        ),
        "language": "python",
        "assignment_description": "Implement binary search. Required complexity O(log n).",
        "rubric": {
            "functionality": 35,
            "algorithmic_efficiency": 25,
            "code_standards": 25,
            "security": 15,
        },
        "sandbox_result": {"compilation_success": True, "exit_code": 0, "stderr": ""},
        "task_alignment": {"factor": 1.0, "reasons": [], "programmatic_factor": 1.0},
        "evidence": {
            "validated_claims": [],
            "total_claims_received": 0,
            "total_claims_validated": 0,
        },
        "code_quality": {"score": 80, "issues": []},
        "test_agent": {"score": 82, "runs_successfully": True},
        "seniority": {"score": 75},
        "guideline": {"score": 70, "style_violations": []},
        "security": {
            "score": 95,
            "risk_level": "safe",
            "critical_count": 0,
            "high_count": 0,
        },
        "algorithm": {
            "score": algorithm_score,
            "time_complexity": "O(log n)",
            "complexity_gap": "matches_expected",
            "guardrail_flags": [],
        },
    }


class Phase3MasterWiringTests(unittest.TestCase):
    def test_programmatic_analysis_ignores_algorithm_agent_score(self):
        agent = MasterEvaluatorAgent()
        low = agent._programmatic_analysis(_shared_master_input(algorithm_score=5))
        high = agent._programmatic_analysis(_shared_master_input(algorithm_score=100))

        self.assertEqual(low["final_score"], high["final_score"])
        self.assertEqual(low["rubric_breakdown"], high["rubric_breakdown"])

    def test_algorithmic_efficiency_uses_code_quality_not_algorithm_agent(self):
        agent = MasterEvaluatorAgent()
        result = agent._programmatic_analysis(_shared_master_input(algorithm_score=5))
        efficiency = next(
            row for row in result["rubric_breakdown"] if row["criterion"] == "algorithmic_efficiency"
        )
        self.assertEqual(efficiency["score"], 80)


class Phase3MasterWiringAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_with_mocked_llm_ignores_algorithm_agent_score(self):
        agent = MasterEvaluatorAgent()
        llm_payload = {
            "final_score": 84,
            "rubric_breakdown": [
                {
                    "criterion": "functionality",
                    "label": "Functionality",
                    "weight": 35,
                    "score": 80,
                    "weighted_score": 28.0,
                    "justification": "ok",
                },
                {
                    "criterion": "algorithmic_efficiency",
                    "label": "Algorithmic efficiency",
                    "weight": 25,
                    "score": 78,
                    "weighted_score": 19.5,
                    "justification": "ok",
                },
                {
                    "criterion": "code_standards",
                    "label": "Code standards",
                    "weight": 25,
                    "score": 72,
                    "weighted_score": 18.0,
                    "justification": "ok",
                },
                {
                    "criterion": "security",
                    "label": "Security",
                    "weight": 15,
                    "score": 95,
                    "weighted_score": 14.25,
                    "justification": "ok",
                },
            ],
            "summary": "Solid submission.",
            "strengths": ["Runs"],
            "weaknesses": [],
            "recommendations": [],
        }
        with patch.object(agent, "_call_llm", new=AsyncMock(return_value=llm_payload)):
            low = await agent.analyze(_shared_master_input(algorithm_score=5))
            high = await agent.analyze(_shared_master_input(algorithm_score=100))

        self.assertEqual(low["final_score"], high["final_score"])
        self.assertEqual(low["rubric_breakdown"], high["rubric_breakdown"])


if __name__ == "__main__":
    unittest.main()
