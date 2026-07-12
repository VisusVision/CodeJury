from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.algorithm_analysis.contracts import AlgorithmEvidence, GapResult
from backend.algorithm_analysis.scoring import apply_algorithm_score_guardrail


REQUIRED_CHECKS = (
    "BASELINE_FAILURE_COUNT",
    "BACKEND_FULL_SUITE_FAILED",
    "FRONTEND_SUITE_FAILED",
    "FRONTEND_BUILD_FAILED",
    "POSTGRES_READY",
    "REDIS_READY",
    "WORKER_READY",
    "SANDBOX_REAL_EXECUTION_FAILED",
    "REAL_LLM_PROVIDER_MISMATCH",
    "TEACHER_JOURNEY_FAILED",
    "STUDENT_JOURNEY_FAILED",
    "AGENT_CONTRACT_FAILED",
    "FORMAL_AUTHORITY_OVERRIDDEN",
    "ALGORITHM_GUARDRAIL_OVERRIDDEN",
    "STUDENT_PRIVATE_DATA_LEAK",
    "UNAUTHORIZED_ACCESS_SUCCEEDED",
    "CLEANUP_RESIDUE_FOUND",
)

REQUIRED_AGENT_IDS = frozenset({
    "code_quality",
    "algorithm",
    "ai_authorship",
    "seniority",
    "guideline",
    "security",
    "testing",
    "evidence",
    "master",
})

REQUIRED_PRESENTATION_AGENT_IDS = frozenset({
    "testing",
    "quality",
    "algorithm",
    "seniority",
    "guideline",
    "security",
    "ai_authorship",
    "evidence",
})

STUDENT_FORBIDDEN_KEYS = frozenset({
    "stdin",
    "input",
    "expected",
    "expected_stdout",
    "actual",
    "stderr",
    "diff",
    "files",
    "fixtures",
    "oracle_validation",
    "cacheKey",
    "cache_key",
    "setId",
    "expectationId",
    "expectationVersion",
    "expectedSource",
    "extractorProvider",
    "extractorModel",
    "verifierProvider",
    "verifierModel",
    "verificationReason",
})

_PUBLIC_TEST_IO_KEYS = frozenset({"input", "expected", "actual"})
_GAP_STATUSES = frozenset({
    "better_than_expected",
    "matches_expected",
    "worse_than_expected",
    "unknown",
})

_DIAGNOSTIC_GUARDRAIL_FIELDS = frozenset({
    "score",
    "llm_status",
    "confidence",
    "guardrail_flags",
})
_ALGORITHM_AUTHORITY_FIELDS = (
    "timeComplexity",
    "expectedComplexity",
    "complexityGap",
    "gapSteps",
)

_STRICT_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, strict=True)

_SAFE_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9\-]{0,31}$")
_SAFE_MODEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9/._\-]{0,63}$")
_UNSAFE_STRING_MARKERS = (
    "password",
    "token",
    "secret",
    "cookie",
    "authorization",
    "bearer",
    "csrf",
    "prompt",
    "browser",
    "document",
    "payload",
    "private",
    "raw",
    "dom",
    "source",
)


def _validate_phase4a_run_id(value: str) -> str:
    prefix = "phase4a-"
    if not value.startswith(prefix) or value != f"{prefix}{value[len(prefix):]}":
        raise ValueError("run_id must use phase4a- prefix without extra segments")
    uuid_part = value[len(prefix):]
    try:
        parsed = uuid.UUID(uuid_part, version=4)
    except ValueError as exc:
        raise ValueError("run_id must contain a valid UUIDv4") from exc
    if str(parsed) != uuid_part:
        raise ValueError("run_id UUID must be lowercase")
    return value


