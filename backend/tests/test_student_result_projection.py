"""Unit tests for student-safe analysis result projection (Phase 2A Task 7)."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from backend.reporting.student_projection import (
    GENERIC_REDACTED_TEXT,
    project_student_result,
)

# Distinct greppable sentinels for hidden-test private fields.
SENTINEL_HIDDEN_NAME = "SENTINEL_HIDDEN_NAME_7f3a"
SENTINEL_HIDDEN_INPUT = "SENTINEL_HIDDEN_INPUT_7f3a"
SENTINEL_HIDDEN_EXPECTED = "SENTINEL_HIDDEN_EXPECTED_7f3a"
SENTINEL_HIDDEN_ACTUAL = "SENTINEL_HIDDEN_ACTUAL_7f3a"
SENTINEL_HIDDEN_DIFF = "SENTINEL_HIDDEN_DIFF_7f3a"
SENTINEL_AGENT_DIAGNOSTICS = "SENTINEL_AGENT_DIAGNOSTICS_7f3a"
SENTINEL_REJECTED_CLAIMS = "SENTINEL_REJECTED_CLAIMS_7f3a"
SENTINEL_UNKNOWN_TOP = "SENTINEL_UNKNOWN_TOP_7f3a"
SENTINEL_NESTED = "NESTED_SENTINEL_7f3a"

PUBLIC_NAME = "PUBLIC_KEEP_NAME_7f3a"
PUBLIC_INPUT = "PUBLIC_KEEP_INPUT_7f3a"
PUBLIC_EXPECTED = "PUBLIC_KEEP_EXPECTED_7f3a"
PUBLIC_ACTUAL = "PUBLIC_KEEP_ACTUAL_7f3a"
PUBLIC_DIFF = "PUBLIC_KEEP_DIFF_7f3a"

HIDDEN_SENTINELS = (
    SENTINEL_HIDDEN_NAME,
    SENTINEL_HIDDEN_INPUT,
    SENTINEL_HIDDEN_EXPECTED,
    SENTINEL_HIDDEN_ACTUAL,
    SENTINEL_HIDDEN_DIFF,
    SENTINEL_AGENT_DIAGNOSTICS,
    SENTINEL_REJECTED_CLAIMS,
)


def private_result_with_hidden_sentinels() -> dict[str, Any]:
    """Build a realistic private result with greppable hidden-test sentinels."""
    leaky_message = (
        f"Test {SENTINEL_HIDDEN_NAME} basarisiz | Gizli test | "
        f"Girdi: {SENTINEL_HIDDEN_INPUT} | "
        f"Beklenen: {SENTINEL_HIDDEN_EXPECTED} | "
        f"Gercek: {SENTINEL_HIDDEN_ACTUAL}"
    )
    return {
        "totalScore": 42,
        "maxScore": 100,
        "rubric": {"criteria": [{"name": "correctness", "score": 42}]},
        "agents": [
            {
                "id": "testing",
                "name": "Test Ajani",
                "summary": "Derleme basarili, 1 test gecti, 1 basarisiz",
                "score": 50,
                "maxScore": 100,
                "findings": [
                    {
                        "severity": "error",
                        "message": leaky_message,
                        "line": None,
                        "agent": "Test Ajani",
                        "code": None,
                    },
                    {
                        "severity": "info",
                        "message": f"Public test {PUBLIC_NAME} gecti",
                        "line": None,
                        "agent": "Test Ajani",
                        "code": None,
                    },
                ],
                "testResults": [
                    {
                        "name": PUBLIC_NAME,
                        "input": PUBLIC_INPUT,
                        "expected": PUBLIC_EXPECTED,
                        "actual": PUBLIC_ACTUAL,
                        "passed": True,
                        "visibility": "public",
                        "matchPct": 100.0,
                        "diffDetail": PUBLIC_DIFF,
                    },
                    {
                        "name": SENTINEL_HIDDEN_NAME,
                        "input": SENTINEL_HIDDEN_INPUT,
                        "expected": SENTINEL_HIDDEN_EXPECTED,
                        "actual": SENTINEL_HIDDEN_ACTUAL,
                        "passed": False,
                        "visibility": "hidden",
                        "matchPct": 0.0,
                        "diffDetail": SENTINEL_HIDDEN_DIFF,
                        "stderr": "secret stderr",
                        "stdin": SENTINEL_HIDDEN_INPUT,
                    },
                ],
                "llm_status": "ok",
                "confidence": 0.9,
            },
            {
                "id": "quality",
                "name": "Kod Kalitesi Ajani",
                "summary": "Skor: 70/100",
                "score": 70,
                "maxScore": 100,
                "findings": [
                    {
                        "severity": "warning",
                        "message": "Unused variable on line 5",
                        "line": 5,
                        "agent": "Kod Kalitesi Ajani",
                        "code": "W001",
                    },
                ],
            },
        ],
        "evidence": [{"line": 1, "message": "sample evidence"}],
        "rejectedClaims": [{"claim": SENTINEL_REJECTED_CLAIMS}],
        "fileName": "solution.py",
        "executionTimeMs": 1200,
        "memoryUsageMb": 12.5,
        "peakMemoryMb": 18.0,
        "analysisEngine": "agentgrade-v1",
        "summary": "Orta duzey bir cozum.",
        "strengths": ["Temiz kod"],
        "weaknesses": ["Eksik edge case"],
        "recommendations": ["Daha fazla test yazin"],
        "resourceRecommendations": [],
        "relevanceScoreWarning": None,
        "taskAlignment": {"factor": 1.0},
        "reportStatus": "ready",
        "agentDiagnostics": {
            "agents": [{"id": "testing", "score": 50}],
            "nested": SENTINEL_AGENT_DIAGNOSTICS,
        },
        "privateDebugField": SENTINEL_UNKNOWN_TOP,
    }


def _testing_agent(projected: dict[str, Any]) -> dict[str, Any]:
    for agent in projected.get("agents", []):
        if agent.get("id") == "testing":
            return agent
    raise AssertionError("testing agent not found in projection")


class StudentResultProjectionTests(unittest.TestCase):
    def test_student_projection_contains_no_hidden_sentinel_anywhere(self) -> None:
        private = private_result_with_hidden_sentinels()
        projected = project_student_result(private)
        serialized = json.dumps(projected, ensure_ascii=False)
        for sentinel in HIDDEN_SENTINELS:
            self.assertNotIn(
                sentinel,
                serialized,
                msg=f"hidden sentinel leaked into projection: {sentinel}",
            )

    def test_hidden_case_is_minimal_and_anonymous(self) -> None:
        private = private_result_with_hidden_sentinels()
        projected = project_student_result(private)
        testing = _testing_agent(projected)
        hidden_cases = [
            case for case in testing["testResults"] if case.get("visibility") == "hidden"
        ]
        self.assertEqual(len(hidden_cases), 1)
        hidden = hidden_cases[0]
        self.assertEqual(set(hidden.keys()), {"name", "visibility", "status", "passed"})
        self.assertEqual(hidden["name"], "Hidden test #1")
        self.assertEqual(hidden["visibility"], "hidden")
        self.assertEqual(hidden["passed"], False)
        self.assertIn(hidden["status"], {"failed", "error"})

    def test_public_test_case_fields_are_preserved(self) -> None:
        private = private_result_with_hidden_sentinels()
        projected = project_student_result(private)
        testing = _testing_agent(projected)
        public_cases = [
            case for case in testing["testResults"] if case.get("visibility") != "hidden"
        ]
        self.assertEqual(len(public_cases), 1)
        public = public_cases[0]
        self.assertEqual(public["name"], PUBLIC_NAME)
        self.assertEqual(public["input"], PUBLIC_INPUT)
        self.assertEqual(public["expected"], PUBLIC_EXPECTED)
        self.assertEqual(public["actual"], PUBLIC_ACTUAL)
        self.assertEqual(public["passed"], True)
        self.assertEqual(public["visibility"], "public")
        self.assertEqual(public["matchPct"], 100.0)
        self.assertEqual(public["diffDetail"], PUBLIC_DIFF)

    def test_projection_does_not_mutate_private_result(self) -> None:
        private = private_result_with_hidden_sentinels()
        before = copy.deepcopy(private)
        project_student_result(private)
        self.assertEqual(private, before)

    def test_agent_diagnostics_and_rejected_claims_are_absent(self) -> None:
        private = private_result_with_hidden_sentinels()
        projected = project_student_result(private)
        self.assertNotIn("agentDiagnostics", projected)
        self.assertNotIn("rejectedClaims", projected)

    def test_unknown_top_level_keys_are_dropped(self) -> None:
        private = private_result_with_hidden_sentinels()
        projected = project_student_result(private)
        self.assertNotIn("privateDebugField", projected)
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(SENTINEL_UNKNOWN_TOP, serialized)

    def test_hidden_finding_message_is_replaced_with_generic_text(self) -> None:
        private = private_result_with_hidden_sentinels()
        projected = project_student_result(private)
        testing = _testing_agent(projected)
        for finding in testing.get("findings", []):
            message = finding.get("message", "")
            for sentinel in (
                SENTINEL_HIDDEN_NAME,
                SENTINEL_HIDDEN_INPUT,
                SENTINEL_HIDDEN_EXPECTED,
                SENTINEL_HIDDEN_ACTUAL,
                SENTINEL_HIDDEN_DIFF,
            ):
                self.assertNotIn(sentinel, message)
        generic_messages = [
            f["message"]
            for f in testing.get("findings", [])
            if f.get("message") == "Hidden test basarisiz."
        ]
        self.assertGreaterEqual(len(generic_messages), 1)

    def test_multiple_hidden_cases_get_sequential_anonymous_numbering(self) -> None:
        private = private_result_with_hidden_sentinels()
        testing_agent = private["agents"][0]
        testing_agent["testResults"] = [
            {
                "name": PUBLIC_NAME,
                "input": PUBLIC_INPUT,
                "expected": PUBLIC_EXPECTED,
                "actual": PUBLIC_ACTUAL,
                "passed": True,
                "visibility": "public",
                "matchPct": 100.0,
                "diffDetail": "",
            },
            {
                "name": "hidden-a",
                "input": "secret-a-in",
                "expected": "secret-a-exp",
                "actual": "secret-a-act",
                "passed": False,
                "visibility": "hidden",
                "matchPct": 0.0,
                "diffDetail": "mismatch",
            },
            {
                "name": "hidden-b",
                "input": "secret-b-in",
                "expected": "secret-b-exp",
                "actual": "secret-b-act",
                "passed": True,
                "visibility": "hidden",
                "matchPct": 100.0,
                "diffDetail": "",
            },
            {
                "name": "hidden-c",
                "input": "secret-c-in",
                "expected": "secret-c-exp",
                "actual": "secret-c-act",
                "passed": False,
                "visibility": "hidden",
                "matchPct": 0.0,
                "diffDetail": "Traceback (most recent call last): boom",
            },
        ]
        projected = project_student_result(private)
        testing = _testing_agent(projected)
        hidden_cases = [
            case for case in testing["testResults"] if case.get("visibility") == "hidden"
        ]
        self.assertEqual(len(hidden_cases), 3)
        self.assertEqual(hidden_cases[0]["name"], "Hidden test #1")
        self.assertEqual(hidden_cases[1]["name"], "Hidden test #2")
        self.assertEqual(hidden_cases[2]["name"], "Hidden test #3")
        self.assertEqual(hidden_cases[0]["passed"], False)
        self.assertEqual(hidden_cases[1]["passed"], True)
        self.assertEqual(hidden_cases[2]["passed"], False)
        serialized = json.dumps(testing["testResults"], ensure_ascii=False)
        for secret in (
            "hidden-a",
            "secret-a-in",
            "hidden-b",
            "secret-c-in",
            "Traceback",
        ):
            self.assertNotIn(secret, serialized)

    def test_progress_shaped_partial_result_also_redacts_hidden_data(self) -> None:
        private = {
            "totalScore": 10,
            "maxScore": 100,
            "rubric": {},
            "agents": [
                {
                    "id": "testing",
                    "name": "Test Ajani",
                    "summary": "Hazirlaniyor",
                    "score": 0,
                    "maxScore": 100,
                    "findings": [
                        {
                            "severity": "error",
                            "message": f"Leak {SENTINEL_HIDDEN_INPUT}",
                            "line": None,
                            "agent": "Test Ajani",
                            "code": None,
                        },
                    ],
                    "testResults": [
                        {
                            "name": SENTINEL_HIDDEN_NAME,
                            "input": SENTINEL_HIDDEN_INPUT,
                            "expected": SENTINEL_HIDDEN_EXPECTED,
                            "actual": SENTINEL_HIDDEN_ACTUAL,
                            "passed": False,
                            "visibility": "hidden",
                            "matchPct": 0.0,
                            "diffDetail": SENTINEL_HIDDEN_DIFF,
                        },
                    ],
                },
            ],
            "evidence": [],
            "fileName": "partial.py",
            "executionTimeMs": 0,
            "memoryUsageMb": 0.0,
            "peakMemoryMb": 0.0,
            "analysisEngine": "agentgrade-v1",
            "summary": "",
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "relevanceScoreWarning": None,
            "taskAlignment": {},
            "reportStatus": "preparing",
            "agentDiagnostics": {"sentinel": SENTINEL_AGENT_DIAGNOSTICS},
            "rejectedClaims": [SENTINEL_REJECTED_CLAIMS],
        }
        projected = project_student_result(private)
        serialized = json.dumps(projected, ensure_ascii=False)
        for sentinel in HIDDEN_SENTINELS:
            self.assertNotIn(sentinel, serialized)
        self.assertNotIn("resourceRecommendations", projected)
        self.assertEqual(projected["reportStatus"], "preparing")

    def _private_with_hidden_fragments(self) -> dict[str, Any]:
        """Private result whose hidden test cases define greppable fragments."""
        return private_result_with_hidden_sentinels()

    def test_top_level_summary_leaking_hidden_data_is_redacted(self) -> None:
        private = self._private_with_hidden_fragments()
        private["summary"] = f"Model summary includes {SENTINEL_HIDDEN_INPUT}"
        projected = project_student_result(private)
        self.assertNotIn(SENTINEL_HIDDEN_INPUT, projected["summary"])
        self.assertEqual(projected["summary"], GENERIC_REDACTED_TEXT)

    def test_top_level_strengths_weaknesses_recommendations_drop_leaking_items(
        self,
    ) -> None:
        private = self._private_with_hidden_fragments()
        clean = "Clean item preserved"
        private["strengths"] = [f"Leaks {SENTINEL_HIDDEN_INPUT}", clean]
        private["weaknesses"] = [f"Leaks {SENTINEL_HIDDEN_EXPECTED}", clean]
        private["recommendations"] = [f"Leaks {SENTINEL_HIDDEN_ACTUAL}", clean]
        projected = project_student_result(private)
        self.assertEqual(projected["strengths"], [clean])
        self.assertEqual(projected["weaknesses"], [clean])
        self.assertEqual(projected["recommendations"], [clean])

    def test_top_level_evidence_entries_leaking_hidden_data_are_dropped(self) -> None:
        private = self._private_with_hidden_fragments()
        clean_evidence = {"message": "clean evidence", "line": 1, "agent": "quality"}
        leaking_evidence = {
            "message": f"evidence includes {SENTINEL_HIDDEN_INPUT}",
            "line": 2,
            "agent": "testing",
        }
        private["evidence"] = [leaking_evidence, clean_evidence]
        projected = project_student_result(private)
        self.assertEqual(projected["evidence"], [clean_evidence])

    def test_agent_summary_leaking_hidden_data_is_redacted_for_every_agent(
        self,
    ) -> None:
        private = self._private_with_hidden_fragments()
        for agent in private["agents"]:
            agent["summary"] = f"{agent['id']} summary includes {SENTINEL_HIDDEN_INPUT}"
        projected = project_student_result(private)
        for agent in projected["agents"]:
            self.assertNotIn(SENTINEL_HIDDEN_INPUT, agent["summary"])
            self.assertEqual(agent["summary"], GENERIC_REDACTED_TEXT)

    def test_non_testing_agent_finding_leaking_hidden_data_is_dropped(self) -> None:
        private = self._private_with_hidden_fragments()
        quality = next(a for a in private["agents"] if a["id"] == "quality")
        quality["findings"] = [
            {
                "severity": "error",
                "message": f"quality finding includes {SENTINEL_HIDDEN_INPUT}",
                "line": 1,
                "agent": "Kod Kalitesi Ajani",
                "code": "E001",
            },
            {
                "severity": "warning",
                "message": "Unused variable on line 5",
                "line": 5,
                "agent": "Kod Kalitesi Ajani",
                "code": "W001",
            },
        ]
        projected = project_student_result(private)
        quality_projected = next(a for a in projected["agents"] if a["id"] == "quality")
        self.assertEqual(len(quality_projected["findings"]), 1)
        self.assertEqual(quality_projected["findings"][0]["message"], "Unused variable on line 5")

    def test_non_leaking_top_level_and_agent_text_is_preserved_unchanged(self) -> None:
        private = self._private_with_hidden_fragments()
        projected = project_student_result(private)
        self.assertEqual(projected["summary"], "Orta duzey bir cozum.")
        self.assertEqual(projected["strengths"], ["Temiz kod"])
        self.assertEqual(projected["weaknesses"], ["Eksik edge case"])
        self.assertEqual(projected["recommendations"], ["Daha fazla test yazin"])
        self.assertEqual(projected["evidence"], [{"line": 1, "message": "sample evidence"}])
        testing = _testing_agent(projected)
        self.assertEqual(testing["summary"], "Derleme basarili, 1 test gecti, 1 basarisiz")
        quality = next(a for a in projected["agents"] if a["id"] == "quality")
        self.assertEqual(quality["summary"], "Skor: 70/100")

    def test_evidence_entry_with_leaking_non_message_field_is_dropped(self) -> None:
        private = self._private_with_hidden_fragments()
        clean_evidence = {"message": "clean", "line": 1}
        leaking_evidence = {
            "message": "clean",
            "details": f"leak: {SENTINEL_HIDDEN_INPUT}",
        }
        private["evidence"] = [leaking_evidence, clean_evidence]
        projected = project_student_result(private)
        self.assertEqual(projected["evidence"], [clean_evidence])
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(SENTINEL_HIDDEN_INPUT, serialized)

    def test_resource_recommendations_with_leaking_field_are_sanitized(self) -> None:
        private = self._private_with_hidden_fragments()
        clean_rec = {"title": "clean", "url": "https://example.com"}
        leaking_rec = {
            "title": "clean",
            "private_note": f"leak: {SENTINEL_HIDDEN_INPUT}",
        }
        private["resourceRecommendations"] = [leaking_rec, clean_rec]
        projected = project_student_result(private)
        self.assertEqual(projected["resourceRecommendations"], [clean_rec])
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(SENTINEL_HIDDEN_INPUT, serialized)

    def test_rubric_nested_leaking_field_is_redacted(self) -> None:
        private = self._private_with_hidden_fragments()
        criteria = [{"name": "correctness", "score": 42}]
        private["rubric"] = {
            "criteria": criteria,
            "debug": f"leak: {SENTINEL_HIDDEN_INPUT}",
        }
        projected = project_student_result(private)
        self.assertEqual(projected["rubric"]["criteria"], criteria)
        self.assertEqual(projected["rubric"]["debug"], GENERIC_REDACTED_TEXT)
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(SENTINEL_HIDDEN_INPUT, serialized)

    def test_task_alignment_nested_leaking_field_is_redacted(self) -> None:
        private = self._private_with_hidden_fragments()
        private["taskAlignment"] = {
            "factor": 1.0,
            "reason": f"leak: {SENTINEL_HIDDEN_INPUT}",
        }
        projected = project_student_result(private)
        self.assertEqual(projected["taskAlignment"]["factor"], 1.0)
        self.assertEqual(projected["taskAlignment"]["reason"], GENERIC_REDACTED_TEXT)
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(SENTINEL_HIDDEN_INPUT, serialized)

    def test_non_testing_finding_leaking_code_field_is_dropped(self) -> None:
        private = self._private_with_hidden_fragments()
        quality = next(a for a in private["agents"] if a["id"] == "quality")
        quality["findings"] = [
            {
                "severity": "error",
                "message": "clean",
                "line": 1,
                "agent": "Kod Kalitesi Ajani",
                "code": f"leak: {SENTINEL_HIDDEN_INPUT}",
            },
            {
                "severity": "warning",
                "message": "Unused variable on line 5",
                "line": 5,
                "agent": "Kod Kalitesi Ajani",
                "code": "W001",
            },
        ]
        projected = project_student_result(private)
        quality_projected = next(a for a in projected["agents"] if a["id"] == "quality")
        self.assertEqual(len(quality_projected["findings"]), 1)
        self.assertEqual(quality_projected["findings"][0]["code"], "W001")
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(SENTINEL_HIDDEN_INPUT, serialized)

    def test_testing_finding_leaking_non_message_field_is_dropped(self) -> None:
        private = self._private_with_hidden_fragments()
        testing = private["agents"][0]
        testing["findings"] = [
            {
                "severity": "error",
                "message": "clean",
                "line": None,
                "agent": "Test Ajani",
                "code": f"leak: {SENTINEL_HIDDEN_INPUT}",
            },
            {
                "severity": "info",
                "message": f"Public test {PUBLIC_NAME} gecti",
                "line": None,
                "agent": "Test Ajani",
                "code": None,
            },
        ]
        projected = project_student_result(private)
        testing_projected = _testing_agent(projected)
        messages = [f["message"] for f in testing_projected["findings"]]
        self.assertIn(f"Public test {PUBLIC_NAME} gecti", messages)
        for finding in testing_projected["findings"]:
            code = finding.get("code")
            if code is not None:
                self.assertNotIn(SENTINEL_HIDDEN_INPUT, str(code))
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(SENTINEL_HIDDEN_INPUT, serialized)

    def test_adversarial_nested_leak_reproduction_is_blocked(self) -> None:
        """End-to-end regression for nested sub-field leak vectors."""
        secret = SENTINEL_NESTED
        private = self._private_with_hidden_fragments()
        private["evidence"] = [
            {"message": "clean", "details": f"leak: {secret}"},
        ]
        private["resourceRecommendations"] = [
            {"title": "clean", "private_note": f"leak: {secret}"},
        ]
        private["rubric"] = {
            "criteria": [{"name": "correctness", "score": 42}],
            "debug": f"leak: {secret}",
        }
        private["taskAlignment"] = {
            "factor": 1.0,
            "reason": f"leak: {secret}",
        }
        quality = next(a for a in private["agents"] if a["id"] == "quality")
        quality["findings"] = [
            {
                "severity": "error",
                "message": "clean",
                "code": f"leak: {secret}",
            },
        ]
        private["agents"][0]["testResults"][1]["input"] = secret
        out = project_student_result(private)
        serialized = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(secret, serialized)

    def test_adversarial_hidden_fragment_leak_reproduction_is_blocked(self) -> None:
        """End-to-end regression for the reported vulnerability."""
        secret = SENTINEL_HIDDEN_INPUT
        private = {
            "totalScore": 42,
            "maxScore": 100,
            "rubric": {},
            "summary": f"Model summary includes {secret}",
            "evidence": [{"message": f"evidence includes {secret}"}],
            "agents": [
                {
                    "id": "testing",
                    "name": "Test Ajani",
                    "summary": f"testing summary includes {secret}",
                    "score": 50,
                    "maxScore": 100,
                    "testResults": [
                        {
                            "name": SENTINEL_HIDDEN_NAME,
                            "input": secret,
                            "expected": SENTINEL_HIDDEN_EXPECTED,
                            "actual": SENTINEL_HIDDEN_ACTUAL,
                            "passed": False,
                            "visibility": "hidden",
                        },
                    ],
                    "findings": [],
                },
                {
                    "id": "quality",
                    "name": "Kod Kalitesi Ajani",
                    "summary": f"quality summary includes {secret}",
                    "score": 70,
                    "maxScore": 100,
                    "findings": [
                        {
                            "severity": "error",
                            "message": f"quality finding includes {secret}",
                        },
                    ],
                },
            ],
            "fileName": "solution.py",
            "executionTimeMs": 100,
            "memoryUsageMb": 1.0,
            "peakMemoryMb": 1.0,
            "analysisEngine": "agentgrade-v1",
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "taskAlignment": {},
            "reportStatus": "ready",
        }
        out = project_student_result(private)
        serialized = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(secret, serialized)

    def test_dict_key_leak_in_rubric_is_redacted(self) -> None:
        private = self._private_with_hidden_fragments()
        secret = SENTINEL_HIDDEN_INPUT
        private["rubric"] = {
            "criteria": [{"name": "correctness", "score": 42}],
            secret: "leaked via rubric dict key",
        }
        projected = project_student_result(private)
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertIn("redacted_key", serialized)

    def test_dict_key_leak_in_resource_recommendations_is_redacted(self) -> None:
        private = self._private_with_hidden_fragments()
        secret = SENTINEL_HIDDEN_INPUT
        clean_rec = {"title": "clean", "url": "https://example.com"}
        leaking_rec = {secret: "leaked via rec dict key", "title": "bad rec"}
        private["resourceRecommendations"] = [leaking_rec, clean_rec]
        projected = project_student_result(private)
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertEqual(projected["resourceRecommendations"], [clean_rec])

    def test_agent_name_leaking_hidden_data_is_redacted(self) -> None:
        private = self._private_with_hidden_fragments()
        secret = SENTINEL_HIDDEN_INPUT
        private["agents"][0]["name"] = f"Test Agent {secret}"
        projected = project_student_result(private)
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        testing = _testing_agent(projected)
        self.assertEqual(testing["name"], GENERIC_REDACTED_TEXT)

    def test_agent_id_leaking_hidden_data_is_redacted(self) -> None:
        private = self._private_with_hidden_fragments()
        secret = SENTINEL_HIDDEN_INPUT
        private["agents"][1]["id"] = secret
        projected = project_student_result(private)
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        quality = next(a for a in projected["agents"] if a.get("score") == 70)
        self.assertEqual(quality["id"], GENERIC_REDACTED_TEXT)

    def test_adversarial_dict_key_and_agent_metadata_leak_reproduction_is_blocked(
        self,
    ) -> None:
        """Exact combined bug-report reproduction: dict keys + agent name."""
        secret = SENTINEL_HIDDEN_INPUT
        private = self._private_with_hidden_fragments()
        private["rubric"] = {
            "criteria": [{"name": "correctness", "score": 42}],
            secret: "leaked via rubric key",
        }
        private["resourceRecommendations"] = [
            {secret: "leaked via rec key", "title": "bad rec"},
        ]
        private["agents"][0]["name"] = f"Test Agent {secret}"
        out = project_student_result(private)
        serialized = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(secret, serialized)

    def test_comprehensive_invariant_no_sentinel_survives_in_serialized_output_regardless_of_location(
        self,
    ) -> None:
        """Kitchen-sink fail-closed invariant: sentinel absent from entire output."""
        secret = SENTINEL_HIDDEN_INPUT
        private = self._private_with_hidden_fragments()
        private["rubric"] = {
            "criteria": [
                {
                    "name": "correctness",
                    "score": 42,
                    "nested": {"deep": secret},
                },
            ],
            secret: "rubric key leak",
        }
        private["taskAlignment"] = {
            secret: "task alignment key leak",
            "factor": 1.0,
        }
        private["resourceRecommendations"] = [
            {secret: "rec key leak", "title": "bad rec"},
            {"title": "clean rec", "url": "https://example.com"},
        ]
        private["evidence"] = [
            {secret: "evidence key leak", "message": "clean"},
            {"message": "clean evidence", "line": 1},
        ]
        private["agents"][0]["name"] = f"testing name {secret}"
        private["agents"][1]["id"] = secret
        private["agents"][1]["name"] = f"quality name {secret}"
        quality = private["agents"][1]
        quality["findings"] = [
            {
                "severity": "error",
                "message": "clean message",
                "agent": f"agent field {secret}",
                "code": "E001",
            },
        ]
        out = project_student_result(private)
        serialized = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
