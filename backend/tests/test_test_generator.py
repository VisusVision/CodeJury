"""RED-phase tests for LLM test-case generator and independent oracle verifier."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from backend.core.config import settings
from backend.llm.ollama_client import ChatJsonResult
from backend.testing.cache import AssignmentTestContext
from backend.testing.contracts import FormalTestCase
from backend.testing.fixture_policy import MAX_CASE_BYTES, MAX_FILE_BYTES, MAX_FILES_PER_CASE
from backend.testing.generator import (
    GenerationAttemptResult,
    build_generator_prompt,
    generate_and_verify_once,
)
from backend.testing.difficulty import TARGETS

STUDENT_CODE_SENTINEL = "STUDENT_CODE_SENTINEL_9f3a"

ChatSpy = Callable[..., Awaitable[ChatJsonResult]]


def _context(**overrides: Any) -> AssignmentTestContext:
    base = {
        "assignment_id": "assignment-1",
        "title": "Square a Number",
        "description": "Read an integer and print its square.",
        "rubric": [{"name": "Correctness", "max_score": 100}],
        "difficulty": "easy",
    }
    base.update(overrides)
    return AssignmentTestContext(**base)


def _case(
    *,
    name: str,
    stdin: str = "3\n",
    expected_stdout: str = "9\n",
    visibility: str = "public",
    files: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "stdin": stdin,
        "expected_stdout": expected_stdout,
        "expected_exit_code": 0,
        "visibility": visibility,
        "files": files or [],
    }


def _verify(
    case_id: str,
    *,
    verified: bool = True,
    deterministic: bool = True,
    assignment_aligned: bool = True,
    reason: str = "ok",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "verified": verified,
        "deterministic": deterministic,
        "assignment_aligned": assignment_aligned,
        "reason": reason,
    }


def _make_spy(
    generator_cases: list[dict[str, Any]],
    verifier_decisions: dict[str, dict[str, Any]] | None = None,
) -> ChatSpy:
    verifier_decisions = verifier_decisions or {}
    call_index = {"n": 0}

    async def spy_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del system_prompt, user_prompt, kwargs
        if call_index["n"] == 0:
            call_index["n"] += 1
            return ChatJsonResult(
                data={"cases": generator_cases},
                provider="test",
                model="test-model",
                fallback_used=False,
            )
        case_id = str(call_index["n"] - 1)
        call_index["n"] += 1
        decision = verifier_decisions.get(case_id, _verify(case_id))
        return ChatJsonResult(
            data=decision,
            provider="test",
            model="test-model",
            fallback_used=False,
        )

    return spy_chat


@pytest.mark.asyncio
async def test_generator_and_verifier_prompts_never_contain_student_code_sentinel() -> None:
    captured: list[str] = []
    call_index = {"n": 0}

    async def spy_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del kwargs
        captured.append(system_prompt)
        captured.append(user_prompt)
        call_index["n"] += 1
        if call_index["n"] == 1:
            return ChatJsonResult(
                data={"cases": [_case(name="square")]},
                provider="test",
                model="test-model",
                fallback_used=False,
            )
        return ChatJsonResult(
            data=_verify("0"),
            provider="test",
            model="test-model",
            fallback_used=False,
        )

    context = _context()
    signature = inspect.signature(generate_and_verify_once)
    assert "source_code" not in signature.parameters
    assert "stdout" not in signature.parameters
    assert "stderr" not in signature.parameters
    assert "student_id" not in signature.parameters

    result = await generate_and_verify_once(context, chat=spy_chat)

    assert result.cases
    assert all(STUDENT_CODE_SENTINEL not in prompt for prompt in captured)
    joined_prompts = "\n".join(captured)
    assert context.title in joined_prompts
    assert context.description in joined_prompts
    assert context.rubric[0]["name"] in joined_prompts


@pytest.mark.asyncio
async def test_verification_gate_accepts_generator_verifier_agreement() -> None:
    generator_cases = [
        _case(name="square-three", stdin="3\n", expected_stdout="9\n"),
        _case(name="square-zero", stdin="0\n", expected_stdout="0\n", visibility="hidden"),
    ]
    result = await generate_and_verify_once(
        _context(),
        chat=_make_spy(generator_cases),
    )

    assert isinstance(result, GenerationAttemptResult)
    assert len(result.cases) == 2
    assert all(isinstance(case, FormalTestCase) for case in result.cases)
    assert all(case.source == "auto_generated" for case in result.cases)
    assert all(case.oracle == "llm_verified" for case in result.cases)
    assert all(
        case.oracle_validation is not None and case.oracle_validation.status == "verified"
        for case in result.cases
    )


@pytest.mark.asyncio
async def test_verification_gate_drops_only_rejected_case() -> None:
    generator_cases = [
        _case(name="approved", stdin="1\n", expected_stdout="1\n"),
        _case(name="rejected", stdin="2\n", expected_stdout="4\n", visibility="hidden"),
    ]
    result = await generate_and_verify_once(
        _context(),
        chat=_make_spy(
            generator_cases,
            verifier_decisions={
                "0": _verify("0"),
                "1": _verify("1", verified=False, reason="nondeterministic"),
            },
        ),
    )

    assert len(result.cases) == 1
    assert result.cases[0].name == "approved"
    assert len(result.rejected) == 1


@pytest.mark.asyncio
async def test_verification_gate_drops_duplicate_cases() -> None:
    generator_cases = [
        _case(name="dup-a", stdin="1\n", expected_stdout="1\n"),
        _case(name="dup-b", stdin="1\n", expected_stdout="1\n"),
    ]
    result = await generate_and_verify_once(
        _context(),
        chat=_make_spy(generator_cases),
    )

    assert len(result.cases) == 1


@pytest.mark.asyncio
async def test_verification_gate_allows_explicit_empty_expected_output() -> None:
    generator_cases = [
        _case(name="silent-run", stdin="", expected_stdout="", visibility="hidden"),
    ]
    result = await generate_and_verify_once(
        _context(),
        chat=_make_spy(generator_cases),
    )

    assert len(result.cases) == 1
    assert result.cases[0].expected_stdout == ""


@pytest.mark.asyncio
async def test_verification_gate_rejects_unsafe_fixture_case() -> None:
    generator_cases = [
        _case(name="safe", stdin="1\n", expected_stdout="1\n"),
        _case(
            name="unsafe",
            stdin="2\n",
            expected_stdout="2\n",
            files=[{"name": "../evil.txt", "content": "bad"}],
        ),
    ]
    result = await generate_and_verify_once(
        _context(),
        chat=_make_spy(generator_cases),
    )

    assert len(result.cases) == 1
    assert result.cases[0].name == "safe"
    assert len(result.rejected) == 1


@pytest.mark.asyncio
async def test_wrong_counts_does_not_fabricate_cases() -> None:
    generator_cases = [_case(name="only-one", stdin="5\n", expected_stdout="25\n")]
    result = await generate_and_verify_once(
        _context(difficulty="hard"),
        chat=_make_spy(generator_cases),
    )

    assert len(result.cases) == 1
    assert result.cases[0].name == "only-one"


@pytest.mark.asyncio
async def test_chat_json_none_produces_empty_failed_attempt_not_exception() -> None:
    async def spy_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del system_prompt, user_prompt, kwargs
        return ChatJsonResult(
            data=None,
            provider="test",
            model="test-model",
            fallback_used=False,
            error="timeout",
        )

    result = await generate_and_verify_once(_context(), chat=spy_chat)

    assert isinstance(result, GenerationAttemptResult)
    assert result.cases == ()
    assert result.provider == "test"
    assert result.model == "test-model"
    assert result.success is False


def test_generator_prompt_includes_targets_and_fixture_limits() -> None:
    context = _context(difficulty="medium")
    prompt = build_generator_prompt(context)
    policy = TARGETS["medium"]
    assert f"Target verified case count: {policy['target']}" in prompt
    assert f"Minimum verified case count: {policy['minimum']}" in prompt
    assert f"Required public case count: {policy['public']}" in prompt
    assert str(MAX_FILES_PER_CASE) in prompt
    assert str(MAX_FILE_BYTES) in prompt
    assert str(MAX_CASE_BYTES) in prompt


@pytest.mark.asyncio
async def test_oracle_validation_uses_verifier_provider_not_generator() -> None:
    call_index = {"n": 0}

    async def spy_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del system_prompt, user_prompt, kwargs
        if call_index["n"] == 0:
            call_index["n"] += 1
            return ChatJsonResult(
                data={"cases": [_case(name="square")]},
                provider="generator-provider",
                model="generator-model",
                fallback_used=False,
            )
        call_index["n"] += 1
        return ChatJsonResult(
            data=_verify("0"),
            provider="verifier-provider",
            model="verifier-model",
            fallback_used=False,
        )

    result = await generate_and_verify_once(_context(), chat=spy_chat)

    assert len(result.cases) == 1
    validation = result.cases[0].oracle_validation
    assert validation is not None
    assert validation.provider == "verifier-provider"
    assert validation.model == "verifier-model"
    assert result.provider == "generator-provider"
    assert result.model == "generator-model"


@pytest.mark.asyncio
async def test_verifier_case_id_mismatch_is_rejected() -> None:
    mismatch = _verify("0")
    mismatch["case_id"] = "999"
    result = await generate_and_verify_once(
        _context(),
        chat=_make_spy([_case(name="square")], verifier_decisions={"0": mismatch}),
    )

    assert result.cases == ()
    assert len(result.rejected) == 1
    assert result.rejected[0]["reason"] == "verifier_case_id_mismatch"


@pytest.mark.asyncio
async def test_chat_calls_use_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "test_generation_call_timeout_seconds", 0.05)

    async def slow_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del system_prompt, user_prompt, kwargs
        await asyncio.sleep(0.2)
        return ChatJsonResult(
            data={"cases": [_case(name="slow")]},
            provider="test",
            model="test-model",
            fallback_used=False,
        )

    with pytest.raises(asyncio.TimeoutError):
        await generate_and_verify_once(_context(), chat=slow_chat)
