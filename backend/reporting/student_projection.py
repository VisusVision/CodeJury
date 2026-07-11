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
})

AGENT_KEYS = frozenset({"id", "name", "summary", "score", "maxScore", "findings", "testResults"})
FINDING_KEYS = frozenset({"severity", "message", "line", "agent", "code"})
PUBLIC_TEST_KEYS = frozenset({
    "name",
    "input",
    "expected",
    "actual",
    "passed",
    "visibility",
    "matchPct",
    "diffDetail",
})
HIDDEN_TEST_KEYS = frozenset({"name", "visibility", "status", "passed"})

SAFE_HIDDEN_METADATA_KEYS = frozenset({"visibility", "status", "passed"})
SAFE_HIDDEN_STATUS_VALUES = frozenset({"passed", "failed", "error"})

GENERIC_HIDDEN_FAILURE_MESSAGE = "Hidden test basarisiz."
GENERIC_REDACTED_TEXT = "İçerik gizli test verisi barındırdığı için kaldırıldı."


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
        if key == "agents":
            if projected_agents:
                projected["agents"] = projected_agents
            continue
        if key not in private_result:
            continue
        value = private_result[key]
        if value is None:
            continue
        projected[key] = _sanitize_top_level_value(key, value, hidden_private_fragments)
    redacted = _deep_redact(projected, hidden_private_fragments)
    return _restore_synthetic_hidden_test_fields(redacted, projected_agents)


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
    return HiddenFragments(
        strings=string_fragments,
        token_strings=token_string_fragments,
        numbers=numeric_fragments,
        has_nan=has_nan,
    )


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
        else:
            projected_agent["findings"] = _project_non_testing_findings(
                agent.get("findings", []),
                hidden_private_fragments,
            )

        projected_agents.append(projected_agent)
    return projected_agents


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
    return {key: case[key] for key in PUBLIC_TEST_KEYS if key in case}


def _project_hidden_test_case(case: dict[str, Any], hidden_index: int) -> dict[str, Any]:
    passed = bool(case.get("passed"))
    return {
        "name": f"Hidden test #{hidden_index}",
        "visibility": "hidden",
        "status": _hidden_test_status(case, passed),
        "passed": passed,
    }


def _hidden_test_status(case: dict[str, Any], passed: bool) -> str:
    if passed:
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
            for field in ("name", "visibility", "status", "passed"):
                if field in original_case:
                    redacted_case[field] = original_case[field]
    return redacted
