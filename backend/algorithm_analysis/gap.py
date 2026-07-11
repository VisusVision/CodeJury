from __future__ import annotations

from backend.algorithm_analysis.complexity import safe_rank_distance
from backend.algorithm_analysis.contracts import ComplexityEstimate, GapResult, GapStatus


def _approach_mismatch(
    actual_approaches: tuple[str, ...],
    expected_approaches: tuple[str, ...],
) -> bool:
    if not expected_approaches:
        return False
    if not actual_approaches:
        return True
    actual = {item.strip().lower() for item in actual_approaches if item.strip()}
    expected = {item.strip().lower() for item in expected_approaches if item.strip()}
    return expected.isdisjoint(actual)


def _status_from_ranks(
    actual: ComplexityEstimate,
    expected: ComplexityEstimate,
) -> GapStatus | None:
    if actual.rank is None or expected.rank is None:
        return None
    if actual.rank > expected.rank:
        return "worse_than_expected"
    if actual.rank < expected.rank:
        return "better_than_expected"
    return "matches_expected"


def _explain(
    *,
    status: GapStatus,
    actual: ComplexityEstimate,
    expected: ComplexityEstimate,
    steps: int | None,
    approach_mismatch: bool,
) -> str:
    if status == "unknown":
        return (
            f"Complexity gap unknown: actual {actual.expression} and expected "
            f"{expected.expression} are not safely comparable."
        )
    if status == "better_than_expected":
        return (
            f"Actual complexity {actual.expression} is better than expected "
            f"{expected.expression}."
        )
    if status == "worse_than_expected":
        detail = (
            f"Actual complexity {actual.expression} is {steps} step(s) worse than "
            f"expected {expected.expression}."
        )
        if approach_mismatch:
            detail += " Required approach was not used."
        return detail
    if approach_mismatch:
        return (
            f"Actual complexity {actual.expression} matches expected "
            f"{expected.expression}, but the required approach was not used."
        )
    return (
        f"Actual complexity {actual.expression} matches expected "
        f"{expected.expression}."
    )


def compare_expected_actual(
    actual: ComplexityEstimate,
    expected: ComplexityEstimate,
    *,
    actual_approaches: tuple[str, ...] = (),
    expected_approaches: tuple[str, ...] = (),
) -> GapResult:
    distance = safe_rank_distance(actual, expected)
    approach_mismatch = _approach_mismatch(actual_approaches, expected_approaches)
    status = _status_from_ranks(actual, expected)
    if distance is None or status is None:
        return GapResult(
            status="unknown",
            steps=None,
            approach_mismatch=False,
            explanation=_explain(
                status="unknown",
                actual=actual,
                expected=expected,
                steps=None,
                approach_mismatch=False,
            ),
        )

    if status == "worse_than_expected":
        steps: int | None = distance
    elif status == "better_than_expected":
        steps = distance
    else:
        steps = 0

    return GapResult(
        status=status,
        steps=steps,
        approach_mismatch=approach_mismatch,
        explanation=_explain(
            status=status,
            actual=actual,
            expected=expected,
            steps=steps,
            approach_mismatch=approach_mismatch,
        ),
    )
