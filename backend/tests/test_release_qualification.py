from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from backend.ops.release_qualification import (
    REQUIRED_AGENT_IDS,
    REQUIRED_CHECKS,
    Phase4ABrowserEvidence,
    Phase4ACheck,
    Phase4AReleaseLedger,
    audit_analysis_pair,
    safe_ledger_lines,
)


RUN_ID = "phase4a-11111111-1111-4111-8111-111111111111"
PRIVATE_SENTINEL = "TASK5_PRIVATE_SENTINEL_7b0864425d834c9d"


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


def _agent(agent_id: str, *, score: int = 80) -> dict[str, object]:
    agent: dict[str, object] = {
        "id": agent_id,
        "name": agent_id,
        "summary": "ready",
        "score": score,
        "maxScore": 100,
        "findings": [],
    }
    if agent_id == "algorithm":
        agent["algorithmResult"] = {
            "timeComplexity": "O(n)",
            "expectedComplexity": "O(n)",
            "complexityGap": "matches_expected",
            "gapSteps": 0,
        }
    return agent


def _result_pair() -> tuple[dict[str, object], dict[str, object]]:
    diagnostics = [
        {
            "id": agent_id,
            "score": 50 if agent_id == "testing" else 80,
            "llm_status": "ok",
            "confidence": 0.9,
            "guardrail_flags": [],
        }
        for agent_id in sorted(REQUIRED_AGENT_IDS)
    ]
    private_agents = [
        _agent(agent_id, score=50 if agent_id == "testing" else 80)
        for agent_id in sorted(REQUIRED_AGENT_IDS - {"master"})
    ]
    private = {
        "reportStatus": "ready",
        "formalPassed": 1,
        "formalTotal": 2,
        "agents": private_agents,
        "agentDiagnostics": {"agents": diagnostics},
        "privateEvidence": {"expected_stdout": PRIVATE_SENTINEL},
    }
    student = {
        "reportStatus": "ready",
        "formalPassed": 1,
        "formalTotal": 2,
        "summary": "The expected and actual behavior are explained in ordinary prose.",
        "agents": copy.deepcopy(private_agents),
    }
    return private, student


def test_release_ledger_requires_every_gate() -> None:
    with pytest.raises(ValidationError):
        Phase4AReleaseLedger(
            run_id="phase4a-123",
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


def test_browser_evidence_requires_exactly_three_jobs_and_uuid_run_id() -> None:
    common = {
        "assignment_id": "assignment-1",
        "teacher_journey_passed": True,
        "student_journey_passed": True,
        "unauthorized_checks_passed": True,
    }
    with pytest.raises(ValidationError):
        Phase4ABrowserEvidence(run_id="phase4a-not-a-uuid", job_ids=("j1", "j2", "j3"), **common)
    with pytest.raises(ValidationError):
        Phase4ABrowserEvidence(run_id=RUN_ID, job_ids=("j1", "j2"), **common)


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


def test_analysis_pair_requires_all_agents_and_no_student_private_keys() -> None:
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
    ],
)
def test_analysis_pair_flags_incomplete_agent_contract(mutate) -> None:
    private, student = _result_pair()
    mutate(private, student)
    assert audit_analysis_pair(private, student).agent_contract_failed is True


def test_analysis_pair_flags_formal_authority_override() -> None:
    private, student = _result_pair()
    student["formalPassed"] = 2
    audit = audit_analysis_pair(private, student)
    assert audit.formal_authority_overridden is True


def test_analysis_pair_flags_algorithm_score_override() -> None:
    private, student = _result_pair()
    algorithm = next(agent for agent in student["agents"] if agent["id"] == "algorithm")
    algorithm["score"] = 99
    audit = audit_analysis_pair(private, student)
    assert audit.algorithm_guardrail_overridden is True


@pytest.mark.parametrize("forbidden_key", ["expected_stdout", "cacheKey", "fixtures"])
def test_analysis_pair_recursively_rejects_exact_student_private_keys(forbidden_key: str) -> None:
    private, student = _result_pair()
    student["safe"] = [{"nested": {forbidden_key: "leak"}}]
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
