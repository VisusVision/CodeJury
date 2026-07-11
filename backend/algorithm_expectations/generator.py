from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.algorithm_analysis.complexity import normalize_complexity
from backend.algorithm_analysis.contracts import ComplexityEstimate
from backend.algorithm_expectations.cache import AlgorithmExpectationContext
from backend.core.config import settings
from backend.llm.ollama_client import ChatJsonResult, chat_json_with_metadata

EXTRACTOR_SYSTEM_PROMPT = (
    "You are an expert algorithm expectation extractor for programming assignments. "
    "Infer expected time complexity, algorithm families, and conceptual approach from "
    "the assignment specification only. Return strict JSON matching the schema."
)

VERIFIER_SYSTEM_PROMPT = (
    "You are an independent verifier for programming assignment algorithm expectations. "
    "Judge whether a proposed expectation is correct, deterministic, and aligned with the "
    "assignment specification. Return strict JSON matching the schema."
)

CANDIDATE_ID = "0"

ALLOWED_ALGORITHM_FAMILIES = frozenset(
    {
        "binary_search",
        "hash_lookup",
        "sorting",
        "stack",
        "queue",
        "deque",
        "heap",
        "recursion",
        "backtracking",
        "bfs",
        "dfs",
        "greedy",
        "dynamic_programming",
        "brute_force",
        "brute_force_nested_scan",
        "divide_and_conquer",
        "search",
        "graph_traversal",
    }
)

_BIG_O_PATTERN = re.compile(r"O\s*\(", re.IGNORECASE)


def _extract_big_o_expressions(text: str) -> tuple[str, ...]:
    """Extract Big-O expressions, including nested parentheses like O((V+E) log V)."""
    expressions: list[str] = []
    for match in _BIG_O_PATTERN.finditer(text):
        start = match.start()
        index = match.end()
        depth = 1
        while index < len(text) and depth > 0:
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        if depth == 0:
            expressions.append(text[start:index])
    return tuple(expressions)


class ExtractorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_complexity: str
    expected_approach: str
    algorithm_families: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class VerifierDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    correct: bool
    deterministic: bool
    assignment_aligned: bool
    family_valid: bool
    reason: str = ""


@dataclass(frozen=True)
class AlgorithmExpectationCandidate:
    expected_complexity: ComplexityEstimate
    expected_approach: str
    algorithm_families: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class ExpectationAttempt:
    candidate: AlgorithmExpectationCandidate | None
    rejection_reason: str
    provider: str
    model: str
    success: bool
    verifier_provider: str = ""
    verifier_model: str = ""


def build_extractor_prompt(context: AlgorithmExpectationContext) -> str:
    rubric_text = json.dumps(list(context.rubric), ensure_ascii=False, indent=2)
    return (
        f"Assignment title: {context.title}\n"
        f"Description: {context.description}\n"
        f"Difficulty: {context.difficulty}\n"
        f"Rubric:\n{rubric_text}\n\n"
        "Extract the expected time complexity expression, conceptual algorithm approach, "
        "and algorithm families implied by this assignment specification."
    )


def build_verifier_prompt(
    context: AlgorithmExpectationContext,
    candidate: ExtractorResponse,
    candidate_id: str,
) -> str:
    rubric_text = json.dumps(list(context.rubric), ensure_ascii=False, indent=2)
    candidate_text = json.dumps(candidate.model_dump(), ensure_ascii=False, indent=2)
    return (
        f"Assignment title: {context.title}\n"
        f"Description: {context.description}\n"
        f"Difficulty: {context.difficulty}\n"
        f"Rubric:\n{rubric_text}\n\n"
        f"Candidate id: {candidate_id}\n"
        f"Proposed expectation:\n{candidate_text}\n\n"
        "Verify this expectation independently against the assignment specification."
    )


def _normalize_family_name(raw: str) -> str:
    return re.sub(r"\s+", "_", raw.strip().lower())


def _validate_families(families: list[str]) -> tuple[str, ...] | None:
    normalized = tuple(_normalize_family_name(item) for item in families if item.strip())
    if not normalized:
        return None
    if any(item not in ALLOWED_ALGORITHM_FAMILIES for item in normalized):
        return None
    return normalized


def _assignment_text(context: AlgorithmExpectationContext) -> str:
    rubric_chunks = []
    for item in context.rubric:
        rubric_chunks.extend(str(value) for value in item.values())
    return "\n".join([context.title, context.description, *rubric_chunks])


def _candidate_from_extractor(
    response: ExtractorResponse,
    *,
    source: Literal["llm", "deterministic_fallback"],
) -> tuple[AlgorithmExpectationCandidate | None, str]:
    try:
        complexity = normalize_complexity(
            response.expected_complexity,
            source=source,
            confidence=response.confidence,
        )
    except (ValueError, ValidationError):
        return None, "invalid_confidence"

    if complexity.family == "unknown":
        return None, "invalid_complexity_expression"

    families = _validate_families(response.algorithm_families)
    if families is None:
        return None, "invalid_algorithm_family"

    return (
        AlgorithmExpectationCandidate(
            expected_complexity=complexity,
            expected_approach=response.expected_approach.strip(),
            algorithm_families=families,
            confidence=response.confidence,
        ),
        "",
    )


