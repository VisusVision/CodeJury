"""
JSON Schema snippets for LLM agent outputs (Draft 2020-12).

Used with jsonschema after parse + required_keys checks; repair retries reuse the LLM.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator


def _schema_types(schema: dict[str, Any]) -> set[str]:
    raw = schema.get("type")
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {item for item in raw if isinstance(item, str)}
    return set()


def _coerce_scalar_for_schema(value: Any, schema: dict[str, Any]) -> Any:
    types = _schema_types(schema)

    if "string" in types:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            rule = str(value.get("rule") or value.get("type") or value.get("name") or "").strip()
            description = str(value.get("description") or value.get("message") or value.get("detail") or "").strip()
            line_hint = str(value.get("line_hint") or value.get("line") or "").strip()
            if rule and description:
                text = f"{rule}: {description}"
            else:
                text = description or rule
            if line_hint and text:
                text = f"{text} ({line_hint})"
            if text:
                return text
            return str(value)
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)

    if "null" in types and value == 0 and schema.get("minimum") == 1:
        return None

    if "boolean" in types:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        if isinstance(value, int) and value in {0, 1}:
            return bool(value)

    if "integer" in types and not isinstance(value, bool):
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            try:
                parsed = float(stripped)
            except ValueError:
                return value
            if parsed.is_integer():
                return int(parsed)

    if "number" in types and not isinstance(value, bool):
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return value

    return value


def normalize_instance_for_schema(instance: Any, schema: dict[str, Any]) -> Any:
    """Coerce common LLM JSON type drift before strict schema validation.

    Models sometimes return JSON-valid but schema-loose values such as
    ``"true"`` for booleans or ``"2"`` for integers. This keeps validation
    strict for structure and enums while accepting harmless scalar drift.
    """
    if not isinstance(schema, dict):
        return instance

    schema_types = _schema_types(schema)
    if isinstance(instance, dict) and ("object" in schema_types or "properties" in schema):
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return instance
        normalized = dict(instance)
        for key, child_schema in properties.items():
            if key in normalized and isinstance(child_schema, dict):
                normalized[key] = normalize_instance_for_schema(normalized[key], child_schema)
        return normalized

    if isinstance(instance, list) and "array" in schema_types:
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            return [normalize_instance_for_schema(item, item_schema) for item in instance]
        return instance

    return _coerce_scalar_for_schema(instance, schema)


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

_QUALITY_ENUM = ["poor", "fair", "good", "excellent"]
_SEVERITY_ENUM = ["info", "low", "medium", "high", "critical"]

SENIORITY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "estimated_level",
        "modern_features_usage",
        "error_handling_quality",
        "abstraction_quality",
        "design_patterns",
        "maturity_indicators",
        "immaturity_indicators",
        "idiomatic_usage_score",
        "score",
    ],
    "properties": {
        "estimated_level": {"type": "string", "enum": ["junior", "mid", "senior"]},
        "modern_features_usage": {"type": "string"},
        "error_handling_quality": {"type": "string", "enum": _QUALITY_ENUM},
        "abstraction_quality": {"type": "string", "enum": _QUALITY_ENUM},
        "design_patterns": {"type": "array", "items": {"type": "string"}},
        "maturity_indicators": {"type": "array", "items": {"type": "string"}},
        "immaturity_indicators": {"type": "array", "items": {"type": "string"}},
        "idiomatic_usage_score": {"type": "number", "minimum": 0, "maximum": 100},
        "score": {"type": "number", "minimum": 0, "maximum": 100},
    },
    "additionalProperties": True,
}

GUIDELINE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "naming_quality",
        "documentation_quality",
        "clean_code_score",
        "style_guide_compliance",
        "style_violations",
        "has_docstrings",
        "has_type_hints",
        "function_length_ok",
        "nesting_depth_ok",
        "dry_violations",
        "score",
    ],
    "properties": {
        "naming_quality": {"type": "string", "enum": _QUALITY_ENUM},
        "documentation_quality": {"type": "string", "enum": _QUALITY_ENUM},
        "clean_code_score": {"type": "number", "minimum": 0, "maximum": 100},
        "style_guide_compliance": {"type": "string"},
        "style_violations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["rule", "description", "line_hint", "severity"],
                "properties": {
                    "rule": {"type": "string"},
                    "description": {"type": "string"},
                    "line_hint": {"type": "string"},
                    "severity": {"type": "string", "enum": _SEVERITY_ENUM},
                },
                "additionalProperties": True,
            },
        },
        "has_docstrings": {"type": "boolean"},
        "has_type_hints": {"type": "boolean"},
        "function_length_ok": {"type": "boolean"},
        "nesting_depth_ok": {"type": "boolean"},
        "dry_violations": {"type": "array", "items": {"type": "string"}},
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

SECURITY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "threats",
        "risk_level",
        "safe",
        "total_threats",
        "critical_count",
        "high_count",
        "blocked_imports",
        "score",
    ],
    "properties": {
        "threats": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "severity", "line", "description", "detail"],
                "properties": {
                    "type": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "line": {"type": ["integer", "null"], "minimum": 1},
                    "description": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "risk_level": {"type": "string", "enum": ["safe", "low", "medium", "high", "critical"]},
        "safe": {"type": "boolean"},
        "total_threats": {"type": "integer", "minimum": 0},
        "critical_count": {"type": "integer", "minimum": 0},
        "high_count": {"type": "integer", "minimum": 0},
        "blocked_imports": {"type": "array", "items": {"type": "string"}},
        "score": {"type": "number", "minimum": 0, "maximum": 100},
    },
    "additionalProperties": True,
}

EVIDENCE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "validated_claims",
        "rejected_claims",
        "total_claims_received",
        "total_claims_validated",
    ],
    "properties": {
        "validated_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "lines",
                    "code_snippet",
                    "feedback",
                    "agent_source",
                    "severity",
                    "is_valid",
                ],
                "properties": {
                    "lines": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                    },
                    "line_range": {
                        "type": ["array", "null"],
                        "prefixItems": [
                            {"type": "integer", "minimum": 1},
                            {"type": "integer", "minimum": 1},
                        ],
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "block_id": {"type": ["string", "null"]},
                    "node_type": {
                        "type": "string",
                        "enum": ["function", "class", "if", "for", "while", "try", "with", "return", "line", "file"],
                    },
                    "symbol": {"type": ["string", "null"]},
                    "code_snippet": {"type": "string"},
                    "feedback": {"type": "string"},
                    "agent_source": {"type": "string"},
                    "severity": {"type": "string", "enum": _SEVERITY_ENUM},
                    "is_valid": {"type": "boolean"},
                },
                "additionalProperties": True,
            },
        },
        "rejected_claims": {"type": "array"},
        "total_claims_received": {"type": "integer", "minimum": 0},
        "total_claims_validated": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": True,
}

MASTER_EVALUATOR_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "final_score",
        "rubric_breakdown",
        "summary",
        "strengths",
        "weaknesses",
        "recommendations",
    ],
    "properties": {
        "final_score": {"type": "number", "minimum": 0, "maximum": 100},
        "rubric_breakdown": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "criterion",
                    "label",
                    "weight",
                    "score",
                    "weighted_score",
                    "justification",
                ],
                "properties": {
                    "criterion": {"type": "string"},
                    "label": {"type": "string"},
                    "weight": {"type": "integer", "minimum": 0},
                    "score": {"type": "number", "minimum": 0},
                    "weighted_score": {"type": "number", "minimum": 0},
                    "justification": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}
