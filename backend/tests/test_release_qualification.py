from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.ops.release_qualification import (
    REQUIRED_AGENT_IDS,
    REQUIRED_CHECKS,
    REQUIRED_PRESENTATION_AGENT_IDS,
    STUDENT_FORBIDDEN_KEYS,
    Phase4ABrowserEvidence,
    Phase4ACheck,
    Phase4AReleaseLedger,
    audit_analysis_pair,
    safe_ledger_lines,
)
from backend.reporting.student_projection import project_student_result
from frontend.backend import main


RUN_ID = "phase4a-11111111-1111-4111-8111-111111111111"
PRIVATE_SENTINEL = "TASK5_PRIVATE_SENTINEL_7b0864425d834c9d"
PUBLIC_NAME = "PUBLIC_KEEP_NAME_7f3a"
PUBLIC_INPUT = "PUBLIC_KEEP_INPUT_7f3a"
PUBLIC_EXPECTED = "PUBLIC_KEEP_EXPECTED_7f3a"
PUBLIC_ACTUAL = "PUBLIC_KEEP_ACTUAL_7f3a"
_PUBLIC_TEST_IO_KEYS = frozenset({"input", "expected", "actual"})


def _complete_ledger(*, detail: str = "") -> Phase4AReleaseLedger:
    return Phase4AReleaseLedger(
        run_id=RUN_ID,
        provider="nvidia-nim",
        model="meta/llama-test",
        checks=tuple(
            Phase4ACheck(
                name=name,
                safe_value=False if name.endswith("FAILED") else True,
                passed=True,
                detail_code=detail,
            )
            for name in REQUIRED_CHECKS
        ),
    )


