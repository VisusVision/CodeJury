from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.algorithm_analysis.contracts import ComplexityEstimate
from backend.testing.contracts import AssignmentDifficulty

ExpectationResolutionStatus = Literal["available", "deterministic_fallback", "unknown"]
ExpectationVerificationStatus = Literal["verified", "rejected"]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AlgorithmExpectationContext(StrictFrozenModel):
    assignment_id: str
    title: str
    description: str
    rubric: tuple[dict, ...]
    difficulty: AssignmentDifficulty


class ExpectationCacheIdentity(StrictFrozenModel):
    cache_key: str


class ExpectationVerification(StrictFrozenModel):
    status: ExpectationVerificationStatus
    provider: str
    model: str
    schema_version: str
    verified_at: str
    reason: str = ""


class AlgorithmExpectation(StrictFrozenModel):
    id: str
    assignment_id: str
    cache_key: str
    version: int = Field(ge=1)
    expected_complexity: ComplexityEstimate | None = None
    expected_approach: str = ""
    algorithm_families: tuple[str, ...] = ()
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    extractor_provider: str
    extractor_model: str
    verifier_provider: str
    verifier_model: str
    schema_version: str
    extractor_prompt_version: str
    verifier_prompt_version: str
    assignment_hash: str = ""
    rubric_hash: str = ""
    verification_status: ExpectationVerificationStatus
    verification_reason: str = ""
    active: bool = True
    created_at: str = ""
    deactivated_at: str | None = None


class AlgorithmExpectationResolution(StrictFrozenModel):
    expectation: AlgorithmExpectation | None = None
    status: ExpectationResolutionStatus
    cache_key: str
    generation_attempts: int = Field(default=0, ge=0, le=2)
