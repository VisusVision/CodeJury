"""Contract tests for backend.testing domain models (RED phase)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.testing.contracts import (
    EvaluatedTestCase,
    FormalTestCase,
    GeneratedTestSet,
    TestFixture,
    TestSelection,
)


def test_formal_case_rejects_unknown_visibility() -> None:
    with pytest.raises(ValidationError):
        FormalTestCase(
            id="case-1",
            name="edge",
            stdin="0\n",
            expected_stdout="0\n",
            visibility="secret",
            source="manual",
            oracle="teacher",
        )


def test_generated_set_is_frozen() -> None:
    generated = GeneratedTestSet(
        id="set-1",
        assignment_id="assignment-1",
        cache_key="a" * 64,
        version=1,
        difficulty="medium",
        cases=(),
        provider="ollama",
        model="qwen2.5:7b",
        schema_version="test-set-v1",
        prompt_version="test-prompt-v1",
    )
    with pytest.raises(ValidationError):
        generated.version = 2
    assert isinstance(generated.cases, tuple)
    with pytest.raises(AttributeError):
        generated.cases.append(None)  # type: ignore[attr-defined]


def test_formal_case_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        FormalTestCase(
            id="case-1",
            name="edge",
            stdin="",
            expected_stdout="",
            visibility="public",
            source="not_a_real_source",
            oracle="teacher",
        )


def test_formal_case_rejects_unknown_oracle() -> None:
    with pytest.raises(ValidationError):
        FormalTestCase(
            id="case-1",
            name="edge",
            stdin="",
            expected_stdout="",
            visibility="public",
            source="manual",
            oracle="not_a_real_oracle",
        )


def test_formal_case_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        FormalTestCase(
            id="case-1",
            name="edge",
            stdin="",
            expected_stdout="",
            visibility="public",
            source="manual",
            oracle="teacher",
            extra_field="x",
        )


def test_generated_test_set_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        GeneratedTestSet(
            id="set-1",
            assignment_id="assignment-1",
            cache_key="a" * 64,
            version=1,
            difficulty="medium",
            cases=(),
            provider="ollama",
            model="qwen2.5:7b",
            schema_version="test-set-v1",
            prompt_version="test-prompt-v1",
            extra_field="x",
        )


def test_test_selection_generation_attempts_bounds() -> None:
    with pytest.raises(ValidationError):
        TestSelection(
            cases=(),
            source="none",
            test_evidence_status="unavailable",
            generation_attempts=3,
        )
    with pytest.raises(ValidationError):
        TestSelection(
            cases=(),
            source="none",
            test_evidence_status="unavailable",
            generation_attempts=-1,
        )


def test_evaluated_test_case_status_enum() -> None:
    with pytest.raises(ValidationError):
        EvaluatedTestCase(
            id="case-1",
            name="edge",
            visibility="public",
            status="bogus",
            passed=False,
            stdin="",
            expected_stdout="",
            actual_stdout="",
            actual_stderr="",
            expected_exit_code=0,
            actual_exit_code=0,
            source="manual",
            oracle="teacher",
        )


def test_test_fixture_round_trip() -> None:
    fixture = TestFixture(name="data/input.csv", content="1,2\n")
    assert fixture.name == "data/input.csv"
    assert fixture.content == "1,2\n"
    with pytest.raises(ValidationError):
        fixture.content = "x"
