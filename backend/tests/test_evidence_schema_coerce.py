"""P1: coerce Evidence LLM payload before JSON Schema validation."""

from __future__ import annotations

import unittest

from backend.agents.evidence import coerce_evidence_llm_payload
from backend.agents.json_output_schema import EVIDENCE_OUTPUT_SCHEMA, collect_validation_messages


class CoerceEvidenceLlmPayloadTests(unittest.TestCase):
    def test_fills_missing_agent_source_and_lines(self):
        raw = {
            "validated_claims": [
                {
                    "feedback": "CSV okuma var.",
                    "severity": "medium",
                },
                {
                    "feedback": "Guvenlik riski dusuk.",
                    "agent": "security",
                    "severity": "low",
                },
            ],
            "rejected_claims": [],
            "total_claims_received": 2,
            "total_claims_validated": 2,
        }
        coerced = coerce_evidence_llm_payload(raw)
        msgs = collect_validation_messages(coerced, EVIDENCE_OUTPUT_SCHEMA)
        self.assertEqual(msgs, [], msgs)
        self.assertEqual(coerced["validated_claims"][0]["agent_source"], "unknown")
        self.assertEqual(coerced["validated_claims"][0]["lines"], [])
        self.assertTrue(coerced["validated_claims"][0]["is_valid"])
        self.assertEqual(coerced["validated_claims"][1]["agent_source"], "security")

    def test_preserves_existing_valid_claims(self):
        raw = {
            "validated_claims": [
                {
                    "lines": [3],
                    "feedback": "return ifadesi.",
                    "agent_source": "code_quality",
                    "severity": "info",
                    "is_valid": True,
                }
            ],
            "rejected_claims": [],
            "total_claims_received": 1,
            "total_claims_validated": 1,
        }
        coerced = coerce_evidence_llm_payload(raw)
        self.assertEqual(coerced["validated_claims"][0]["lines"], [3])


if __name__ == "__main__":
    unittest.main()