def infer_expectation_from_assignment(
    context: AlgorithmExpectationContext,
) -> AlgorithmExpectationCandidate | None:
    text = _assignment_text(context)
    for expression in _extract_big_o_expressions(text):
        try:
            complexity = normalize_complexity(
                expression,
                source="deterministic_fallback",
                confidence=1.0,
            )
        except (ValueError, ValidationError):
            continue
        if complexity.family == "unknown":
            continue

        approach = ""
        lowered = text.lower()
        if "binary search" in lowered:
            approach = "binary search"
            families: tuple[str, ...] = ("binary_search",)
        elif "hash" in lowered:
            approach = "hash lookup"
            families = ("hash_lookup",)
        elif "bfs" in lowered or "breadth-first" in lowered:
            approach = "breadth-first search"
            families = ("bfs",)
        elif "dfs" in lowered or "depth-first" in lowered:
            approach = "depth-first search"
            families = ("dfs",)
        else:
            families = ()

        return AlgorithmExpectationCandidate(
            expected_complexity=complexity,
            expected_approach=approach,
            algorithm_families=families,
            confidence=1.0,
        )
    return None


def _failed_attempt(
    *,
    reason: str,
    provider: str,
    model: str,
    verifier_provider: str = "",
    verifier_model: str = "",
) -> ExpectationAttempt:
    return ExpectationAttempt(
        candidate=None,
        rejection_reason=reason,
        provider=provider,
        model=model,
        success=False,
        verifier_provider=verifier_provider,
        verifier_model=verifier_model,
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def extract_and_verify_once(
    context: AlgorithmExpectationContext,
    *,
    chat: Callable[..., Awaitable[ChatJsonResult]] = chat_json_with_metadata,
) -> ExpectationAttempt:
    timeout_seconds = settings.algorithm_expectation_call_timeout_seconds

    async def _call_chat(**kwargs: object) -> ChatJsonResult:
        return await asyncio.wait_for(chat(**kwargs), timeout=timeout_seconds)

    extractor_result = await _call_chat(
        system_prompt=EXTRACTOR_SYSTEM_PROMPT,
        user_prompt=build_extractor_prompt(context),
        schema_hint=ExtractorResponse.model_json_schema(),
        temperature=0.2,
        use_cache=False,
    )

    if extractor_result.data is None:
        return _failed_attempt(
            reason=extractor_result.error or "extractor_failed",
            provider=extractor_result.provider,
            model=extractor_result.model,
        )

    try:
        extractor_response = ExtractorResponse.model_validate(extractor_result.data)
    except ValidationError as exc:
        reason = "invalid_confidence"
        for error in exc.errors():
            if error.get("loc") == ("confidence",):
                reason = "invalid_confidence"
                break
        else:
            reason = "invalid_extractor_response"
        return _failed_attempt(
            reason=reason,
            provider=extractor_result.provider,
            model=extractor_result.model,
        )

    candidate, rejection = _candidate_from_extractor(extractor_response, source="llm")
    if candidate is None:
        return _failed_attempt(
            reason=rejection,
            provider=extractor_result.provider,
            model=extractor_result.model,
        )

    verifier_result = await _call_chat(
        system_prompt=VERIFIER_SYSTEM_PROMPT,
        user_prompt=build_verifier_prompt(context, extractor_response, CANDIDATE_ID),
        schema_hint=VerifierDecision.model_json_schema(),
        temperature=0.0,
        use_cache=False,
    )

    if verifier_result.data is None:
        return _failed_attempt(
            reason=verifier_result.error or "verifier_failed",
            provider=extractor_result.provider,
            model=extractor_result.model,
            verifier_provider=verifier_result.provider,
            verifier_model=verifier_result.model,
        )

    try:
        decision = VerifierDecision.model_validate(verifier_result.data)
    except ValidationError:
        return _failed_attempt(
            reason="invalid_verifier_response",
            provider=extractor_result.provider,
            model=extractor_result.model,
            verifier_provider=verifier_result.provider,
            verifier_model=verifier_result.model,
        )

    if decision.candidate_id != CANDIDATE_ID:
        return _failed_attempt(
            reason="verifier_candidate_id_mismatch",
            provider=extractor_result.provider,
            model=extractor_result.model,
            verifier_provider=verifier_result.provider,
            verifier_model=verifier_result.model,
        )

    if not (
        decision.correct
        and decision.deterministic
        and decision.assignment_aligned
        and decision.family_valid
    ):
        return _failed_attempt(
            reason=decision.reason or "verification_failed",
            provider=extractor_result.provider,
            model=extractor_result.model,
            verifier_provider=verifier_result.provider,
            verifier_model=verifier_result.model,
        )

    return ExpectationAttempt(
        candidate=candidate,
        rejection_reason="",
        provider=extractor_result.provider,
        model=extractor_result.model,
        success=True,
        verifier_provider=verifier_result.provider,
        verifier_model=verifier_result.model,
    )
