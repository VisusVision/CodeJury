"""Phase 2B formal test report projection contracts (Task 12)."""

from __future__ import annotations

import json
import unittest
from typing import Any

from backend.reporting.student_projection import project_student_result

SENTINEL_FIXTURE_NAME = "SENTINEL_FIXTURE_NAME_2b12"
SENTINEL_FIXTURE_CONTENT = "SENTINEL_FIXTURE_CONTENT_2b12"
SENTINEL_SOURCE_PRIVATE = "SENTINEL_SOURCE_PRIVATE_2b12"
SENTINEL_ORACLE_MODEL = "SENTINEL_ORACLE_MODEL_2b12"
SENTINEL_ORACLE_PROVIDER = "SENTINEL_ORACLE_PROVIDER_2b12"
SENTINEL_CACHE_KEY = "SENTINEL_CACHE_KEY_2b12"
SENTINEL_SET_ID = "SENTINEL_SET_ID_2b12"
SENTINEL_STDERR = "SENTINEL_STDERR_2b12"
SENTINEL_NORMALIZED_DIFF = "SENTINEL_NORMALIZED_DIFF_2b12"
SENTINEL_RUNTIME_DETAIL = "SENTINEL_RUNTIME_DETAIL_2b12"
SENTINEL_ORIGINAL_NAME = "SENTINEL_ORIGINAL_NAME_2b12"
SENTINEL_CASE_ID = "SENTINEL_CASE_ID_2b12"

PHASE2B_HIDDEN_SENTINELS = (
    SENTINEL_FIXTURE_NAME,
    SENTINEL_FIXTURE_CONTENT,
    SENTINEL_SOURCE_PRIVATE,
    SENTINEL_ORACLE_MODEL,
    SENTINEL_ORACLE_PROVIDER,
    SENTINEL_CACHE_KEY,
    SENTINEL_SET_ID,
    SENTINEL_STDERR,
    SENTINEL_NORMALIZED_DIFF,
    SENTINEL_RUNTIME_DETAIL,
    SENTINEL_ORIGINAL_NAME,
    SENTINEL_CASE_ID,
)


def _testing_agent(projected: dict[str, Any]) -> dict[str, Any]:
    for agent in projected.get("agents", []):
        if agent.get("id") == "testing":
            return agent
    raise AssertionError("testing agent not found")


def private_result_with_public_case(**overrides: Any) -> dict[str, Any]:
    case = {
        "name": "square two",
        "stdin": "2\n",
        "expected_stdout": "4\n",
        "actual_stdout": "5\n",
        "passed": False,
        "visibility": "public",
        "status": "fail",
        "source": "auto_generated",
        "error_type": None,
    }
    case.update(overrides)
    return {
        "totalScore": 70,
        "maxScore": 100,
        "rubric": {},
        "agents": [
            {
                "id": "testing",
                "name": "Test Ajani",
                "summary": "1 test basarisiz",
                "score": 0,
                "maxScore": 100,
                "findings": [],
                "testResults": [case],
            }
        ],
        "fileName": "solution.py",
        "executionTimeMs": 100,
        "memoryUsageMb": 1.0,
        "peakMemoryMb": 1.0,
        "analysisEngine": "agentgrade-v1",
        "summary": "Formal test sonucu",
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "taskAlignment": {},
        "reportStatus": "ready",
        "testSource": "auto_generated",
        "testEvidenceStatus": "available",
        "formalPassed": 0,
        "formalTotal": 1,
        "testSetId": SENTINEL_SET_ID,
        "testSetHash": SENTINEL_CACHE_KEY,
        "cacheVersion": 7,
    }