def _algorithm_result(
    *,
    complexity_gap: str = "matches_expected",
    gap_steps: int = 0,
    programmatic_base_score: int = 90,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    return {
        "timeComplexity": "O(n)",
        "expectedComplexity": "O(n)",
        "complexityGap": complexity_gap,
        "gapSteps": gap_steps,
        "gapExplanation": "test gap",
        "programmatic_base_score": programmatic_base_score,
        "evidence": evidence or [],
    }


def _presentation_agent(agent_id: str, *, score: int = 80) -> dict[str, object]:
    agent: dict[str, object] = {
        "id": agent_id,
        "name": agent_id,
        "summary": "ready",
        "score": score,
        "maxScore": 100,
        "findings": [],
    }
    if agent_id == "algorithm":
        agent["algorithmResult"] = _algorithm_result()
    if agent_id == "testing":
        agent["testResults"] = [
            {
                "name": PUBLIC_NAME,
                "input": PUBLIC_INPUT,
                "expected": PUBLIC_EXPECTED,
                "actual": PUBLIC_ACTUAL,
                "passed": True,
                "visibility": "public",
            },
            {
                "name": "Hidden test",
                "visibility": "hidden",
                "status": "failed",
                "passed": False,
            },
        ]
    return agent


def _diagnostic_agent(agent_id: str, *, score: int = 80, flags: list[str] | None = None) -> dict[str, object]:
    return {
        "id": agent_id,
        "score": score,
        "llm_status": "ok",
        "confidence": 0.9,
        "guardrail_flags": flags or [],
    }


def _production_private_result(*, algorithm_score: int = 90) -> dict[str, object]:
    private_agents = [
        _presentation_agent(agent_id, score=50 if agent_id == "testing" else algorithm_score)
        for agent_id in sorted(REQUIRED_PRESENTATION_AGENT_IDS)
    ]
    diagnostics = [
        _diagnostic_agent(agent_id, score=50 if agent_id == "testing" else algorithm_score)
        for agent_id in sorted(REQUIRED_AGENT_IDS)
    ]
    return {
        "reportStatus": "ready",
        "formalPassed": 1,
        "formalTotal": 2,
        "agents": private_agents,
        "agentDiagnostics": {"agents": diagnostics},
        "privateEvidence": {"expected_stdout": PRIVATE_SENTINEL},
    }


def _result_pair() -> tuple[dict[str, object], dict[str, object]]:
    private = _production_private_result()
    student = project_student_result(copy.deepcopy(private))
    return private, student


def _set_algorithm_state(
    private: dict[str, object],
    student: dict[str, object],
    *,
    score: int,
    complexity_gap: str,
    gap_steps: int,
    flags: list[str] | None = None,
    evidence: list[dict[str, object]] | None = None,
    programmatic_base_score: int = 90,
) -> None:
    algorithm_result = _algorithm_result(
        complexity_gap=complexity_gap,
        gap_steps=gap_steps,
        programmatic_base_score=programmatic_base_score,
        evidence=evidence,
    )
    for container in (private, student):
        algorithm = next(agent for agent in container["agents"] if agent["id"] == "algorithm")
        algorithm["score"] = score
        algorithm["algorithmResult"] = copy.deepcopy(algorithm_result)
        if flags is not None:
            algorithm["guardrail_flags"] = list(flags)
    diagnostic = next(
        agent for agent in private["agentDiagnostics"]["agents"] if agent["id"] == "algorithm"
    )
    diagnostic["score"] = score
    if flags is not None:
        diagnostic["guardrail_flags"] = list(flags)


def test_release_ledger_requires_every_gate() -> None:
    with pytest.raises(ValidationError):
        Phase4AReleaseLedger(
            run_id="phase4a-12345678-1234-4234-8234-123456789012",
            provider="provider",
            model="model",
            checks=(),
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown"])
def test_release_ledger_requires_each_known_gate_exactly_once(mutation: str) -> None:
    checks = list(_complete_ledger().checks)
    if mutation == "missing":
        checks.pop()
    elif mutation == "duplicate":
        checks[-1] = checks[0]
    else:
        checks[-1] = checks[-1].model_copy(update={"name": "NOT_A_RELEASE_GATE"})

    with pytest.raises(ValidationError):
        Phase4AReleaseLedger(
            run_id=RUN_ID,
            provider="provider",
            model="model",
            checks=tuple(checks),
        )


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    evidence = Phase4ABrowserEvidence(
        run_id=RUN_ID,
        assignment_id="assignment-1",
        job_ids=("job-1", "job-2", "job-3"),
        teacher_journey_passed=True,
        student_journey_passed=True,
        unauthorized_checks_passed=True,
    )
    with pytest.raises(ValidationError):
        evidence.assignment_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Phase4ACheck(
            name=REQUIRED_CHECKS[0],
            safe_value=True,
            passed=True,
            raw_detail="secret",  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    ("raw", "field_name"),
    [
        (1, "teacher_journey_passed"),
        (0, "student_journey_passed"),
        ("true", "unauthorized_checks_passed"),
        ("false", "teacher_journey_passed"),
    ],
)
def test_browser_evidence_rejects_coercive_booleans(raw: object, field_name: str) -> None:
    payload = {
        "run_id": RUN_ID,
        "assignment_id": "assignment-1",
        "job_ids": ("job-1", "job-2", "job-3"),
        "teacher_journey_passed": True,
        "student_journey_passed": True,
        "unauthorized_checks_passed": True,
    }
    payload[field_name] = raw
    with pytest.raises(ValidationError):
        Phase4ABrowserEvidence(**payload)


def test_release_ledger_rejects_coercive_safe_value_and_list_job_ids() -> None:
    with pytest.raises(ValidationError):
        Phase4ACheck(
            name=REQUIRED_CHECKS[0],
            safe_value=1.0,
            passed=True,
        )
    with pytest.raises(ValidationError):
        Phase4ABrowserEvidence(
            run_id=RUN_ID,
            assignment_id="assignment-1",
            job_ids=["job-1", "job-2", "job-3"],
            teacher_journey_passed=True,
            student_journey_passed=True,
            unauthorized_checks_passed=True,
        )


@pytest.mark.parametrize(
    "run_id",
    [
        "phase4a-not-a-uuid",
        "phase4a------------------------------------",
        "phase4a-11111111-1111-3111-8111-111111111111",
        "phase4a-11111111-1111-4111-7111-111111111111",
        "phase4a-11111111-1111-4111-8111-111111111111-extra",
        "prefix-phase4a-11111111-1111-4111-8111-111111111111",
        "PHASE4A-11111111-1111-4111-8111-111111111111",
    ],
)
def test_browser_evidence_rejects_invalid_run_ids(run_id: str) -> None:
    with pytest.raises(ValidationError):
        Phase4ABrowserEvidence(
            run_id=run_id,
            assignment_id="assignment-1",
            job_ids=("job-1", "job-2", "job-3"),
            teacher_journey_passed=True,
            student_journey_passed=True,
            unauthorized_checks_passed=True,
        )


def test_browser_evidence_accepts_valid_uuidv4_run_id() -> None:
    Phase4ABrowserEvidence(
        run_id=RUN_ID,
        assignment_id="assignment-1",
        job_ids=("job-1", "job-2", "job-3"),
        teacher_journey_passed=True,
        student_journey_passed=True,
        unauthorized_checks_passed=True,
    )


def _normalize_browser_evidence_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for field in ("job_ids", "screenshots"):
        value = normalized.get(field)
        if isinstance(value, list):
            normalized[field] = tuple(value)
    return normalized


_BROWSER_EVIDENCE_EXAMPLE_FORBIDDEN = (
    "username",
    "password",
    "cookie",
    "csrf",
    "authorization",
    "bearer",
    "token",
    "secret",
    "credential",
    "prompt",
    "dom",
    "stdin",
    "stderr",
    "source_code",
    "expected_stdout",
    "oracle",
    "extractorprovider",
    "verifierprovider",
    "input",
    "expected",
    "actual",
)


def test_browser_evidence_example_is_valid_and_secret_free() -> None:
    example_path = Path("docs/examples/phase4a-browser-evidence.example.json")
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    evidence = Phase4ABrowserEvidence.model_validate(_normalize_browser_evidence_payload(payload))
    serialized = evidence.model_dump_json().lower()
    for term in _BROWSER_EVIDENCE_EXAMPLE_FORBIDDEN:
        assert term not in serialized, term


def test_browser_evidence_requires_exactly_three_jobs() -> None:
    common = {
        "assignment_id": "assignment-1",
        "teacher_journey_passed": True,
        "student_journey_passed": True,
        "unauthorized_checks_passed": True,
    }
    with pytest.raises(ValidationError):
        Phase4ABrowserEvidence(run_id=RUN_ID, job_ids=("j1", "j2"), **common)


@pytest.mark.parametrize(
    ("channel", "value"),
    [
        ("provider", "PASSWORDTOKEN123456789"),
        ("model", "COOKIESECRET123456789"),
        ("safe_value", "CREDENTIALTOKEN123456789"),
        ("provider", "Authorization: Bearer abcdef"),
        ("model", "session=COOKIESECRET123456789"),
        ("safe_value", "csrf=ABCDEF1234567890"),
        ("provider", "prompt=ignore previous instructions"),
        ("model", "source_code=print('secret')"),
        ("safe_value", "document.querySelector('#secret')"),
        ("provider", "raw/private payload"),
        ("model", "line\nbreak"),
        ("safe_value", "a=b|c"),
        ("provider", "ABCDEFGHIJKLMNOP1234567890"),
    ],
)
def test_safe_lines_redact_unsafe_string_channels(channel: str, value: str) -> None:
    ledger = _complete_ledger(detail=value)
    if channel == "provider":
        ledger = ledger.model_copy(update={"provider": value})
    elif channel == "model":
        ledger = ledger.model_copy(update={"model": value})
    else:
        checks = list(ledger.checks)
        checks[0] = checks[0].model_copy(update={"safe_value": value})
        ledger = ledger.model_copy(update={"checks": tuple(checks)})

    output = "\n".join(safe_ledger_lines(ledger))
    assert value not in output
    assert "detail_code" not in output
    assert "SECRET" not in output


def test_safe_lines_never_emit_secrets() -> None:
    ledger = _complete_ledger(detail="password=SECRET cookie=COOKIE hidden=HIDDEN")
    output = "\n".join(safe_ledger_lines(ledger))
    assert "SECRET" not in output
    assert "COOKIE" not in output
    assert "HIDDEN" not in output
    assert output.splitlines() == [
        "PROVIDER=nvidia-nim",
        "MODEL=meta/llama-test",
        *(f"{check.name}={str(check.safe_value).lower()}" for check in ledger.checks),
    ]


def test_analysis_pair_accepts_production_projection_with_public_and_hidden_tests() -> None:
    private, student = _result_pair()
    audit = audit_analysis_pair(private, student)
    assert audit.agent_contract_failed is False
    assert audit.formal_authority_overridden is False
    assert audit.algorithm_guardrail_overridden is False
    assert audit.student_private_data_leak is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda private, student: private["agentDiagnostics"]["agents"].pop(),
        lambda private, student: student.__setitem__("reportStatus", "preparing"),
        lambda private, student: next(
            agent for agent in student["agents"] if agent["id"] == "algorithm"
        ).pop("algorithmResult"),
        lambda private, student: next(
            agent for agent in private["agentDiagnostics"]["agents"] if agent["id"] == "security"
        ).pop("guardrail_flags"),
        lambda private, student: private["agents"].pop(),
        lambda private, student: student["agents"].append(
            {"id": "unknown", "name": "unknown", "summary": "", "score": 1, "maxScore": 100, "findings": []}
        ),
    ],
)
def test_analysis_pair_flags_incomplete_agent_contract(mutate) -> None:
    private, student = _result_pair()
    mutate(private, student)
    assert audit_analysis_pair(private, student).agent_contract_failed is True


