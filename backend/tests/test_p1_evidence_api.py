"""P1: Evidence API — file-level claims and rejectedClaims in analysis response."""

from __future__ import annotations

import unittest

from frontend.backend.main import (
    _build_line_evidence,
    _build_rejected_claims_response,
)


class FileLevelEvidenceTests(unittest.TestCase):
    def test_file_level_validated_claim_appears_with_scope_file(self):
        evidence = _build_line_evidence(
            {"issues": []},
            {"style_violations": []},
            {"threats": []},
            {
                "validated_claims": [
                    {
                        "feedback": "Guvenlik riski tespit edildi.",
                        "severity": "high",
                        "lines": [],
                        "node_type": "file",
                        "agent_source": "security",
                    }
                ]
            },
            "print('hello')\n",
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["line"], 0)
        self.assertEqual(evidence[0]["scope"], "file")
        self.assertEqual(evidence[0]["agent"], "Güvenlik")
        self.assertIn("Guvenlik riski", evidence[0]["message"])

    def test_line_level_claims_keep_positive_line_numbers(self):
        evidence = _build_line_evidence(
            {"issues": []},
            {"style_violations": []},
            {"threats": []},
            {
                "validated_claims": [
                    {
                        "feedback": "Toplama islemi.",
                        "severity": "medium",
                        "lines": [2],
                        "agent_source": "code_quality",
                    }
                ]
            },
            "def add(a, b):\n    return a + b\n",
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["line"], 2)
        self.assertNotIn("scope", evidence[0])


class RejectedClaimsResponseTests(unittest.TestCase):
    def test_structured_rejected_claims_include_agent_and_reason(self):
        rows = _build_rejected_claims_response(
            {
                "rejected_claims": [
                    {
                        "agent_source": "guideline",
                        "claim": "Docstring yok",
                        "reason": "Somut kanit yok",
                    }
                ]
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent"], "Standartlar")
        self.assertEqual(rows[0]["claim"], "Docstring yok")
        self.assertEqual(rows[0]["reason"], "Somut kanit yok")

    def test_empty_when_no_rejections(self):
        self.assertEqual(_build_rejected_claims_response({}), [])
        self.assertEqual(_build_rejected_claims_response({"rejected_claims": []}), [])


if __name__ == "__main__":
    unittest.main()