class Phase4ABrowserEvidence(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    run_id: str
    assignment_id: str
    job_ids: tuple[str, str, str]
    teacher_journey_passed: bool
    student_journey_passed: bool
    unauthorized_checks_passed: bool
    screenshots: tuple[str, ...] = ()

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return _validate_phase4a_run_id(value)


class Phase4ACheck(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    name: str
    safe_value: bool | int | str
    passed: bool
    detail_code: str = ""


class Phase4AReleaseLedger(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    run_id: str
    provider: str
    model: str
    checks: tuple[Phase4ACheck, ...]

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return _validate_phase4a_run_id(value)

    @model_validator(mode="after")
    def require_each_release_check_once(self) -> "Phase4AReleaseLedger":
        counts = Counter(check.name for check in self.checks)
        required = set(REQUIRED_CHECKS)
        if set(counts) != required or any(counts[name] != 1 for name in required):
            raise ValueError("checks must contain every required release gate exactly once")
        return self


class Phase4AAnalysisAudit(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    agent_contract_failed: bool
    formal_authority_overridden: bool
    algorithm_guardrail_overridden: bool
    student_private_data_leak: bool


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _items_by_id(value: Any) -> tuple[dict[str, Mapping[str, Any]], bool]:
    if not _is_sequence(value):
        return {}, True
    items: dict[str, Mapping[str, Any]] = {}
    invalid = False
    for raw in value:
        if not isinstance(raw, Mapping):
            invalid = True
            continue
        item_id = raw.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in items:
            invalid = True
            continue
        items[item_id] = raw
    return items, invalid


def _presentation_contract(
    private_agents: Mapping[str, Mapping[str, Any]],
    student_agents: Mapping[str, Mapping[str, Any]],
) -> bool:
    if set(private_agents) != REQUIRED_PRESENTATION_AGENT_IDS:
        return True
    if set(student_agents) != REQUIRED_PRESENTATION_AGENT_IDS:
        return True
    return False


def _diagnostic_contract(private_result: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], bool]:
    diagnostics = private_result.get("agentDiagnostics")
    if not isinstance(diagnostics, Mapping):
        return {}, True
    agents, invalid = _items_by_id(diagnostics.get("agents"))
    if set(agents) != REQUIRED_AGENT_IDS:
        invalid = True
    for agent_id in REQUIRED_AGENT_IDS:
        agent = agents.get(agent_id)
        if agent is None or not _DIAGNOSTIC_GUARDRAIL_FIELDS.issubset(agent):
            invalid = True
            continue
        if not isinstance(agent.get("guardrail_flags"), (list, tuple)):
            invalid = True
    return agents, invalid


def _valid_audited_score(score: Any) -> bool:
    return (
        isinstance(score, int)
        and not isinstance(score, bool)
        and 0 <= score <= 100
        and math.isfinite(score)
    )


def _valid_no_formal_testing_score(score: Any) -> bool:
    return _valid_audited_score(score) and score <= 40


def _valid_formal_totals(result: Mapping[str, Any]) -> tuple[int, int] | None:
    passed = result.get("formalPassed")
    total = result.get("formalTotal")
    if (
        not isinstance(passed, int)
        or isinstance(passed, bool)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or passed < 0
        or total < 0
        or passed > total
    ):
        return None
    return passed, total


def _gap_from_algorithm_result(
    algorithm_result: Mapping[str, Any],
    *,
    guardrail_flags: Sequence[Any],
) -> GapResult | None:
    status = algorithm_result.get("complexityGap")
    if status not in _GAP_STATUSES:
        return None
    steps = algorithm_result.get("gapSteps")
    if steps is not None and (not isinstance(steps, int) or isinstance(steps, bool)):
        return None
    approach_mismatch = "algorithm_approach_mismatch" in guardrail_flags
    explanation = algorithm_result.get("gapExplanation")
    return GapResult(
        status=status,  # type: ignore[arg-type]
        steps=steps if isinstance(steps, int) else None,
        approach_mismatch=approach_mismatch,
        explanation=str(explanation or ""),
    )


def _evidence_from_algorithm_result(
    algorithm_result: Mapping[str, Any],
) -> tuple[AlgorithmEvidence, ...]:
    raw = algorithm_result.get("evidence")
    if not isinstance(raw, (list, tuple)):
        return ()
    parsed: list[AlgorithmEvidence] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("kind")
        line = item.get("line")
        detail = item.get("detail")
        confidence = item.get("confidence")
        if not isinstance(kind, str) or not isinstance(line, int) or isinstance(line, bool):
            continue
        if not isinstance(detail, str) or not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            continue
        try:
            parsed.append(
                AlgorithmEvidence(
                    kind=kind,
                    line=line,
                    detail=detail,
                    confidence=float(confidence),
                )
            )
        except ValueError:
            continue
    return tuple(parsed)


def _expected_algorithm_score(
    private_algorithm: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
) -> int | None:
    algorithm_result = private_algorithm.get("algorithmResult")
    if not isinstance(algorithm_result, Mapping):
        return None
    guardrail_flags = tuple(
        flag
        for flag in (diagnostic.get("guardrail_flags") or private_algorithm.get("guardrail_flags") or ())
        if isinstance(flag, str)
    )
    gap = _gap_from_algorithm_result(algorithm_result, guardrail_flags=guardrail_flags)
    if gap is None:
        return None

    base_score = algorithm_result.get("programmatic_base_score")
    if not _valid_audited_score(base_score):
        base_score = private_algorithm.get("score")
    if not _valid_audited_score(base_score):
        return None

    llm_score = private_algorithm.get("score")
    if not _valid_audited_score(llm_score):
        llm_score = base_score

    evidence = _evidence_from_algorithm_result(algorithm_result)
    decision = apply_algorithm_score_guardrail(
        int(base_score),
        int(llm_score),
        gap,
        evidence,
    )
    return decision.score


def _formal_authority_was_overridden(
    private_result: Mapping[str, Any],
    student_result: Mapping[str, Any],
    private_agents: Mapping[str, Mapping[str, Any]],
    student_agents: Mapping[str, Mapping[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
) -> bool:
    private_totals = _valid_formal_totals(private_result)
    student_totals = _valid_formal_totals(student_result)
    if private_totals is None or student_totals != private_totals:
        return True
    private_testing = private_agents.get("testing")
    student_testing = student_agents.get("testing")
    testing_diagnostic = diagnostics.get("testing")
    if private_testing is None or student_testing is None or testing_diagnostic is None:
        return True

    scores = (
        private_testing.get("score"),
        student_testing.get("score"),
        testing_diagnostic.get("score"),
    )
    if not all(_valid_audited_score(score) for score in scores):
        return True
    if len({score for score in scores}) != 1:
        return True

    passed, total = private_totals
    score = scores[0]
    if total > 0:
        formal_score = round(100 * passed / total)
        return score != formal_score
    return not _valid_no_formal_testing_score(score)


def _algorithm_guardrail_was_overridden(
    private_agents: Mapping[str, Mapping[str, Any]],
    student_agents: Mapping[str, Mapping[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
) -> bool:
    private_algorithm = private_agents.get("algorithm")
    student_algorithm = student_agents.get("algorithm")
    diagnostic = diagnostics.get("algorithm")
    if private_algorithm is None or student_algorithm is None or diagnostic is None:
        return True
    private_result = private_algorithm.get("algorithmResult")
    student_result = student_algorithm.get("algorithmResult")
    if not isinstance(private_result, Mapping) or not isinstance(student_result, Mapping):
        return True

    scores = (
        private_algorithm.get("score"),
        student_algorithm.get("score"),
        diagnostic.get("score"),
    )
    if not all(_valid_audited_score(score) for score in scores):
        return True

    expected_score = _expected_algorithm_score(private_algorithm, diagnostic)
    if expected_score is None or any(score != expected_score for score in scores):
        return True

    return any(
        not _algorithm_authority_field_matches(private_result, student_result, field)
        for field in _ALGORITHM_AUTHORITY_FIELDS
    )


def _algorithm_authority_field_matches(
    private_result: Mapping[str, Any],
    student_result: Mapping[str, Any],
    field: str,
) -> bool:
    """Student projection may omit null authority fields; treat that as equal."""
    if field not in private_result:
        return False
    private_value = private_result[field]
    if field not in student_result:
        return private_value is None
    return student_result[field] == private_value


def _is_public_test_case(case: Mapping[str, Any]) -> bool:
    return str(case.get("visibility") or "").strip().lower() == "public"


def _contains_forbidden_key(value: Any, *, allow_public_test_io: bool = False) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key in STUDENT_FORBIDDEN_KEYS:
                if allow_public_test_io and key in _PUBLIC_TEST_IO_KEYS:
                    continue
                return True
            if _contains_forbidden_key(nested, allow_public_test_io=allow_public_test_io):
                return True
        return False
    if _is_sequence(value):
        return any(_contains_forbidden_key(item, allow_public_test_io=allow_public_test_io) for item in value)
    return False


def _student_private_data_leak(student_result: Mapping[str, Any]) -> bool:
    agents = student_result.get("agents")
    if _is_sequence(agents):
        for agent in agents:
            if not isinstance(agent, Mapping):
                if _contains_forbidden_key(agent):
                    return True
                continue
            agent_id = agent.get("id")
            if agent_id == "testing":
                test_results = agent.get("testResults")
                if _is_sequence(test_results):
                    for case in test_results:
                        if not isinstance(case, Mapping):
                            if _contains_forbidden_key(case):
                                return True
                            continue
                        allow_public_io = _is_public_test_case(case)
                        if _contains_forbidden_key(case, allow_public_test_io=allow_public_io):
                            return True
                agent_without_results = {
                    key: value for key, value in agent.items() if key != "testResults"
                }
                if _contains_forbidden_key(agent_without_results):
                    return True
                continue
            if _contains_forbidden_key(agent):
                return True
        remainder = {key: value for key, value in student_result.items() if key != "agents"}
        return _contains_forbidden_key(remainder)
    return _contains_forbidden_key(student_result)


def _high_entropy_sentinel(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    sentinel = value.strip()
    if len(sentinel) < 16 or len(set(sentinel)) < 8:
        return None
    return sentinel


def _contains_sentinel(value: Any, sentinels: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return any(sentinel in value for sentinel in sentinels)
    if isinstance(value, Mapping):
        return any(
            (isinstance(key, str) and any(sentinel in key for sentinel in sentinels))
            or _contains_sentinel(nested, sentinels)
            for key, nested in value.items()
        )
    if _is_sequence(value):
        return any(_contains_sentinel(item, sentinels) for item in value)
    return False


def _string_is_unsafe(value: str) -> bool:
    if not value or len(value) > 160:
        return True
    if any(marker in value.lower() for marker in _UNSAFE_STRING_MARKERS):
        return True
    if any(char in value for char in ("\n", "\r", "\t", "=", ";", "|", "<", ">", "{", "}", "[", "]")):
        return True
    if _high_entropy_sentinel(value) is not None:
        return True
    return False


def _safe_provider_or_model(value: str, *, kind: str) -> bool:
    if _string_is_unsafe(value):
        return False
    pattern = _SAFE_PROVIDER_PATTERN if kind == "provider" else _SAFE_MODEL_PATTERN
    return pattern.fullmatch(value) is not None


def audit_analysis_pair(
    private_result: Mapping[str, Any],
    student_result: Mapping[str, Any],
    *,
    private_sentinels: Sequence[str] = (),
) -> Phase4AAnalysisAudit:
    diagnostics, diagnostic_invalid = _diagnostic_contract(private_result)
    private_agents, private_agents_invalid = _items_by_id(private_result.get("agents"))
    student_agents, student_agents_invalid = _items_by_id(student_result.get("agents"))

    private_algorithm = private_agents.get("algorithm")
    student_algorithm = student_agents.get("algorithm")
    agent_contract_failed = any((
        private_result.get("reportStatus") != "ready",
        student_result.get("reportStatus") != "ready",
        diagnostic_invalid,
        private_agents_invalid,
        student_agents_invalid,
        _presentation_contract(private_agents, student_agents),
        private_algorithm is None,
        student_algorithm is None,
        private_algorithm is not None
        and not isinstance(private_algorithm.get("algorithmResult"), Mapping),
        student_algorithm is not None
        and not isinstance(student_algorithm.get("algorithmResult"), Mapping),
        _valid_formal_totals(private_result) is None,
        _valid_formal_totals(student_result) is None,
    ))

    sentinels = tuple(
        sentinel
        for raw in private_sentinels
        if (sentinel := _high_entropy_sentinel(raw)) is not None
    )
    student_private_data_leak = _student_private_data_leak(student_result) or (
        bool(sentinels) and _contains_sentinel(student_result, sentinels)
    )

    return Phase4AAnalysisAudit(
        agent_contract_failed=agent_contract_failed,
        formal_authority_overridden=_formal_authority_was_overridden(
            private_result,
            student_result,
            private_agents,
            student_agents,
            diagnostics,
        ),
        algorithm_guardrail_overridden=_algorithm_guardrail_was_overridden(
            private_agents,
            student_agents,
            diagnostics,
        ),
        student_private_data_leak=student_private_data_leak,
    )


def _console_value(value: bool | int | str) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    return "REDACTED"


def safe_ledger_lines(ledger: Phase4AReleaseLedger) -> tuple[str, ...]:
    provider = ledger.provider if _safe_provider_or_model(ledger.provider, kind="provider") else "REDACTED"
    model = ledger.model if _safe_provider_or_model(ledger.model, kind="model") else "REDACTED"
    lines = [
        f"PROVIDER={provider}",
        f"MODEL={model}",
    ]
    for check in ledger.checks:
        safe_value = check.safe_value
        if isinstance(safe_value, str):
            rendered = "REDACTED"
        else:
            rendered = _console_value(safe_value)
        lines.append(f"{check.name}={rendered}")
    return tuple(lines)


__all__ = [
    "REQUIRED_AGENT_IDS",
    "REQUIRED_CHECKS",
    "REQUIRED_PRESENTATION_AGENT_IDS",
    "STUDENT_FORBIDDEN_KEYS",
    "Phase4AAnalysisAudit",
    "Phase4ABrowserEvidence",
    "Phase4ACheck",
    "Phase4AReleaseLedger",
    "audit_analysis_pair",
    "safe_ledger_lines",
]
