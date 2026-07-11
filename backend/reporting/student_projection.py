"""Student-safe projection of private analysis pipeline results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

STUDENT_TOP_LEVEL_KEYS = frozenset({
    "totalScore",
    "maxScore",
    "rubric",
    "agents",
    "evidence",
    "fileName",
    "executionTimeMs",
    "memoryUsageMb",
    "peakMemoryMb",
    "analysisEngine",
    "summary",
    "strengths",
    "weaknesses",
    "recommendations",
    "resourceRecommendations",
    "relevanceScoreWarning",
    "taskAlignment",
    "reportStatus",
    "testSource",
    "testEvidenceStatus",
    "formalPassed",
    "formalTotal",
    "hiddenTestSummary",
})

PRIVATE_TOP_LEVEL_FRAGMENT_KEYS = frozenset({
    "testSetId",
    "testSetHash",
    "cacheVersion",
    "generationAttempts",
    "formalScore",
})

AGENT_KEYS = frozenset({"id", "name", "summary", "score", "maxScore", "findings", "testResults"})
FINDING_KEYS = frozenset({"severity", "message", "line", "agent", "code"})
ALGORITHM_RESULT_STUDENT_KEYS = frozenset({
    "detectedAlgorithms",
    "dataStructures",
    "timeComplexity",
    "spaceComplexity",
    "actualFamily",
    "actualConfidence",
    "expectedComplexity",
    "expectedApproach",
    "complexityGap",
    "gapSteps",
    "gapExplanation",
    "recommendedApproach",
    "evidence",
})
ALGORITHM_EVIDENCE_STUDENT_KEYS = frozenset({"line", "kind", "detail"})
ALGORITHM_RESULT_SNAKE_TO_CAMEL = {
    "detected_algorithms": "detectedAlgorithms",
    "data_structures": "dataStructures",
    "time_complexity": "timeComplexity",
    "space_complexity": "spaceComplexity",
    "actual_family": "actualFamily",
    "actual_confidence": "actualConfidence",
    "expected_complexity": "expectedComplexity",
    "expected_approach": "expectedApproach",
    "complexity_gap": "complexityGap",
    "gap_steps": "gapSteps",
    "gap_explanation": "gapExplanation",
    "recommended_approach": "recommendedApproach",
}
PUBLIC_TEST_KEYS = frozenset({
    "name",
    "input",
    "expected",
    "actual",
    "passed",
    "visibility",
    "status",
    "source",
    "matchPct",
    "diffDetail",
})
HIDDEN_TEST_KEYS = frozenset({"name", "visibility", "status", "passed"})

SAFE_HIDDEN_METADATA_KEYS = frozenset({"visibility", "status", "passed", "source"})
SAFE_HIDDEN_STATUS_VALUES = frozenset({"passed", "failed", "error", "pass", "fail"})

GENERIC_HIDDEN_FAILURE_MESSAGE = "Hidden test basarisiz."
GENERIC_REDACTED_TEXT = "İçerik gizli test verisi barındırdığı için kaldırıldı."

STUDENT_SAFE_TEST_SOURCE_VALUES = frozenset({
    "faculty",
    "auto_generated",
    "none",
    "manual",
    "ai_approved",
})
STUDENT_SAFE_TEST_EVIDENCE_STATUS_VALUES = frozenset({"available", "unavailable"})


@dataclass(frozen=True)
class HiddenFragments:
    strings: list[str]
    token_strings: list[str]
    numbers: list[Decimal]
    has_nan: bool = False


_NUMERIC_LITERAL = (
    r"[+-]?(?:(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?|inf(?:inity)?)"
)
_NUMERIC_FULL_PATTERN = re.compile(rf"{_NUMERIC_LITERAL}\Z", re.IGNORECASE)
_NUMERIC_TOKEN_PATTERN = re.compile(
    rf"(?<![\w.]){_NUMERIC_LITERAL}(?![\w.])",
    re.IGNORECASE,
)
_NAN_FULL_PATTERN = re.compile(r"[+-]?nan\Z", re.IGNORECASE)
_NAN_TOKEN_PATTERN = re.compile(
    r"(?<![\w.])[+-]?nan(?![\w.])",
    re.IGNORECASE,
)
_SHORT_WORD_FRAGMENT_PATTERN = re.compile(r"\w{1,3}\Z")


def project_student_result(private_result: dict[str, Any]) -> dict[str, Any]:
    """Build a student-safe allowlisted projection of a private analysis result.

    Never mutates the input. Never includes hidden test raw data or private diagnostics.
    """
    hidden_private_fragments = _collect_hidden_private_fragments(private_result)
    projected_agents = _project_agents(private_result.get("agents", []), hidden_private_fragments)

    projected: dict[str, Any] = {}
    for key in STUDENT_TOP_LEVEL_KEYS:
        if key in {"agents", "hiddenTestSummary"}:
            if key == "agents" and projected_agents:
                projected["agents"] = projected_agents
            continue
        if key not in private_result:
            continue
        value = private_result[key]
        if value is None:
            continue
        projected[key] = _sanitize_top_level_value(key, value, hidden_private_fragments)
    redacted = _deep_redact(projected, hidden_private_fragments)
    restored = _restore_synthetic_hidden_test_fields(redacted, projected_agents)
    hidden_summary = _compute_hidden_test_summary(restored.get("agents"))
    if hidden_summary is not None:
        restored["hiddenTestSummary"] = hidden_summary
    return restored


def _sanitize_text(value: str, hidden_fragments: HiddenFragments) -> str:
    if _message_leaks_hidden_data(value, hidden_fragments):
        return GENERIC_REDACTED_TEXT
    return value


def _sanitize_string_list(items: Any, hidden_fragments: HiddenFragments) -> list[str]:
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, str) and not _message_leaks_hidden_data(item, hidden_fragments)
    ]


def _value_contains_leak(value: Any, hidden_fragments: HiddenFragments) -> bool:
    """Recursively check whether ANY string leaf inside value (dict/list/str, any depth) leaks."""
    if isinstance(value, str):
        return _message_leaks_hidden_data(value, hidden_fragments)
    if isinstance(value, dict):
        return any(
            (isinstance(k, str) and _message_leaks_hidden_data(k, hidden_fragments))
            or _value_contains_leak(v, hidden_fragments)
            for k, v in value.items()
        )
    if isinstance(value, list):
        return any(_value_contains_leak(item, hidden_fragments) for item in value)
    return False


def _deep_redact(value: Any, hidden_fragments: HiddenFragments) -> Any:
    """Recursively replace any leaking string leaf with GENERIC_REDACTED_TEXT."""
    if isinstance(value, str):
        return _sanitize_text(value, hidden_fragments)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            safe_key = k
            if isinstance(k, str) and _message_leaks_hidden_data(k, hidden_fragments):
                safe_key = "redacted_key"
            result[safe_key] = _deep_redact(v, hidden_fragments)
        return result
    if isinstance(value, list):
        return [_deep_redact(item, hidden_fragments) for item in value]
    return value


def _deep_sanitize_list(items: Any, hidden_fragments: HiddenFragments) -> list[Any]:
    """Drop list items that leak hidden data at any depth."""
    if not isinstance(items, list):
        return []
    return [item for item in items if not _value_contains_leak(item, hidden_fragments)]


def _sanitize_top_level_value(
    key: str,
    value: Any,
    hidden_fragments: HiddenFragments,
) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value, hidden_fragments)
    if key in ("evidence", "resourceRecommendations"):
        return _deep_sanitize_list(value, hidden_fragments)
    if key in ("strengths", "weaknesses", "recommendations"):
        return _sanitize_string_list(value, hidden_fragments)
    if key == "testSource" and isinstance(value, str) and value in STUDENT_SAFE_TEST_SOURCE_VALUES:
        return value
    if (
        key == "testEvidenceStatus"
        and isinstance(value, str)
        and value in STUDENT_SAFE_TEST_EVIDENCE_STATUS_VALUES
    ):
        return value
    if key in ("rubric", "taskAlignment"):
        return _deep_redact(value, hidden_fragments)
    return value


def _collect_hidden_private_fragments(private_result: dict[str, Any]) -> HiddenFragments:
    string_fragments: list[str] = []
    token_string_fragments: list[str] = []
    numeric_fragments: list[Decimal] = []
    has_nan = False
    for agent in private_result.get("agents", []) or []:
        if not isinstance(agent, dict) or agent.get("id") != "testing":
            continue
        for case in agent.get("testResults", []) or []:
            if not isinstance(case, dict):
                continue
            if str(case.get("visibility") or "").strip().lower() != "hidden":
                continue
            for field_key, field_value in case.items():
                if (
                    field_key in SAFE_HIDDEN_METADATA_KEYS
                    and _is_safe_hidden_metadata_value(field_key, field_value)
                ):
                    continue
                has_nan = _collect_hidden_leaves(
                    field_value,
                    string_fragments,
                    token_string_fragments,
                    numeric_fragments,
                    has_nan,
                ) or has_nan
    has_nan = _collect_top_level_private_provenance(
        private_result,
        string_fragments,
        token_string_fragments,
        numeric_fragments,
        has_nan,
    )
    return HiddenFragments(
        strings=string_fragments,
        token_strings=token_string_fragments,
        numbers=numeric_fragments,
        has_nan=has_nan,
    )


def _collect_top_level_private_provenance(
    private_result: dict[str, Any],
    string_out: list[str],
    token_string_out: list[str],
    numeric_out: list[Decimal],
    has_nan: bool,
) -> bool:
    """Collect redactable fragments from private top-level provenance fields."""
    for key in PRIVATE_TOP_LEVEL_FRAGMENT_KEYS:
        if key not in private_result:
            continue
        value = private_result[key]
        if key == "cacheVersion" and _is_numeric_leaf(value):
            if isinstance(value, float) and value != value:
                has_nan = True
            else:
                decimal_value = _numeric_leaf_to_decimal(value)
                if decimal_value is not None:
                    numeric_out.append(decimal_value)
            continue
        has_nan = _collect_hidden_leaves(
            value,
            string_out,
            token_string_out,
            numeric_out,
            has_nan,
        ) or has_nan
    for prov_key in ("oracleValidation", "oracle_validation"):
        if prov_key in private_result:
            has_nan = _collect_hidden_leaves(
                private_result[prov_key],
                string_out,
                token_string_out,
                numeric_out,
                has_nan,
            ) or has_nan
    return has_nan


def _is_safe_hidden_metadata_value(field_key: str, field_value: Any) -> bool:
    """Return True only when a metadata field holds an expected safe literal.

    Key name alone must not suppress fragment collection — an unexpected value
    in visibility/status/passed could leak via substring match elsewhere.
    """
    if field_key == "visibility":
        return field_value == "hidden"
    if field_key == "status":
        return isinstance(field_value, str) and field_value in SAFE_HIDDEN_STATUS_VALUES
    if field_key == "passed":
        if isinstance(field_value, bool):
            return True
        if isinstance(field_value, str):
            return field_value.strip().lower() in {"true", "false"}
    if field_key == "source":
        return isinstance(field_value, str) and field_value in {
            "manual",
            "ai_approved",
            "auto_generated",
        }
    return False


def _is_numeric_leaf(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_leaf_to_decimal(value: int | float) -> Decimal | None:
    """Canonicalize a numeric leaf for exact-value comparison.

    Returns None for NaN, which must be handled via standalone-token matching.
    """
    if isinstance(value, float) and value != value:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _collect_hidden_leaves(
    value: Any,
    string_out: list[str],
    token_string_out: list[str],
    numeric_out: list[Decimal],
    has_nan: bool,
) -> bool:
    """Recursively collect string and numeric leaves from hidden test case fields."""
    if isinstance(value, str):
        text = value.strip()
        if text:
            has_nan = _collect_hidden_string_fragment(
                text,
                string_out,
                token_string_out,
                numeric_out,
                has_nan,
            )
        return has_nan
    if _is_numeric_leaf(value):
        if isinstance(value, float) and value != value:
            return True
        decimal_value = _numeric_leaf_to_decimal(value)
        if decimal_value is not None:
            numeric_out.append(decimal_value)
        return has_nan
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                key_text = k.strip()
                if key_text:
                    has_nan = _collect_hidden_string_fragment(
                        key_text,
                        string_out,
                        token_string_out,
                        numeric_out,
                        has_nan,
                    )
            elif _is_numeric_leaf(k):
                if isinstance(k, float) and k != k:
                    has_nan = True
                else:
                    decimal_key = _numeric_leaf_to_decimal(k)
                    if decimal_key is not None:
                        numeric_out.append(decimal_key)
            has_nan = _collect_hidden_leaves(
                v,
                string_out,
                token_string_out,
                numeric_out,
                has_nan,
            ) or has_nan
        return has_nan
    if isinstance(value, list):
        for item in value:
            has_nan = _collect_hidden_leaves(
                item,
                string_out,
                token_string_out,
                numeric_out,
                has_nan,
            ) or has_nan
        return has_nan
    return has_nan


def _collect_hidden_string_fragment(
    text: str,
    string_out: list[str],
    token_string_out: list[str],
    numeric_out: list[Decimal],
    has_nan: bool,
) -> bool:
    """Classify a hidden string without weakening exact leak detection."""
    if _NAN_FULL_PATTERN.fullmatch(text):
        return True
    if _NUMERIC_FULL_PATTERN.fullmatch(text):
        try:
            numeric_out.append(Decimal(text))
            return has_nan
        except InvalidOperation:
            pass
    if _SHORT_WORD_FRAGMENT_PATTERN.fullmatch(text):
        token_string_out.append(text)
    else:
        string_out.append(text)
    return has_nan


def _message_contains_numeric_fragment(message: str, fragments: list[Decimal]) -> bool:
    if not fragments:
        return False
    for match in _NUMERIC_TOKEN_PATTERN.finditer(message):
        try:
            token_value = Decimal(match.group(0))
        except InvalidOperation:
            continue
        if any(token_value == fragment for fragment in fragments):
            return True
    return False


def _message_contains_standalone_nan(message: str) -> bool:
    return _NAN_TOKEN_PATTERN.search(message) is not None


def _message_contains_token_string(message: str, fragment: str) -> bool:
    pattern = rf"(?<!\w){re.escape(fragment)}(?!\w)"
    return re.search(pattern, message) is not None


def _message_leaks_hidden_data(message: str, hidden_fragments: HiddenFragments) -> bool:
    if not message:
        return False
    for fragment in hidden_fragments.strings:
        if fragment and fragment in message:
            return True
    for fragment in hidden_fragments.token_strings:
        if fragment and _message_contains_token_string(message, fragment):
            return True
    if _message_contains_numeric_fragment(message, hidden_fragments.numbers):
        return True
    if hidden_fragments.has_nan and _message_contains_standalone_nan(message):
        return True
    return False


def _project_agents(
    agents: Any,
    hidden_private_fragments: HiddenFragments,
) -> list[dict[str, Any]]:
    if not isinstance(agents, list):
        return []

    projected_agents: list[dict[str, Any]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = agent.get("id")
        projected_agent: dict[str, Any] = {}
        for key in ("id", "name", "summary", "score", "maxScore"):
            if key in agent and agent[key] is not None:
                if key == "summary" and isinstance(agent[key], str):
                    projected_agent[key] = _sanitize_text(agent[key], hidden_private_fragments)
                else:
                    projected_agent[key] = agent[key]

        if agent_id == "testing":
            projected_test_results = _project_test_results(agent.get("testResults", []))
            if projected_test_results:
                projected_agent["testResults"] = projected_test_results
            projected_agent["findings"] = _project_testing_findings(
                agent.get("findings", []),
                hidden_private_fragments,
                projected_test_results,
            )
        elif agent_id == "algorithm":
            projected_algorithm_result = _project_algorithm_result(
                agent,
                hidden_private_fragments,
            )
            if projected_algorithm_result:
                projected_agent["algorithmResult"] = projected_algorithm_result
            projected_agent["findings"] = _project_non_testing_findings(
                agent.get("findings", []),
                hidden_private_fragments,
            )
        else:
            projected_agent["findings"] = _project_non_testing_findings(
                agent.get("findings", []),
                hidden_private_fragments,
            )

        projected_agents.append(projected_agent)
    return projected_agents


def _normalize_algorithm_result_source(agent: dict[str, Any]) -> dict[str, Any]:
    algorithm_result = agent.get("algorithmResult")
    if isinstance(algorithm_result, dict):
        return algorithm_result

    normalized: dict[str, Any] = {}
    for snake_key, camel_key in ALGORITHM_RESULT_SNAKE_TO_CAMEL.items():
        if snake_key in agent and agent[snake_key] is not None:
            normalized[camel_key] = agent[snake_key]
    if "evidence" in agent and agent["evidence"] is not None:
        normalized["evidence"] = agent["evidence"]
    return normalized


def _collect_algorithm_private_fragments(source: dict[str, Any]) -> list[str]:
    private_keys = (
        "expectedFamilies",
        "expectedSource",
        "expectedConfidence",
        "expectationVersion",
        "expectationId",
        "cacheKey",
        "extractorProvider",
        "extractorModel",
        "extractorPromptVersion",
        "verifierProvider",
        "verifierModel",
        "verificationReason",
        "schemaVersion",
    )
    fragments: list[str] = []
    for key in private_keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            fragments.append(value.strip())
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            fragments.append(str(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    fragments.append(item.strip())
    for item in source.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        confidence = item.get("confidence")
        if confidence is not None:
            fragments.append(str(confidence))
    return fragments


def _algorithm_evidence_detail_is_student_safe(detail: Any, private_fragments: list[str]) -> bool:
    if not isinstance(detail, str):
        return detail is not None
    text = detail.strip()
    if not text:
        return False
    lowered = text.lower()
    if "pseudo-code" in lowered or "pseudocode" in lowered:
        return False
    return not any(fragment and fragment in text for fragment in private_fragments)


def _project_algorithm_result(
    agent: dict[str, Any],
    hidden_private_fragments: HiddenFragments,
) -> dict[str, Any]:
    source = _normalize_algorithm_result_source(agent)
    if not source:
        return {}

    private_fragments = _collect_algorithm_private_fragments(source)
    projected: dict[str, Any] = {}
    for key in ALGORITHM_RESULT_STUDENT_KEYS:
        if key == "evidence":
            evidence = source.get("evidence")
            if not isinstance(evidence, list):
                continue
            projected_evidence: list[dict[str, Any]] = []
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                detail = item.get("detail")
                if not _algorithm_evidence_detail_is_student_safe(detail, private_fragments):
                    continue
                rebuilt = {
                    field: item[field]
                    for field in ALGORITHM_EVIDENCE_STUDENT_KEYS
                    if field in item and item[field] is not None
                }
                if not rebuilt:
                    continue
                if _value_contains_leak(rebuilt, hidden_private_fragments):
                    continue
                projected_evidence.append(rebuilt)
            if projected_evidence:
                projected["evidence"] = projected_evidence
            continue

        if key not in source or source[key] is None:
            continue
        value = source[key]
        if isinstance(value, str):
            projected[key] = _sanitize_text(value, hidden_private_fragments)
        else:
            projected[key] = value
    return projected


def _project_non_testing_findings(
    findings: Any,
    hidden_private_fragments: HiddenFragments,
) -> list[dict[str, Any]]:
    if not isinstance(findings, list):
        return []
    projected: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if _value_contains_leak(finding, hidden_private_fragments):
            continue
        rebuilt = {key: finding[key] for key in FINDING_KEYS if key in finding}
        if rebuilt:
            projected.append(rebuilt)
    return projected


def _project_testing_findings(
    findings: Any,
    hidden_private_fragments: HiddenFragments,
    projected_test_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            if _value_contains_leak(finding, hidden_private_fragments):
                continue
            rebuilt = {key: finding[key] for key in FINDING_KEYS if key in finding}
            if rebuilt:
                projected.append(rebuilt)

    for case in projected_test_results:
        if case.get("visibility") != "hidden":
            continue
        if case.get("passed"):
            continue
        status = case.get("status")
        if status not in {"failed", "error"}:
            continue
        projected.append({
            "severity": "error",
            "message": GENERIC_HIDDEN_FAILURE_MESSAGE,
        })
    return projected


def _project_test_results(test_results: Any) -> list[dict[str, Any]]:
    if not isinstance(test_results, list):
        return []

    projected: list[dict[str, Any]] = []
    hidden_index = 0
    for case in test_results:
        if not isinstance(case, dict):
            continue
        visibility = str(case.get("visibility") or "public").strip().lower()
        if visibility == "hidden":
            hidden_index += 1
            projected.append(_project_hidden_test_case(case, hidden_index))
        else:
            projected.append(_project_public_test_case(case))
    return projected


def _project_public_test_case(case: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    if "name" in case:
        projected["name"] = case["name"]
    input_value = case.get("input", case.get("stdin"))
    if input_value is not None:
        projected["input"] = input_value
    expected_value = case.get("expected", case.get("expected_stdout"))
    if expected_value is not None:
        projected["expected"] = expected_value
    actual_value = case.get("actual", case.get("actual_stdout"))
    if actual_value is not None:
        projected["actual"] = actual_value
    for key in ("passed", "visibility", "status", "source", "matchPct", "diffDetail"):
        if key in case:
            projected[key] = case[key]
    if "status" not in projected:
        projected["status"] = "pass" if bool(case.get("passed")) else "fail"
    return projected


def _compute_hidden_test_summary(agents: Any) -> dict[str, int] | None:
    if not isinstance(agents, list):
        return None
    hidden_cases: list[dict[str, Any]] = []
    for agent in agents:
        if not isinstance(agent, dict) or agent.get("id") != "testing":
            continue
        for case in agent.get("testResults", []) or []:
            if isinstance(case, dict) and case.get("visibility") == "hidden":
                hidden_cases.append(case)
    if not hidden_cases:
        return None
    summary = {"passed": 0, "failed": 0, "error": 0, "total": len(hidden_cases)}
    for case in hidden_cases:
        status = str(case.get("status") or "").strip().lower()
        if status in {"passed", "pass"}:
            summary["passed"] += 1
        elif status in {"failed", "fail"}:
            summary["failed"] += 1
        elif status == "error":
            summary["error"] += 1
    return summary


def _project_hidden_test_case(case: dict[str, Any], hidden_index: int) -> dict[str, Any]:
    passed = bool(case.get("passed"))
    return {
        "name": f"Hidden test #{hidden_index}",
        "visibility": "hidden",
        "status": _hidden_test_status(case, passed),
        "passed": passed,
    }


def _hidden_test_status(case: dict[str, Any], passed: bool) -> str:
    explicit_status = str(case.get("status") or "").strip().lower()
    if explicit_status == "error":
        return "error"
    if passed:
        return "passed"
    if explicit_status in {"fail", "failed"}:
        return "failed"
    if explicit_status in {"pass", "passed"}:
        return "passed"
    if _hidden_case_has_error_signal(case):
        return "error"
    return "failed"


def _hidden_case_has_error_signal(case: dict[str, Any]) -> bool:
    if case.get("error") is True or str(case.get("status") or "").strip().lower() == "error":
        return True
    diff_detail = str(case.get("diffDetail") or case.get("diff_detail") or case.get("diff") or "").strip()
    if not diff_detail:
        return False
    lowered = diff_detail.lower()
    error_markers = (
        "traceback",
        "exception",
        "error:",
        "runtimeerror",
        "valueerror",
        "typeerror",
        "indexerror",
        "keyerror",
        "attributeerror",
        "segmentation fault",
        "crash",
    )
    return any(marker in lowered for marker in error_markers)


def _restore_synthetic_hidden_test_fields(
    redacted: dict[str, Any],
    pre_redaction_agents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Restore framework-computed hidden test metadata after blanket redaction.

    Hidden test entries are synthesized with deterministic literals (name,
    visibility, status, passed). Collected fragments from private hidden-case
    content can substring-match those literals (e.g. a case named "hidden" makes
    the fragment "hidden", which would corrupt synthesized visibility="hidden").
    """
    redacted_agents = redacted.get("agents")
    if not isinstance(redacted_agents, list) or not pre_redaction_agents:
        return redacted

    for redacted_agent, original_agent in zip(redacted_agents, pre_redaction_agents):
        if not isinstance(redacted_agent, dict) or not isinstance(original_agent, dict):
            continue
        redacted_results = redacted_agent.get("testResults")
        original_results = original_agent.get("testResults")
        if not isinstance(redacted_results, list) or not isinstance(original_results, list):
            continue
        for redacted_case, original_case in zip(redacted_results, original_results):
            if not isinstance(redacted_case, dict) or not isinstance(original_case, dict):
                continue
            if original_case.get("visibility") != "hidden":
                continue
            redacted_case.clear()
            redacted_case.update({
                field: original_case[field]
                for field in ("name", "visibility", "status", "passed")
                if field in original_case
            })
    return redacted
