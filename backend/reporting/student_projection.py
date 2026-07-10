"""Student-safe projection of private analysis pipeline results."""

from __future__ import annotations

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

HIDDEN_PRIVATE_FIELD_NAMES = (
    "name",
    "input",
    "stdin",
    "expected",
    "expected_stdout",
    "actual",
    "actual_stdout",
    "stderr",
    "actual_stderr",
    "diff",
    "diffDetail",
)

GENERIC_HIDDEN_FAILURE_MESSAGE = "Hidden test basarisiz."
GENERIC_REDACTED_TEXT = "İçerik gizli test verisi barındırdığı için kaldırıldı."


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
    return projected


def _sanitize_text(value: str, hidden_fragments: list[str]) -> str:
    if _message_leaks_hidden_data(value, hidden_fragments):
        return GENERIC_REDACTED_TEXT
    return value


def _sanitize_string_list(items: Any, hidden_fragments: list[str]) -> list[str]:
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, str) and not _message_leaks_hidden_data(item, hidden_fragments)
    ]


def _sanitize_evidence_list(items: Any, hidden_fragments: list[str]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    projected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "")
        if _message_leaks_hidden_data(message, hidden_fragments):
            continue
        projected.append(item)
    return projected


def _sanitize_top_level_value(
    key: str,
    value: Any,
    hidden_fragments: list[str],
) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value, hidden_fragments)
    if isinstance(value, list):
        if key == "evidence":
            return _sanitize_evidence_list(value, hidden_fragments)
        if key in ("strengths", "weaknesses", "recommendations"):
            return _sanitize_string_list(value, hidden_fragments)
    return value


def _collect_hidden_private_fragments(private_result: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    for agent in private_result.get("agents", []) or []:
        if not isinstance(agent, dict) or agent.get("id") != "testing":
            continue
        for case in agent.get("testResults", []) or []:
            if not isinstance(case, dict):
                continue
            if str(case.get("visibility") or "").strip().lower() != "hidden":
                continue
            for field_name in HIDDEN_PRIVATE_FIELD_NAMES:
                raw = case.get(field_name)
                if raw is None:
                    continue
                text = str(raw).strip()
                if text:
                    fragments.append(text)
    return fragments


def _message_leaks_hidden_data(message: str, hidden_fragments: list[str]) -> bool:
    if not message:
        return False
    for fragment in hidden_fragments:
        if fragment and fragment in message:
            return True
    return False


def _project_agents(
    agents: Any,
    hidden_private_fragments: list[str],
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
    hidden_private_fragments: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(findings, list):
        return []
    projected: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        message = str(finding.get("message") or "")
        if _message_leaks_hidden_data(message, hidden_private_fragments):
            continue
        rebuilt = {key: finding[key] for key in FINDING_KEYS if key in finding}
        if rebuilt:
            projected.append(rebuilt)
    return projected


def _project_testing_findings(
    findings: Any,
    hidden_private_fragments: list[str],
    projected_test_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            message = str(finding.get("message") or "")
            if _message_leaks_hidden_data(message, hidden_private_fragments):
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
