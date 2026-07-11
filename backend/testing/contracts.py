from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AssignmentDifficulty = Literal["easy", "medium", "hard"]
DifficultySource = Literal["default", "teacher", "ai_selected", "inferred"]
TestSource = Literal["manual", "ai_approved", "auto_generated"]
OracleSource = Literal["teacher", "llm_verified"]
TestEvidenceStatus = Literal["available", "unavailable"]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TestFixture(StrictFrozenModel):
    name: str
    content: str


class OracleValidation(StrictFrozenModel):
    status: Literal["verified", "rejected"]
    provider: str
    model: str
    schema_version: str
    verified_at: str
    reason: str = ""


class FormalTestCase(StrictFrozenModel):
    id: str
    name: str
    stdin: str = ""
    expected_stdout: str = ""
    expected_exit_code: int = 0
    visibility: Literal["public", "hidden"] = "hidden"
    files: tuple[TestFixture, ...] = ()
    source: TestSource
    oracle: OracleSource
    oracle_validation: OracleValidation | None = None


class GeneratedTestSet(StrictFrozenModel):
    id: str
    assignment_id: str
    cache_key: str
    version: int = Field(ge=1)
    difficulty: AssignmentDifficulty
    cases: tuple[FormalTestCase, ...]
    provider: str
    model: str
    schema_version: str
    prompt_version: str
    assignment_hash: str = ""
    rubric_hash: str = ""
    oracle_validation: tuple[OracleValidation, ...] = ()
    active: bool = True
    created_at: str = ""
    deactivated_at: str | None = None


class TestSelection(StrictFrozenModel):
    cases: tuple[FormalTestCase, ...]
    source: Literal["faculty", "auto_generated", "none"]
    test_set_id: str | None = None
    cache_key: str | None = None
    cache_version: int | None = None
    test_evidence_status: TestEvidenceStatus
    generation_attempts: int = Field(default=0, ge=0, le=2)


class EvaluatedTestCase(StrictFrozenModel):
    id: str
    name: str
    visibility: Literal["public", "hidden"]
    status: Literal["pass", "fail", "error"]
    passed: bool
    stdin: str
    expected_stdout: str
    actual_stdout: str
    actual_stderr: str
    expected_exit_code: int
    actual_exit_code: int
    error_type: str | None = None
    error_message_tr: str | None = None
    source: TestSource
    oracle: OracleSource
    files: tuple[TestFixture, ...] = ()
    wall_time_ms: float = 0.0
    peak_memory_mb: float = 0.0


class RawCaseResult(StrictFrozenModel):
    id: str
    actual_stdout: str = ""
    actual_stderr: str = ""
    actual_exit_code: int = -1
    timed_out: bool = False
    memory_exceeded: bool = False
    compile_success: bool = False
    wall_time_ms: float = 0.0
    peak_memory_mb: float = 0.0
    container_passed: bool | None = None
