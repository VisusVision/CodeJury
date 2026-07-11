"""RED-phase tests for algorithm expectation extractor and independent verifier."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from backend.algorithm_expectations.cache import AlgorithmExpectationContext
from backend.core.config import settings
from backend.llm.ollama_client import ChatJsonResult
from backend.testing.contracts import AssignmentDifficulty

STUDENT_CODE_SENTINEL = "STUDENT_CODE_SENTINEL_9f3a"

ChatSpy = Callable[..., Awaitable[ChatJsonResult]]

try:
    from backend.algorithm_expectations.generator import (
        ExpectationAttempt,
        build_extractor_prompt,
        build_verifier_prompt,
        extract_and_verify_once,
        infer_expectation_from_assignment,
    )
except ImportError:  # pragma: no cover - RED phase
    extract_and_verify_once = None  # type: ignore[assignment,misc]
    infer_expectation_from_assignment = None  # type: ignore[assignment,misc]
    build_extractor_prompt = None  # type: ignore[assignment,misc]
    build_verifier_prompt = None  # type: ignore[assignment,misc]


def _context(**overrides: Any) -> AlgorithmExpectationContext:
    base = {
        "assignment_id": "assignment-1",
        "title": "Binary Search",
        "description": "Implement binary search on a sorted array. Expected time complexity O(log n).",
        "rubric": ({"name": "Correctness", "max_score": 100},),
        "difficulty": "medium",
    }
    base.update(overrides)
    return AlgorithmExpectationContext(**base)


def _candidate(
    *,
    expected_complexity: str = "O(log n)",
    expected_approach: str = "binary search on sorted input",
    algorithm_families: list[str] | None = None,
    confidence: float = 0.9,
    reason: str = "assignment requires logarithmic search",
) -> dict[str, Any]:
    return {
        "expected_complexity": expected_complexity,
        "expected_approach": expected_approach,
        "algorithm_families": algorithm_families or ["binary_search"],
        "confidence": confidence,
        "reason": reason,
    }


def _verify(
    candidate_id: str,
    *,
    correct: bool = True,
    deterministic: bool = True,
    assignment_aligned: bool = True,
    family_valid: bool = True,
    reason: str = "ok",
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "correct": correct,
        "deterministic": deterministic,
        "assignment_aligned": assignment_aligned,
        "family_valid": family_valid,
        "reason": reason,
    }


def _make_spy(
    candidate: dict[str, Any],
    verifier_decision: dict[str, Any] | None = None,
) -> ChatSpy:
    call_index = {"n": 0}

    async def spy_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del system_prompt, user_prompt, kwargs
        if call_index["n"] == 0:
            call_index["n"] += 1
            return ChatJsonResult(
                data=candidate,
                provider="test",
                model="test-model",
                fallback_used=False,
            )
        call_index["n"] += 1
        return ChatJsonResult(
            data=verifier_decision or _verify("0"),
            provider="test",
            model="test-model",
            fallback_used=False,
        )

    return spy_chat


async def _extract(context: AlgorithmExpectationContext, *, chat: ChatSpy) -> ExpectationAttempt:
    assert extract_and_verify_once is not None
    return await extract_and_verify_once(context, chat=chat)


@pytest.mark.asyncio
async def test_extractor_and_verifier_prompts_never_contain_student_code_sentinel() -> None:
    captured: list[str] = []
    call_index = {"n": 0}

    async def spy_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del kwargs
        captured.append(system_prompt)
        captured.append(user_prompt)
        call_index["n"] += 1
        if call_index["n"] == 1:
            return ChatJsonResult(
                data=_candidate(),
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
    assert extract_and_verify_once is not None
    signature = inspect.signature(extract_and_verify_once)
    forbidden = {"source_code", "stdout", "stderr", "student_id", "student", "submission"}
    assert forbidden.isdisjoint(set(signature.parameters))

    result = await _extract(context, chat=spy_chat)

    assert result.success
    assert all(STUDENT_CODE_SENTINEL not in prompt for prompt in captured)
    joined = "\n".join(captured)
    assert context.title in joined
    assert context.description in joined
    assert context.rubric[0]["name"] in joined
    assert context.difficulty in joined


@pytest.mark.asyncio
async def test_verification_gate_accepts_extractor_verifier_agreement() -> None:
    result = await _extract(_context(), chat=_make_spy(_candidate()))

    assert result.success
    assert result.candidate is not None
    assert result.candidate.expected_complexity.expression == "O(log n)"
    assert result.candidate.expected_approach == "binary search on sorted input"
    assert result.candidate.algorithm_families == ("binary_search",)
    assert result.provider == "test"
    assert result.model == "test-model"


@pytest.mark.asyncio
async def test_verifier_candidate_id_mismatch_is_rejected() -> None:
    mismatch = _verify("0")
    mismatch["candidate_id"] = "999"
    result = await _extract(
        _context(),
        chat=_make_spy(_candidate(), verifier_decision=mismatch),
    )

    assert not result.success
    assert result.candidate is None
    assert result.rejection_reason == "verifier_candidate_id_mismatch"


@pytest.mark.asyncio
async def test_verifier_false_rejects_candidate() -> None:
    result = await _extract(
        _context(),
        chat=_make_spy(
            _candidate(),
            verifier_decision=_verify("0", correct=False, reason="wrong complexity"),
        ),
    )

    assert not result.success
    assert result.candidate is None
    assert "wrong complexity" in result.rejection_reason or result.rejection_reason == "verification_failed"


@pytest.mark.asyncio
async def test_invalid_complexity_expression_is_rejected() -> None:
    result = await _extract(
        _context(),
        chat=_make_spy(_candidate(expected_complexity="O(x+y+z)")),
    )

    assert not result.success
    assert result.candidate is None
    assert result.rejection_reason == "invalid_complexity_expression"


@pytest.mark.asyncio
async def test_invalid_algorithm_family_is_rejected() -> None:
    result = await _extract(
        _context(),
        chat=_make_spy(_candidate(algorithm_families=["not_a_real_family"])),
    )

    assert not result.success
    assert result.candidate is None
    assert result.rejection_reason == "invalid_algorithm_family"


@pytest.mark.asyncio
async def test_invalid_confidence_is_rejected() -> None:
    result = await _extract(
        _context(),
        chat=_make_spy(_candidate(confidence=1.5)),
    )

    assert not result.success
    assert result.candidate is None
    assert result.rejection_reason == "invalid_confidence"


@pytest.mark.asyncio
async def test_extractor_extra_fields_are_rejected() -> None:
    payload = _candidate()
    payload["student_code"] = "evil"
    result = await _extract(_context(), chat=_make_spy(payload))

    assert not result.success
    assert result.candidate is None
    assert result.rejection_reason == "invalid_extractor_response"


@pytest.mark.asyncio
async def test_chat_json_none_produces_failed_attempt_not_exception() -> None:
    async def spy_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del system_prompt, user_prompt, kwargs
        return ChatJsonResult(
            data=None,
            provider="test",
            model="test-model",
            fallback_used=False,
            error="timeout",
        )

    result = await _extract(_context(), chat=spy_chat)

    assert isinstance(result, ExpectationAttempt)
    assert not result.success
    assert result.candidate is None
    assert result.provider == "test"
    assert result.model == "test-model"


@pytest.mark.asyncio
async def test_chat_calls_use_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "algorithm_expectation_call_timeout_seconds", 0.05)

    async def slow_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
        del system_prompt, user_prompt, kwargs
        await asyncio.sleep(0.2)
        return ChatJsonResult(
            data=_candidate(),
            provider="test",
            model="test-model",
            fallback_used=False,
        )

    with pytest.raises(asyncio.TimeoutError):
        await _extract(_context(), chat=slow_chat)


def test_extractor_prompt_includes_assignment_context() -> None:
    assert build_extractor_prompt is not None
    prompt = build_extractor_prompt(_context(difficulty="hard"))
    assert "Binary Search" in prompt
    assert "sorted array" in prompt
    assert "hard" in prompt
    assert "Correctness" in prompt


def test_infer_expectation_parses_explicit_big_o_from_description() -> None:
    assert infer_expectation_from_assignment is not None
    context = _context(
        description="Use a hash map. Time complexity must be O(n).",
    )
    candidate = infer_expectation_from_assignment(context)

    assert candidate is not None
    assert candidate.expected_complexity.expression == "O(n)"
    assert candidate.expected_complexity.source == "deterministic_fallback"


def test_infer_expectation_returns_none_without_explicit_complexity() -> None:
    assert infer_expectation_from_assignment is not None
    context = _context(
        title="Generic Problem",
        description="Solve the problem efficiently.",
    )
    assert infer_expectation_from_assignment(context) is None


def test_infer_expectation_parses_graph_complexity_from_rubric_text() -> None:
    assert infer_expectation_from_assignment is not None
    context = _context(
        description="Traverse the graph.",
        rubric=(
            {
                "name": "Performance",
                "max_score": 20,
                "description": "Solution should run in O(V+E).",
            },
        ),
    )
    candidate = infer_expectation_from_assignment(context)

    assert candidate is not None
    assert candidate.expected_complexity.expression == "O(V+E)"
    assert candidate.expected_complexity.family == "graph"


def test_infer_expectation_does_not_guess_from_vague_efficiency_language() -> None:
    assert infer_expectation_from_assignment is not None
    context = _context(description="Use an efficient algorithm with good performance.")
    assert infer_expectation_from_assignment(context) is None
