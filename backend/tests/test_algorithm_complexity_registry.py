"""RED-phase tests for algorithm complexity contracts and family-safe registry."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.algorithm_analysis.complexity import (
    GRAPH_ORDER,
    MATRIX_ORDER,
    SINGLE_VARIABLE_ORDER,
    normalize_complexity,
    safe_rank_distance,
)
from backend.algorithm_analysis.contracts import (
    AlgorithmDetection,
    AlgorithmEvidence,
    ComplexityEstimate,
    GapResult,
)


def test_unknown_multivariate_expression_has_no_rank() -> None:
    estimate = normalize_complexity("O(x+y+z)", source="llm", confidence=0.7)
    assert estimate.family == "unknown"
    assert estimate.rank is None


def test_graph_family_has_safe_order() -> None:
    expected = normalize_complexity("O(V+E)", source="verified_expectation", confidence=1.0)
    actual = normalize_complexity("O(V^2)", source="python_ast", confidence=0.9)
    assert safe_rank_distance(actual, expected) == 2


def test_single_variable_alias_superscript_normalizes_to_caret_form() -> None:
    superscript = normalize_complexity("O(n²)", source="python_ast", confidence=0.9)
    caret = normalize_complexity("O(n^2)", source="python_ast", confidence=0.9)
    assert superscript.expression == caret.expression
    assert superscript.family == "single_variable"
    assert caret.family == "single_variable"
    assert superscript.rank == caret.rank


def test_whitespace_and_case_normalization() -> None:
    estimate = normalize_complexity("  o( N )  ", source="python_ast", confidence=0.8)
    assert estimate.expression == "O(n)"
    assert estimate.family == "single_variable"
    assert estimate.rank == 2


def test_matrix_family_has_safe_order() -> None:
    expected = normalize_complexity("O(rc)", source="verified_expectation", confidence=1.0)
    actual = normalize_complexity("O(r^2c^2)", source="python_ast", confidence=0.9)
    assert expected.family == "matrix"
    assert actual.family == "matrix"
    assert safe_rank_distance(actual, expected) == 2


def test_cross_family_rank_distance_returns_none() -> None:
    single_var = normalize_complexity("O(n)", source="python_ast", confidence=0.9)
    graph = normalize_complexity("O(V+E)", source="verified_expectation", confidence=1.0)
    assert safe_rank_distance(single_var, graph) is None
    assert safe_rank_distance(graph, single_var) is None


def test_unknown_family_rank_distance_returns_none() -> None:
    known = normalize_complexity("O(n)", source="python_ast", confidence=0.9)
    unknown = normalize_complexity("O(x+y+z)", source="llm", confidence=0.7)
    assert safe_rank_distance(known, unknown) is None
    assert safe_rank_distance(unknown, known) is None


def test_normalize_complexity_preserves_immutable_tuple_evidence() -> None:
    estimate = normalize_complexity(
        "O(n)",
        source="python_ast",
        confidence=0.9,
        evidence_lines=(3, 9, 12),
    )
    assert estimate.evidence_lines == (3, 9, 12)
    assert isinstance(estimate.evidence_lines, tuple)


def test_complexity_estimate_rejects_non_finite_confidence() -> None:
    with pytest.raises(ValidationError):
        ComplexityEstimate(
            expression="O(n)",
            family="single_variable",
            rank=2,
            confidence=float("inf"),
            source="python_ast",
        )
    with pytest.raises(ValidationError):
        ComplexityEstimate(
            expression="O(n)",
            family="single_variable",
            rank=2,
            confidence=math.nan,
            source="python_ast",
        )


def test_normalize_complexity_rejects_non_finite_confidence() -> None:
    with pytest.raises(ValidationError):
        normalize_complexity("O(n)", source="llm", confidence=float("inf"))
    with pytest.raises(ValidationError):
        normalize_complexity("O(n)", source="llm", confidence=math.nan)


def test_complexity_estimate_is_frozen_and_rejects_extra_fields() -> None:
    estimate = ComplexityEstimate(
        expression="O(n)",
        family="single_variable",
        rank=2,
        confidence=0.9,
        source="python_ast",
        evidence_lines=(1,),
    )
    with pytest.raises(ValidationError):
        estimate.expression = "O(n^2)"
    with pytest.raises(ValidationError):
        ComplexityEstimate(
            expression="O(n)",
            family="single_variable",
            rank=2,
            confidence=0.9,
            source="python_ast",
            unexpected="x",
        )


def test_algorithm_evidence_is_frozen_and_rejects_extra_fields() -> None:
    evidence = AlgorithmEvidence(kind="loop", line=4, detail="nested scan", confidence=0.85)
    with pytest.raises(ValidationError):
        evidence.line = 5
    with pytest.raises(ValidationError):
        AlgorithmEvidence(
            kind="loop",
            line=4,
            detail="nested scan",
            confidence=0.85,
            unexpected="x",
        )


def test_gap_result_is_frozen_and_rejects_extra_fields() -> None:
    gap = GapResult(
        status="worse_than_expected",
        steps=2,
        approach_mismatch=True,
        explanation="Nested loop instead of hash lookup.",
    )
    with pytest.raises(ValidationError):
        gap.steps = 1
    with pytest.raises(ValidationError):
        GapResult(
            status="worse_than_expected",
            steps=2,
            approach_mismatch=True,
            explanation="Nested loop instead of hash lookup.",
            unexpected="x",
        )


def test_algorithm_detection_is_frozen_model() -> None:
    assert issubclass(AlgorithmDetection, ComplexityEstimate.__bases__[0])


def test_registry_orders_are_explicit_tuples() -> None:
    assert SINGLE_VARIABLE_ORDER == (
        "O(1)",
        "O(log n)",
        "O(n)",
        "O(n log n)",
        "O(n^2)",
        "O(n^3)",
        "O(2^n)",
        "O(n!)",
    )
    assert GRAPH_ORDER == ("O(V+E)", "O((V+E) log V)", "O(V^2)", "O(2^V)")
    assert MATRIX_ORDER == ("O(rc)", "O(rc log(rc))", "O(r^2c^2)")
