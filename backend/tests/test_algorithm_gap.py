"""Tests for family-safe complexity gap comparison."""

from __future__ import annotations

from backend.algorithm_analysis.complexity import normalize_complexity
from backend.algorithm_analysis.gap import compare_expected_actual


def _estimate(expression: str) -> object:
    return normalize_complexity(expression, source="python_ast", confidence=0.9)


def test_single_variable_one_step_worse() -> None:
    gap = compare_expected_actual(
        _estimate("O(n log n)"),
        _estimate("O(n)"),
        actual_approaches=("sorting",),
        expected_approaches=("hash_lookup",),
    )
    assert gap.status == "worse_than_expected"
    assert gap.steps == 1
    assert gap.approach_mismatch is True


def test_graph_family_two_steps_worse() -> None:
    gap = compare_expected_actual(
        _estimate("O(V^2)"),
        _estimate("O(V+E)"),
        actual_approaches=(),
        expected_approaches=(),
    )
    assert gap.status == "worse_than_expected"
    assert gap.steps == 2
    assert gap.approach_mismatch is False


def test_matrix_family_two_steps_worse() -> None:
    gap = compare_expected_actual(
        _estimate("O(r^2c^2)"),
        _estimate("O(rc)"),
        actual_approaches=(),
        expected_approaches=(),
    )
    assert gap.status == "worse_than_expected"
    assert gap.steps == 2


def test_cross_family_returns_unknown() -> None:
    gap = compare_expected_actual(
        _estimate("O(n)"),
        _estimate("O(V+E)"),
        actual_approaches=(),
        expected_approaches=(),
    )
    assert gap.status == "unknown"
    assert gap.steps is None
    assert gap.approach_mismatch is False


def test_unknown_expression_returns_unknown_gap() -> None:
    gap = compare_expected_actual(
        normalize_complexity("O(x+y+z)", source="llm", confidence=0.7),
        _estimate("O(n)"),
        actual_approaches=(),
        expected_approaches=(),
    )
    assert gap.status == "unknown"
    assert gap.steps is None


def test_two_sum_hash_vs_nested_loop() -> None:
    gap = compare_expected_actual(
        _estimate("O(n^2)"),
        _estimate("O(n)"),
        actual_approaches=("brute_force_nested_scan", "nested_loop"),
        expected_approaches=("hash_lookup",),
    )
    assert gap.status == "worse_than_expected"
    assert gap.steps == 2
    assert gap.approach_mismatch is True
    assert "approach" in gap.explanation.lower()


def test_equal_big_o_approach_mismatch() -> None:
    gap = compare_expected_actual(
        _estimate("O(n)"),
        _estimate("O(n)"),
        actual_approaches=("brute_force_nested_scan",),
        expected_approaches=("hash_lookup",),
    )
    assert gap.status == "matches_expected"
    assert gap.steps == 0
    assert gap.approach_mismatch is True


def test_matches_expected_no_mismatch() -> None:
    gap = compare_expected_actual(
        _estimate("O(n)"),
        _estimate("O(n)"),
        actual_approaches=("hash_lookup",),
        expected_approaches=("hash_lookup",),
    )
    assert gap.status == "matches_expected"
    assert gap.approach_mismatch is False


def test_better_than_expected() -> None:
    gap = compare_expected_actual(
        _estimate("O(n)"),
        _estimate("O(n^2)"),
        actual_approaches=(),
        expected_approaches=(),
    )
    assert gap.status == "better_than_expected"
    assert gap.steps == 2
