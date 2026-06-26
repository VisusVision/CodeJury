"""P1: coerce Evidence LLM payload before JSON Schema validation."""

from __future__ import annotations

import unittest

from backend.agents.evidence import coerce_evidence_llm_payload
from backend.agents.json_output_schema import (
    EVIDENCE_OUTPUT_SCHEMA,
    GUIDELINE_OUTPUT_SCHEMA,
    collect_validation_messages,
    normalize_agent_severity,
    normalize_instance_for_schema,
)


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

    def test_drops_invalid_zero_lines_before_schema_validation(self):
        raw = {
            "validated_claims": [
                {
                    "lines": [0, -1, "2"],
                    "feedback": "eval kullanimi riskli.",
                    "agent_source": "security",
                    "severity": "critical",
                    "is_valid": True,
                }
            ],
            "rejected_claims": [],
            "total_claims_received": 1,
            "total_claims_validated": 1,
        }
        coerced = coerce_evidence_llm_payload(raw)
        msgs = collect_validation_messages(coerced, EVIDENCE_OUTPUT_SCHEMA)
        self.assertEqual(msgs, [], msgs)
        self.assertEqual(coerced["validated_claims"][0]["lines"], [2])

    def test_maps_block_node_type_and_missing_lines(self):
        raw = {
            "validated_claims": [
                {
                    "feedback": "Uzun fonksiyon.",
                    "agent_source": "code_quality",
                    "severity": "medium",
                    "node_type": "block",
                    "line_range": [6, 8],
                }
            ],
            "rejected_claims": [],
            "total_claims_received": 1,
            "total_claims_validated": 1,
        }
        coerced = coerce_evidence_llm_payload(raw)
        msgs = collect_validation_messages(coerced, EVIDENCE_OUTPUT_SCHEMA)
        self.assertEqual(msgs, [], msgs)
        claim = coerced["validated_claims"][0]
        self.assertEqual(claim["node_type"], "line")
        self.assertEqual(claim["lines"], [6])

    def test_coerces_null_code_snippet_to_empty_string(self):
        raw = {
            "validated_claims": [
                {
                    "feedback": "CSV okuma var.",
                    "agent_source": "code_quality",
                    "severity": "medium",
                    "lines": [4],
                    "code_snippet": None,
                }
            ],
            "rejected_claims": [],
            "total_claims_received": 1,
            "total_claims_validated": 1,
        }
        coerced = coerce_evidence_llm_payload(raw)
        msgs = collect_validation_messages(coerced, EVIDENCE_OUTPUT_SCHEMA)
        self.assertEqual(msgs, [], msgs)
        self.assertEqual(coerced["validated_claims"][0]["code_snippet"], "")

    def test_normalize_instance_maps_suggestion_severity(self):
        violation_schema = GUIDELINE_OUTPUT_SCHEMA["properties"]["style_violations"]["items"]
        coerced = normalize_instance_for_schema(
            {"rule": "PEP8", "description": "x", "line_hint": "1", "severity": "suggestion"},
            violation_schema,
        )
        self.assertEqual(coerced["severity"], "low")

    def test_normalize_agent_severity_maps_suggestion(self):
        self.assertEqual(normalize_agent_severity("suggestion"), "low")
        self.assertEqual(normalize_agent_severity("warning"), "medium")


if __name__ == "__main__":
    unittest.main()
