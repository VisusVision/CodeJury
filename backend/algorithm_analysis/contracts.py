from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ComplexityFamily = Literal[
    "single_variable",
    "graph",
    "matrix",
    "recursion",
    "dynamic_programming",
    "backtracking",
    "unknown",
]
ComplexitySource = Literal[
    "python_ast",
    "verified_expectation",
    "deterministic_fallback",
    "llm",
    "unknown",
]
GapStatus = Literal[
    "better_than_expected",
    "matches_expected",
    "worse_than_expected",
    "unknown",
]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _finite_confidence(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("confidence must be finite")
    return value


class ComplexityEstimate(StrictFrozenModel):
    expression: str
    family: ComplexityFamily
    rank: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: ComplexitySource
    evidence_lines: tuple[int, ...] = ()

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        return _finite_confidence(value)


class AlgorithmEvidence(StrictFrozenModel):
    kind: str
    line: int
    detail: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        return _finite_confidence(value)


class AlgorithmDetection(StrictFrozenModel):
    names: tuple[str, ...] = ()
    data_structures: tuple[str, ...] = ()
    evidence: tuple[AlgorithmEvidence, ...] = ()
    time_complexity: ComplexityEstimate | None = None
    space_complexity: ComplexityEstimate | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        return _finite_confidence(value)


class GapResult(StrictFrozenModel):
    status: GapStatus
    steps: int | None = None
    approach_mismatch: bool
    explanation: str