def test_analysis_pair_flags_missing_presentation_agent() -> None:
    private, student = _result_pair()
    private["agents"] = [agent for agent in private["agents"] if agent["id"] != "security"]
    student["agents"] = [agent for agent in student["agents"] if agent["id"] != "security"]
    assert audit_analysis_pair(private, student).agent_contract_failed is True


def test_analysis_pair_flags_formal_authority_override() -> None:
    private, student = _result_pair()
    student["formalPassed"] = 2
    audit = audit_analysis_pair(private, student)
    assert audit.formal_authority_overridden is True


@pytest.mark.parametrize(
    ("score", "expected_override"),
    [
        (-1, True),
        (0, False),
        (40, False),
        (41, True),
        (True, True),
        (False, True),
        (40.0, True),
        (math.nan, True),
        (math.inf, True),
        (-math.inf, True),
    ],
)
def test_analysis_pair_validates_no_formal_testing_scores(score: object, expected_override: bool) -> None:
    private, student = _result_pair()
    private["formalPassed"] = 0
    private["formalTotal"] = 0
    student["formalPassed"] = 0
    student["formalTotal"] = 0
    for container in (private, student):
        testing = next(agent for agent in container["agents"] if agent["id"] == "testing")
        testing["score"] = score
    diagnostic = next(
        agent for agent in private["agentDiagnostics"]["agents"] if agent["id"] == "testing"
    )
    diagnostic["score"] = score
    audit = audit_analysis_pair(private, student)
    assert audit.formal_authority_overridden is expected_override


