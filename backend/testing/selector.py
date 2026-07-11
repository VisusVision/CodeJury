from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import asyncpg

from backend.core.config import settings
from backend.testing.cache import (
    AssignmentTestContext,
    GenerationLockUnavailable,
    LeaseLost,
    compute_cache_identity,
    generation_lock,
)
from backend.testing.contracts import (
    AssignmentDifficulty,
    FormalTestCase,
    GeneratedTestSet,
    TestSelection,
)
from backend.testing.difficulty import TARGETS
from backend.testing.generator import GenerationAttemptResult
from backend.testing.store import GeneratedTestSetStore

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_provider(provider: str) -> str:
    normalized = (provider or "ollama").strip().lower()
    if normalized in {"nvidia_nim", "nim", "nvidia"}:
        return "nvidia_nim"
    return "ollama"


def _provider_and_model() -> tuple[str, str]:
    provider = _normalize_provider(settings.llm_provider)
    if provider == "nvidia_nim":
        return provider, settings.nvidia_nim_general_model
    return provider, settings.ollama_general_model


def _is_python(language: str) -> bool:
    return language.strip().lower() in {"python", "py"}


def _is_assignment_less(context: AssignmentTestContext) -> bool:
    return not (context.assignment_id or "").strip()


def _unavailable(
    *,
    cache_key: str | None = None,
    generation_attempts: int = 0,
) -> TestSelection:
    return TestSelection(
        cases=(),
        source="none",
        test_set_id=None,
        cache_key=cache_key,
        cache_version=None,
        test_evidence_status="unavailable",
        generation_attempts=generation_attempts,
    )


def _select_from_cases(
    cases: tuple[FormalTestCase, ...],
    difficulty: AssignmentDifficulty,
) -> tuple[FormalTestCase, ...]:
    policy = TARGETS[difficulty]
    target = policy["target"]
    public_target = policy["public"]
    hidden_target = target - public_target

    public_cases = [case for case in cases if case.visibility == "public"]
    hidden_cases = [case for case in cases if case.visibility == "hidden"]
    return tuple(public_cases[:public_target] + hidden_cases[:hidden_target])


def _attempt_is_sufficient(
    cases: tuple[FormalTestCase, ...],
    difficulty: AssignmentDifficulty,
) -> bool:
    policy = TARGETS[difficulty]
    public_cases = [case for case in cases if case.visibility == "public"]
    hidden_cases = [case for case in cases if case.visibility == "hidden"]
    hidden_needed = max(0, policy["minimum"] - policy["public"])
    return (
        len(cases) >= policy["minimum"]
        and len(public_cases) >= policy["public"]
        and len(hidden_cases) >= hidden_needed
    )


def _selection_from_set(
    test_set: GeneratedTestSet,
    *,
    generation_attempts: int = 0,
) -> TestSelection:
    return TestSelection(
        cases=_select_from_cases(test_set.cases, test_set.difficulty),
        source="auto_generated",
        test_set_id=test_set.id,
        cache_key=test_set.cache_key,
        cache_version=test_set.version,
        test_evidence_status="available",
        generation_attempts=generation_attempts,
    )


def _faculty_selection(
    cases: tuple[FormalTestCase, ...],
    *,
    cache_key: str | None,
) -> TestSelection:
    return TestSelection(
        cases=cases,
        source="faculty",
        test_set_id=None,
        cache_key=cache_key,
        cache_version=None,
        test_evidence_status="available",
        generation_attempts=0,
    )


async def _resolve_cached_set(
    store: GeneratedTestSetStore,
    assignment_id: str,
    cache_key: str,
) -> GeneratedTestSet | None:
    cached = await store.find_by_cache_key(assignment_id, cache_key)
    if cached is None:
        return None
    if cached.active:
        return cached
    return await store.reactivate_exact(assignment_id, cache_key)


