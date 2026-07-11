from __future__ import annotations

import re

from backend.algorithm_analysis.contracts import (
    ComplexityEstimate,
    ComplexityFamily,
    ComplexitySource,
)

SINGLE_VARIABLE_ORDER = (
    "O(1)",
    "O(log n)",
    "O(n)",
    "O(n log n)",
    "O(n^2)",
    "O(n^3)",
    "O(2^n)",
    "O(n!)",
)
GRAPH_ORDER = ("O(V+E)", "O((V+E) log V)", "O(V^2)", "O(2^V)")
MATRIX_ORDER = ("O(rc)", "O(rc log(rc))", "O(r^2c^2)")

_FAMILY_REGISTRIES: tuple[tuple[ComplexityFamily, tuple[str, ...]], ...] = (
    ("single_variable", SINGLE_VARIABLE_ORDER),
    ("graph", GRAPH_ORDER),
    ("matrix", MATRIX_ORDER),
)


def _canonicalize(raw: str) -> str:
    text = raw.strip()
    text = text.replace("²", "^2").replace("³", "^3")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s*\+\s*", "+", text)
    text = re.sub(r"\s*\^\s*", "^", text)
    if text.lower().startswith("o("):
        text = "O(" + text[2:]
    return text


def _lookup(normalized: str) -> tuple[ComplexityFamily, str, int] | None:
    lowered = normalized.lower()
    for family, order in _FAMILY_REGISTRIES:
        for rank, canonical in enumerate(order):
            if lowered == canonical.lower():
                return family, canonical, rank
    return None


def normalize_complexity(
    raw: str,
    *,
    source: ComplexitySource,
    confidence: float,
    evidence_lines: tuple[int, ...] = (),
) -> ComplexityEstimate:
    normalized = _canonicalize(raw)
    match = _lookup(normalized)
    if match is None:
        return ComplexityEstimate(
            expression=normalized,
            family="unknown",
            rank=None,
            confidence=confidence,
            source=source,
            evidence_lines=evidence_lines,
        )
    family, expression, rank = match
    return ComplexityEstimate(
        expression=expression,
        family=family,
        rank=rank,
        confidence=confidence,
        source=source,
        evidence_lines=evidence_lines,
    )


def safe_rank_distance(
    actual: ComplexityEstimate,
    expected: ComplexityEstimate,
) -> int | None:
    if actual.family != expected.family:
        return None
    if actual.rank is None or expected.rank is None:
        return None
    return abs(actual.rank - expected.rank)