def test_analysis_pair_flags_algorithm_score_override() -> None:
    private, student = _result_pair()
    algorithm = next(agent for agent in student["agents"] if agent["id"] == "algorithm")
    algorithm["score"] = 99
    audit = audit_analysis_pair(private, student)
    assert audit.algorithm_guardrail_overridden is True


@pytest.mark.parametrize(
    ("complexity_gap", "gap_steps", "score", "expected_override", "flags"),
    [
        ("matches_expected", 0, 90, False, []),
        ("worse_than_expected", 1, 65, False, ["algorithm_gap_one_step_worse"]),
        ("worse_than_expected", 2, 45, False, ["algorithm_gap_multi_step_worse"]),
        ("unknown", 0, 90, False, []),
        ("worse_than_expected", 1, 80, True, ["algorithm_gap_one_step_worse"]),
    ],
)
def test_analysis_pair_enforces_algorithm_guardrail_recompute(
    complexity_gap: str,
    gap_steps: int,
    score: int,
    expected_override: bool,
    flags: list[str],
) -> None:
    private, student = _result_pair()
    _set_algorithm_state(
        private,
        student,
        score=score,
        complexity_gap=complexity_gap,
        gap_steps=gap_steps,
        flags=flags,
    )
    audit = audit_analysis_pair(private, student)
    assert audit.algorithm_guardrail_overridden is expected_override


@pytest.mark.parametrize(
    ("score", "expected_override"),
    [
        (True, True),
        (-1, True),
        (101, True),
    ],
)
def test_analysis_pair_rejects_invalid_algorithm_scores(score: object, expected_override: bool) -> None:
    private, student = _result_pair()
    _set_algorithm_state(
        private,
        student,
        score=80,
        complexity_gap="matches_expected",
        gap_steps=0,
    )
    for container in (private, student):
        algorithm = next(agent for agent in container["agents"] if agent["id"] == "algorithm")
        algorithm["score"] = score
    diagnostic = next(
        agent for agent in private["agentDiagnostics"]["agents"] if agent["id"] == "algorithm"
    )
    diagnostic["score"] = score
    audit = audit_analysis_pair(private, student)
    assert audit.algorithm_guardrail_overridden is expected_override