async def _persist_generated_set(
    store: GeneratedTestSetStore,
    context: AssignmentTestContext,
    cache_key: str,
    attempt: GenerationAttemptResult,
    *,
    lease,
) -> GeneratedTestSet:
    lease.check()
    provider, model = _provider_and_model()
    test_set = GeneratedTestSet(
        id=str(uuid.uuid4()),
        assignment_id=context.assignment_id,
        cache_key=cache_key,
        version=1,
        difficulty=context.difficulty,
        cases=_select_from_cases(attempt.cases, context.difficulty),
        provider=attempt.provider or provider,
        model=attempt.model or model,
        schema_version=settings.test_generation_schema_version,
        prompt_version=settings.test_generation_prompt_version,
        active=True,
        created_at=_utc_now_iso(),
    )
    try:
        return await store.insert_verified_set(test_set, lease_check=lease.check)
    except LeaseLost:
        raise
    except asyncpg.UniqueViolationError:
        winner = await store.find_by_cache_key(context.assignment_id, cache_key)
        if winner is None:
            raise
        return winner


async def _generate_under_lock(
    context: AssignmentTestContext,
    cache_key: str,
    *,
    store: GeneratedTestSetStore,
    redis,
    generate_once: Callable[[AssignmentTestContext], Awaitable[GenerationAttemptResult]],
) -> TestSelection:
    try:
        async with generation_lock(
            redis,
            context.assignment_id,
            cache_key,
            ttl_seconds=settings.test_generation_lock_ttl_seconds,
            wait_seconds=settings.test_generation_lock_wait_seconds,
            poll_seconds=settings.test_generation_lock_poll_seconds,
        ) as lease:
            cached = await _resolve_cached_set(
                store, context.assignment_id, cache_key
            )
            if cached is not None:
                return _selection_from_set(cached)

            generation_attempts = 0
            for _ in range(2):
                generation_attempts += 1
                try:
                    attempt = await generate_once(context)
                except Exception:
                    continue

                if not _attempt_is_sufficient(attempt.cases, context.difficulty):
                    continue

                try:
                    inserted = await _persist_generated_set(
                        store,
                        context,
                        cache_key,
                        attempt,
                        lease=lease,
                    )
                except LeaseLost:
                    return _unavailable(
                        cache_key=cache_key,
                        generation_attempts=generation_attempts,
                    )
                return _selection_from_set(
                    inserted,
                    generation_attempts=generation_attempts,
                )

            return _unavailable(
                cache_key=cache_key,
                generation_attempts=generation_attempts,
            )
    except GenerationLockUnavailable:
        return _unavailable(cache_key=cache_key)


async def _select_auto_generated(
    context: AssignmentTestContext,
    cache_key: str,
    *,
    store: GeneratedTestSetStore,
    redis,
    generate_once: Callable[[AssignmentTestContext], Awaitable[GenerationAttemptResult]],
) -> TestSelection:
    cached = await _resolve_cached_set(store, context.assignment_id, cache_key)
    if cached is not None:
        return _selection_from_set(cached)

    return await asyncio.wait_for(
        _generate_under_lock(
            context,
            cache_key,
            store=store,
            redis=redis,
            generate_once=generate_once,
        ),
        timeout=settings.test_generation_total_timeout_seconds,
    )


async def select_tests(
    context: AssignmentTestContext,
    language: str,
    *,
    load_faculty: Callable[[], Awaitable[tuple[FormalTestCase, ...] | list[FormalTestCase]]],
    store: GeneratedTestSetStore,
    redis,
    generate_once: Callable[[AssignmentTestContext], Awaitable[GenerationAttemptResult]],
) -> TestSelection:
    faculty_cases = tuple(await load_faculty())
    provider, model = _provider_and_model()
    cache_key = compute_cache_identity(context, provider, model).cache_key

    if faculty_cases:
        return _faculty_selection(faculty_cases, cache_key=cache_key)

    if _is_assignment_less(context) or not _is_python(language):
        return _unavailable()

    try:
        return await _select_auto_generated(
            context,
            cache_key,
            store=store,
            redis=redis,
            generate_once=generate_once,
        )
    except asyncio.TimeoutError:
        return _unavailable(cache_key=cache_key)
    except (asyncpg.PostgresError, RuntimeError, OSError):
        raise
