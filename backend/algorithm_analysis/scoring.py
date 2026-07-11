from __future__ import annotations

from backend.algorithm_analysis.contracts import (
    AlgorithmEvidence,
    GapResult,
    StrictFrozenModel,
)

_EVIDENCE_CONFIDENCE_FLOOR = 0.75
_NESTED_LOOP_PENALTY = 10
_EXPONENTIAL_RECURSION_PENALTY = 10


class AlgorithmScoreDecision(StrictFrozenModel):
    score: int
    programmatic_base: int
    cap: int
    deduction: int
    guardrail_flags: tuple[str, ...] = ()


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


def _evidence_deduction(evidence: tuple[AlgorithmEvidence, ...]) -> tuple[int, tuple[str, ...]]:
    deduction = 0
    flags: list[str] = []
    proven_nested = any(
        item.kind == "nested_loop" and item.confidence >= _EVIDENCE_CONFIDENCE_FLOOR
        for item in evidence
    )
    proven_exponential = any(
        item.kind == "branching_recursion" and item.confidence >= _EVIDENCE_CONFIDENCE_FLOOR
        for item in evidence
    )
    if proven_nested:
        deduction += _NESTED_LOOP_PENALTY
        flags.append("algorithm_evidence_nested_loop_penalty")
    if proven_exponential:
        deduction += _EXPONENTIAL_RECURSION_PENALTY
        flags.append("algorithm_evidence_exponential_recursion_penalty")
    return deduction, tuple(flags)


def _gap_rules(gap: GapResult) -> tuple[int, int, tuple[str, ...]]:
    if gap.status in {"matches_expected", "better_than_expected", "unknown"}:
        if gap.status == "matches_expected" and gap.approach_mismatch:
            return 70, 15, ("algorithm_approach_mismatch",)
        return 100, 0, ()

    steps = gap.steps or 0
    if steps >= 2:
        return 45, 35, ("algorithm_gap_multi_step_worse",)
    return 65, 20, ("algorithm_gap_one_step_worse",)


def apply_algorithm_score_guardrail(
    base_score: int,
    llm_score: int,
    gap: GapResult,
    evidence: tuple[AlgorithmEvidence, ...],
) -> AlgorithmScoreDecision:
    programmatic_base = _clamp_score(base_score)
    llm_candidate = _clamp_score(llm_score)
    evidence_deduction, evidence_flags = _evidence_deduction(evidence)
    gap_cap, gap_min_deduction, gap_flags = _gap_rules(gap)

    cap = min(100, gap_cap)
    adjusted_base = _clamp_score(programmatic_base - evidence_deduction)
    score = min(llm_candidate, cap)
    if gap.status == "unknown":
        score = min(score, programmatic_base)
    if evidence_deduction > 0:
        score = min(score, adjusted_base)
    if gap_min_deduction > 0:
        score = min(score, _clamp_score(adjusted_base - gap_min_deduction))

    flags: list[str] = list(gap_flags) + list(evidence_flags)
    if llm_candidate > score:
        flags.append("algorithm_llm_score_capped")
    if gap_min_deduction > 0:
        flags.append("algorithm_gap_penalty")

    return AlgorithmScoreDecision(
        score=score,
        programmatic_base=programmatic_base,
        cap=cap,
        deduction=max(0, programmatic_base - score),
        guardrail_flags=tuple(dict.fromkeys(flags)),
    )