def test_analysis_pair_flags_equal_but_unauthorized_algorithm_scores() -> None:
    private, student = _result_pair()
    _set_algorithm_state(
        private,
        student,
        score=80,
        complexity_gap="worse_than_expected",
        gap_steps=1,
        flags=["algorithm_gap_one_step_worse"],
    )
    audit = audit_analysis_pair(private, student)
    assert audit.algorithm_guardrail_overridden is True


def test_analysis_pair_flags_evidence_penalty_guardrail() -> None:
    private, student = _result_pair()
    evidence = [
        {
            "kind": "nested_loop",
            "line": 4,
            "detail": "nested loop",
            "confidence": 0.9,
        }
    ]
    _set_algorithm_state(
        private,
        student,
        score=90,
        complexity_gap="matches_expected",
        gap_steps=0,
        evidence=evidence,
    )
    audit = audit_analysis_pair(private, student)
    assert audit.algorithm_guardrail_overridden is True


@pytest.mark.parametrize("forbidden_key", sorted(STUDENT_FORBIDDEN_KEYS))
def test_analysis_pair_recursively_rejects_exact_student_private_keys(forbidden_key: str) -> None:
    private, student = _result_pair()
    if forbidden_key in _PUBLIC_TEST_IO_KEYS:
        student["items"] = [{"nested": {forbidden_key: "leak"}}]
    else:
        student["safe"] = [{"nested": {forbidden_key: "leak"}}]
    assert audit_analysis_pair(private, student).student_private_data_leak is True


@pytest.mark.parametrize("forbidden_key", sorted(_PUBLIC_TEST_IO_KEYS))
def test_analysis_pair_allows_public_test_io_only_in_public_cases(forbidden_key: str) -> None:
    private, student = _result_pair()
    testing = next(agent for agent in student["agents"] if agent["id"] == "testing")
    public_case = next(case for case in testing["testResults"] if case.get("visibility") == "public")
    assert forbidden_key in public_case
    assert audit_analysis_pair(private, student).student_private_data_leak is False


@pytest.mark.parametrize("forbidden_key", sorted(_PUBLIC_TEST_IO_KEYS))
def test_analysis_pair_rejects_public_io_keys_in_hidden_cases(forbidden_key: str) -> None:
    private, student = _result_pair()
    testing = next(agent for agent in student["agents"] if agent["id"] == "testing")
    hidden_case = next(case for case in testing["testResults"] if case.get("visibility") == "hidden")
    hidden_case[forbidden_key] = "leak"
    assert audit_analysis_pair(private, student).student_private_data_leak is True


@pytest.mark.parametrize("forbidden_key", sorted(STUDENT_FORBIDDEN_KEYS - _PUBLIC_TEST_IO_KEYS))
def test_analysis_pair_rejects_forbidden_keys_in_mapping_in_mapping(forbidden_key: str) -> None:
    private, student = _result_pair()
    student["wrapper"] = {"inner": {forbidden_key: "leak"}}
    assert audit_analysis_pair(private, student).student_private_data_leak is True


@pytest.mark.parametrize("forbidden_key", sorted(STUDENT_FORBIDDEN_KEYS))
def test_analysis_pair_rejects_forbidden_keys_in_mapping_in_list(forbidden_key: str) -> None:
    private, student = _result_pair()
    student["items"] = [{"nested": {forbidden_key: "leak"}}]
    assert audit_analysis_pair(private, student).student_private_data_leak is True


def test_analysis_pair_does_not_substring_match_ordinary_student_prose() -> None:
    private, student = _result_pair()
    student["summary"] = (
        "The expected output differs from the actual input; this is a cacheKey concept explanation."
    )
    assert audit_analysis_pair(private, student).student_private_data_leak is False


def test_analysis_pair_rejects_only_explicit_high_entropy_sentinels_in_values() -> None:
    private, student = _result_pair()
    student["summary"] = f"Accidental leak: {PRIVATE_SENTINEL}"
    audit = audit_analysis_pair(private, student, private_sentinels=(PRIVATE_SENTINEL,))
    assert audit.student_private_data_leak is True


