from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.llm.ollama_client import ChatJsonResult, chat_json_with_metadata
from backend.testing.cache import AssignmentTestContext
from backend.testing.contracts import FormalTestCase, OracleValidation, TestFixture
from backend.testing.fixture_policy import FixturePolicyError, validate_case_fixtures

_SCHEMA_VERSION = "test-set-v1"

GENERATOR_SYSTEM_PROMPT = (
    "You are an expert programming assignment test-case generator. "
    "Produce deterministic stdin/stdout test cases that evaluate student solutions "
    "against the assignment requirements only. Return strict JSON matching the schema."
)

VERIFIER_SYSTEM_PROMPT = (
    "You are an independent oracle verifier for programming assignment test cases. "
    "Judge whether a proposed case is correct, deterministic, and aligned with the "
    "assignment specification. Return strict JSON matching the schema."
)


class GeneratedFixtureCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    content: str


class GeneratedCaseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    stdin: str
    expected_stdout: str
    expected_exit_code: int = 0
    visibility: Literal["public", "hidden"]
    files: list[GeneratedFixtureCandidate] = Field(default_factory=list)


class GeneratorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[GeneratedCaseCandidate]


class VerifierDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    verified: bool
    deterministic: bool
    assignment_aligned: bool
    reason: str = ""


@dataclass(frozen=True)
class GenerationAttemptResult:
    cases: tuple[FormalTestCase, ...]
    rejected: tuple[dict[str, str], ...]
    provider: str
    model: str
    success: bool


def build_generator_prompt(context: AssignmentTestContext) -> str:
    rubric_text = json.dumps(context.rubric, ensure_ascii=False, indent=2)
    return (
        f"Assignment title: {context.title}\n"
        f"Description: {context.description}\n"
        f"Difficulty: {context.difficulty}\n"
        f"Rubric:\n{rubric_text}\n\n"
        "Generate a reasonable set of test cases covering typical, edge, and boundary "
        "behaviors for this assignment. Each case must include stdin, expected_stdout, "
        "visibility (public or hidden), and optional fixture files with safe relative paths."
    )


def build_verifier_prompt(
    context: AssignmentTestContext,
    case: GeneratedCaseCandidate,
    case_id: str,
) -> str:
    rubric_text = json.dumps(context.rubric, ensure_ascii=False, indent=2)
    case_text = json.dumps(case.model_dump(), ensure_ascii=False, indent=2)
    return (
        f"Assignment title: {context.title}\n"
        f"Description: {context.description}\n"
        f"Difficulty: {context.difficulty}\n"
        f"Rubric:\n{rubric_text}\n\n"
        f"Case id: {case_id}\n"
        f"Proposed case:\n{case_text}\n\n"
        "Verify this case independently against the assignment specification."
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _case_dedup_key(
    stdin: str,
    files: tuple[TestFixture, ...],
    expected_stdout: str,
) -> tuple[str, tuple[tuple[str, str], ...], str]:
    return (stdin, tuple((fixture.name, fixture.content) for fixture in files), expected_stdout)


async def generate_and_verify_once(
    context: AssignmentTestContext,
    *,
    chat: Callable[..., Awaitable[ChatJsonResult]] = chat_json_with_metadata,
) -> GenerationAttemptResult:
    generator_result = await chat(
        system_prompt=GENERATOR_SYSTEM_PROMPT,
        user_prompt=build_generator_prompt(context),
        schema_hint=GeneratorResponse.model_json_schema(),
        temperature=0.2,
        use_cache=False,
    )

    if generator_result.data is None:
        return GenerationAttemptResult(
            cases=(),
            rejected=(),
            provider=generator_result.provider,
            model=generator_result.model,
            success=False,
        )

    try:
        generator_response = GeneratorResponse.model_validate(generator_result.data)
    except ValidationError:
        return GenerationAttemptResult(
            cases=(),
            rejected=(),
            provider=generator_result.provider,
            model=generator_result.model,
            success=False,
        )

    rejected: list[dict[str, str]] = []
    verified_cases: list[tuple[str, GeneratedCaseCandidate, tuple[TestFixture, ...]]] = []

    for index, candidate in enumerate(generator_response.cases):
        case_id = str(index)
        verifier_result = await chat(
            system_prompt=VERIFIER_SYSTEM_PROMPT,
            user_prompt=build_verifier_prompt(context, candidate, case_id),
            schema_hint=VerifierDecision.model_json_schema(),
            temperature=0.0,
            use_cache=False,
        )

        if verifier_result.data is None:
            rejected.append(
                {
                    "case_id": case_id,
                    "name": candidate.name,
                    "reason": verifier_result.error or "verifier_failed",
                }
            )
            continue

        try:
            decision = VerifierDecision.model_validate(verifier_result.data)
        except ValidationError:
            rejected.append(
                {
                    "case_id": case_id,
                    "name": candidate.name,
                    "reason": "invalid_verifier_response",
                }
            )
            continue

        if not (decision.verified and decision.deterministic and decision.assignment_aligned):
            rejected.append(
                {
                    "case_id": case_id,
                    "name": candidate.name,
                    "reason": decision.reason or "verification_failed",
                }
            )
            continue

        fixtures = [
            TestFixture(name=file.name, content=file.content) for file in candidate.files
        ]
        try:
            validated_fixtures = tuple(validate_case_fixtures(fixtures))
        except FixturePolicyError as exc:
            rejected.append(
                {
                    "case_id": case_id,
                    "name": candidate.name,
                    "reason": str(exc),
                }
            )
            continue

        verified_cases.append((case_id, candidate, validated_fixtures))

    seen: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    surviving: list[tuple[str, GeneratedCaseCandidate, tuple[TestFixture, ...]]] = []
    for case_id, candidate, validated_fixtures in verified_cases:
        key = _case_dedup_key(candidate.stdin, validated_fixtures, candidate.expected_stdout)
        if key in seen:
            continue
        seen.add(key)
        surviving.append((case_id, candidate, validated_fixtures))

    formal_cases = tuple(
        FormalTestCase(
            id=case_id,
            name=candidate.name,
            stdin=candidate.stdin,
            expected_stdout=candidate.expected_stdout,
            expected_exit_code=candidate.expected_exit_code,
            visibility=candidate.visibility,
            files=validated_fixtures,
            source="auto_generated",
            oracle="llm_verified",
            oracle_validation=OracleValidation(
                status="verified",
                provider=generator_result.provider,
                model=generator_result.model,
                schema_version=_SCHEMA_VERSION,
                verified_at=_utc_now_iso(),
                reason="",
            ),
        )
        for case_id, candidate, validated_fixtures in surviving
    )

    return GenerationAttemptResult(
        cases=formal_cases,
        rejected=tuple(rejected),
        provider=generator_result.provider,
        model=generator_result.model,
        success=True,
    )