def private_result_with_hidden_formal_case(**overrides: Any) -> dict[str, Any]:
    hidden_case = {
        "id": SENTINEL_CASE_ID,
        "name": SENTINEL_ORIGINAL_NAME,
        "stdin": "secret stdin\n",
        "expected_stdout": "secret expected\n",
        "actual_stdout": "secret actual\n",
        "actual_stderr": SENTINEL_STDERR,
        "passed": False,
        "visibility": "hidden",
        "status": "error",
        "source": SENTINEL_SOURCE_PRIVATE,
        "oracle": "llm_verified",
        "oracle_validation": {
            "status": "verified",
            "provider": SENTINEL_ORACLE_PROVIDER,
            "model": SENTINEL_ORACLE_MODEL,
            "schema_version": "v1",
            "verified_at": "2026-07-11T00:00:00Z",
        },
        "files": [
            {"name": SENTINEL_FIXTURE_NAME, "content": SENTINEL_FIXTURE_CONTENT},
        ],
        "error_type": "ZeroDivisionError",
        "error_message_tr": SENTINEL_RUNTIME_DETAIL,
        "errorDetail": SENTINEL_NORMALIZED_DIFF,
    }
    hidden_case.update(overrides)
    return {
        "totalScore": 50,
        "maxScore": 100,
        "rubric": {},
        "agents": [
            {
                "id": "testing",
                "name": "Test Ajani",
                "summary": "Hidden formal test",
                "score": 0,
                "maxScore": 100,
                "findings": [],
                "testResults": [hidden_case],
            }
        ],
        "fileName": "solution.py",
        "executionTimeMs": 100,
        "memoryUsageMb": 1.0,
        "peakMemoryMb": 1.0,
        "analysisEngine": "agentgrade-v1",
        "summary": "Hidden formal evidence",
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "taskAlignment": {},
        "reportStatus": "ready",
        "testSource": "auto_generated",
        "testEvidenceStatus": "available",
        "formalPassed": 0,
        "formalTotal": 1,
        "testSetId": SENTINEL_SET_ID,
        "testSetHash": SENTINEL_CACHE_KEY,
        "cacheVersion": 3,
    }


class Phase2BReportContractTests(unittest.TestCase):
    def test_public_case_projection_includes_formal_fields(self) -> None:
        private = private_result_with_public_case()
        projected = project_student_result(private)
        case = _testing_agent(projected)["testResults"][0]
        self.assertEqual(
            case,
            {
                "name": "square two",
                "input": "2\n",
                "expected": "4\n",
                "actual": "5\n",
                "visibility": "public",
                "status": "fail",
                "passed": False,
                "source": "auto_generated",
            },
        )

    def test_hidden_formal_case_strips_all_private_fields(self) -> None:
        private = private_result_with_hidden_formal_case()
        projected = project_student_result(private)
        serialized = json.dumps(projected, ensure_ascii=False)
        for sentinel in PHASE2B_HIDDEN_SENTINELS:
            self.assertNotIn(
                sentinel,
                serialized,
                msg=f"hidden sentinel leaked: {sentinel}",
            )
        hidden = _testing_agent(projected)["testResults"][0]
        self.assertEqual(
            hidden,
            {
                "name": "Hidden test #1",
                "visibility": "hidden",
                "status": "error",
                "passed": False,
            },
        )

    def test_student_receives_safe_top_level_provenance_only(self) -> None:
        private = private_result_with_public_case()
        projected = project_student_result(private)
        self.assertEqual(projected["testSource"], "auto_generated")
        self.assertEqual(projected["testEvidenceStatus"], "available")
        self.assertEqual(projected["formalPassed"], 0)
        self.assertEqual(projected["formalTotal"], 1)
        serialized = json.dumps(projected, ensure_ascii=False)
        for forbidden in (
            "testSetId",
            "testSetHash",
            "cacheVersion",
            SENTINEL_SET_ID,
            SENTINEL_CACHE_KEY,
            SENTINEL_ORACLE_MODEL,
            SENTINEL_ORACLE_PROVIDER,
        ):
            self.assertNotIn(forbidden, serialized)

    def test_hidden_test_summary_counts_projected_statuses(self) -> None:
        private = private_result_with_public_case()
        testing = private["agents"][0]
        testing["testResults"] = [
            private_result_with_public_case()["agents"][0]["testResults"][0],
            {
                "name": "hidden pass",
                "stdin": "a",
                "expected_stdout": "a",
                "actual_stdout": "a",
                "passed": True,
                "visibility": "hidden",
                "status": "pass",
                "source": "auto_generated",
            },
            {
                "name": "hidden fail",
                "stdin": "b",
                "expected_stdout": "b",
                "actual_stdout": "c",
                "passed": False,
                "visibility": "hidden",
                "status": "fail",
                "source": "auto_generated",
            },
            {
                "name": "hidden error",
                "stdin": "c",
                "expected_stdout": "c",
                "actual_stdout": "",
                "passed": False,
                "visibility": "hidden",
                "status": "error",
                "source": "auto_generated",
                "error_type": "ZeroDivisionError",
            },
            {
                "name": "hidden pass 2",
                "stdin": "d",
                "expected_stdout": "d",
                "actual_stdout": "d",
                "passed": True,
                "visibility": "hidden",
                "status": "pass",
                "source": "auto_generated",
            },
        ]
        projected = project_student_result(private)
        self.assertEqual(
            projected["hiddenTestSummary"],
            {"passed": 2, "failed": 1, "error": 1, "total": 4},
        )


if __name__ == "__main__":
    unittest.main()