def test_pipeline_formal_totals_from_test_agent_output() -> None:
    totals = main._pipeline_formal_totals_from_test_agent({"formalPassed": 3, "formalTotal": 4})
    assert totals == {"formalPassed": 3, "formalTotal": 4}
    assert main._pipeline_formal_totals_from_test_agent({}) == {"formalPassed": 0, "formalTotal": 0}
    assert main._pipeline_formal_totals_from_test_agent({"formalPassed": True, "formalTotal": 2}) == {
        "formalPassed": 0,
        "formalTotal": 2,
    }


def _pipeline_shaped_private_result(*, algorithm_score: int = 45) -> dict[str, object]:
    private = _production_private_result(algorithm_score=algorithm_score)
    alg_output = {
        "detected_algorithms": ["nested_iteration"],
        "data_structures": [],
        "time_complexity": "O(n^2)",
        "space_complexity": "O(1)",
        "expected_complexity": "O(n)",
        "expected_approach": "linear scan",
        "expected_families": ["single_pass"],
        "expected_source": "verified_expectation",
        "expected_confidence": 0.9,
        "expectation_version": 1,
        "complexity_gap": "worse_than_expected",
        "gap_steps": 2,
        "gap_explanation": "Two steps worse than expected.",
        "recommended_approach": "Use a hash map.",
        "evidence": [],
        "issues": [],
        "score": algorithm_score,
        "programmatic_base_score": 90,
        "llm_status": "ok",
        "confidence": 0.9,
        "guardrail_flags": ["algorithm_gap_multi_step_worse"],
    }
    algorithm_agent = next(agent for agent in private["agents"] if agent["id"] == "algorithm")
    algorithm_agent["score"] = algorithm_score
    algorithm_agent["algorithmResult"] = main._algorithm_result_from_output(alg_output)
    algorithm_agent["guardrail_flags"] = ["algorithm_gap_multi_step_worse"]
    diagnostic = next(
        agent for agent in private["agentDiagnostics"]["agents"] if agent["id"] == "algorithm"
    )
    diagnostic["score"] = algorithm_score
    diagnostic["guardrail_flags"] = ["algorithm_gap_multi_step_worse"]
    private["formalPassed"] = 1
    private["formalTotal"] = 2
    return private


def test_analysis_pair_accepts_pipeline_shaped_guardrailed_algorithm() -> None:
    private = _pipeline_shaped_private_result()
    student = project_student_result(copy.deepcopy(private))
    audit = audit_analysis_pair(private, student)
    assert audit.agent_contract_failed is False
    assert audit.formal_authority_overridden is False
    assert audit.algorithm_guardrail_overridden is False


def test_analysis_pair_flags_missing_programmatic_base_score_in_pipeline_projection() -> None:
    private = _pipeline_shaped_private_result()
    algorithm = next(agent for agent in private["agents"] if agent["id"] == "algorithm")
    algorithm["algorithmResult"].pop("programmatic_base_score", None)
    student = project_student_result(copy.deepcopy(private))
    audit = audit_analysis_pair(private, student)
    assert audit.algorithm_guardrail_overridden is True


def test_analysis_pair_allows_null_gap_steps_omitted_by_student_projection() -> None:
    """Student projection drops null gapSteps; that is not an authority override."""
    private = _production_private_result()
    algorithm = next(agent for agent in private["agents"] if agent["id"] == "algorithm")
    algorithm["score"] = 90
    algorithm["algorithmResult"] = _algorithm_result(
        complexity_gap="unknown",
        gap_steps=0,
        programmatic_base_score=90,
    )
    algorithm["algorithmResult"]["gapSteps"] = None
    diagnostic = next(
        agent for agent in private["agentDiagnostics"]["agents"] if agent["id"] == "algorithm"
    )
    diagnostic["score"] = 90
    student = project_student_result(copy.deepcopy(private))
    student_algorithm = next(agent for agent in student["agents"] if agent["id"] == "algorithm")
    assert "gapSteps" not in student_algorithm["algorithmResult"]
    audit = audit_analysis_pair(private, student)
    assert audit.algorithm_guardrail_overridden is False
