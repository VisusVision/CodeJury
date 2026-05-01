"""
JSON Schema snippets for LLM agent outputs (Draft 2020-12).

Used with jsonschema after parse + required_keys checks; repair retries reuse the LLM.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator


def collect_validation_messages(instance: Any, schema: dict[str, Any], *, limit: int = 12) -> list[str]:
    """Return human-readable validation issues, or [] if valid."""
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    out: list[str] = []
    for err in errors[:limit]:
        loc = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{loc}: {err.message}")
    return out


CODE_QUALITY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "time_complexity",
        "space_complexity",
        "algorithm_analysis",
        "data_structure_analysis",
        "issues",
        "score",
    ],
    "properties": {
        "time_complexity": {"type": "string"},
        "space_complexity": {"type": "string"},
        "algorithm_analysis": {"type": "string"},
        "data_structure_analysis": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "description", "severity", "suggested_fix"],
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                    "line": {"type": ["integer", "null"]},
                },
                "additionalProperties": True,
            },
        },
        "score": {"type": "number", "minimum": 0, "maximum": 100},
    },
    "additionalProperties": True,
}

TASK_RELEVANCE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "relevance_factor",
        "off_topic",
        "student_fulfills_assignment",
        "explanation",
        "submission_domain_guess",
        "task_domain_guess",
    ],
    "properties": {
        "relevance_factor": {"type": "number", "minimum": 0, "maximum": 1},
        "off_topic": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "student_fulfills_assignment": {"type": "boolean"},
        "explanation": {"type": "string"},
        "submission_domain_guess": {"type": "string"},
        "task_domain_guess": {"type": "string"},
    },
    "additionalProperties": True,
}

TEST_AGENT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "compilation_success",
        "runs_successfully",
        "passed_tests",
        "failed_tests",
        "test_failures",
        "runtime_errors",
        "edge_case_handling",
        "edge_cases_observed",
        "performance_notes",
        "score",
    ],
    "properties": {
        "compilation_success": {"type": "boolean"},
        "runs_successfully": {"type": "boolean"},
        "passed_tests": {"type": "integer", "minimum": 0},
        "failed_tests": {"type": "integer", "minimum": 0},
        "test_failures": {"type": "array"},
        "runtime_errors": {"type": "array"},
        "edge_case_handling": {
            "type": "string",
            "enum": ["poor", "fair", "good", "excellent"],
        },
        "edge_cases_observed": {"type": "array"},
        "performance_notes": {"type": "string"},
        "score": {"type": "number", "minimum": 0, "maximum": 100},
    },
    "additionalProperties": True,
}
