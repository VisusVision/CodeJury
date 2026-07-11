"""Tests for AlgorithmAgent deterministic score guardrail."""

from __future__ import annotations

from backend.algorithm_analysis.contracts import AlgorithmEvidence, GapResult
from backend.algorithm_analysis.scoring import apply_algorithm_score_guardrail


def _gap(
    *,
    status: str,
    steps: int | None = 0,
    approach_mismatch: bool = False,
) -> GapResult:
    return GapResult(
        status=status,  # type: ignore[arg-type]
        steps=steps if steps is not None else 0,
        approach_mismatch=approach_mismatch,
        explanation="test gap",
    )


def test_matches_expected_no_gap_penalty() -> None:
    decision = apply_algorithm_score_guardrail(
        90,
        95,
        _gap(status="matches_expected"),
        (),
    )
    assert decision.score == 95
    assert decision.cap == 100
    assert decision.deduction == 0
    assert "algorithm_gap_penalty" not in decision.guardrail_flags


def test_better_than_expected_no_gap_penalty() -> None:
    decision = apply_algorithm_score_guardrail(
        88,
        85,
        _gap(status="better_than_expected", steps=1),
        (),
    )
    assert decision.score == 85
    assert decision.cap == 100
    assert decision.deduction == 3


def test_one_step_worse_caps_at_65_and_deducts_at_least_20() -> None:
    gap = GapResult(
        status="worse_than_expected",
        steps=1,
        approach_mismatch=False,
        explanation="one step worse",
    )
    decision = apply_algorithm_score_guardrail(90, 100, gap, ())
    assert decision.cap == 65
    assert decision.score == 65
    assert decision.deduction >= 20
    assert "algorithm_gap_one_step_worse" in decision.guardrail_flags


def test_two_plus_steps_worse_caps_at_45_and_deducts_at_least_35() -> None:
    gap = GapResult(
        status="worse_than_expected",
        steps=2,
        approach_mismatch=True,
        explanation="two steps worse",
    )
    decision = apply_algorithm_score_guardrail(90, 100, gap, ())
    assert decision.cap == 45
    assert decision.score == 45
    assert decision.deduction >= 35
    assert "algorithm_gap_multi_step_worse" in decision.guardrail_flags


def test_approach_mismatch_same_big_o_caps_at_70() -> None:
    gap = GapResult(
        status="matches_expected",
        steps=0,
        approach_mismatch=True,
        explanation="approach mismatch",
    )
    decision = apply_algorithm_score_guardrail(90, 100, gap, ())
    assert decision.cap == 70
    assert decision.score == 70
    assert decision.deduction >= 15
    assert "algorithm_approach_mismatch" in decision.guardrail_flags


def test_unknown_expectation_no_gap_penalty() -> None:
    gap = GapResult(
        status="unknown",
        steps=None,
        approach_mismatch=False,
        explanation="unknown gap",
    )
    decision = apply_algorithm_score_guardrail(85, 100, gap, ())
    assert decision.cap == 100
    assert decision.score == 85
    assert decision.deduction == 0
    assert "algorithm_gap_penalty" not in decision.guardrail_flags


def test_nested_loop_evidence_penalty_independent_of_gap() -> None:
    gap = GapResult(
        status="matches_expected",
        steps=0,
        approach_mismatch=False,
        explanation="ok",
    )
    evidence = (
        AlgorithmEvidence(
            kind="nested_loop",
            line=4,
            detail="loop depth 2",
            confidence=0.9,
        ),
    )
    decision = apply_algorithm_score_guardrail(90, 95, gap, evidence)
    assert decision.score == 80
    assert decision.deduction == 10
    assert "algorithm_evidence_nested_loop_penalty" in decision.guardrail_flags


def test_llm_score_cannot_exceed_deterministic_cap() -> None:
    gap = GapResult(
        status="worse_than_expected",
        steps=1,
        approach_mismatch=False,
        explanation="one step",
    )
    decision = apply_algorithm_score_guardrail(90, 100, gap, ())
    assert decision.score == 65
    assert "algorithm_llm_score_capped" in decision.guardrail_flags


def test_programmatic_base_recorded() -> None:
    decision = apply_algorithm_score_guardrail(77, 60, _gap(status="matches_expected"), ())
    assert decision.programmatic_base == 77
    assert decision.score == 60
