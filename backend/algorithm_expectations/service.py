from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import asyncpg

from backend.core.config import settings
from backend.algorithm_expectations.cache import (
    AlgorithmExpectationContext,
    AlgorithmExpectationLeaseLost,
    ExpectationGenerationLockUnavailable,
    compute_assignment_hash,
    compute_expectation_identity,
    compute_rubric_hash,
    expectation_generation_lock,
)
from backend.algorithm_expectations.contracts import (
    AlgorithmExpectation,
    AlgorithmExpectationResolution,
)
from backend.algorithm_expectations.generator import (
    AlgorithmExpectationCandidate,
    ExpectationAttempt,
    infer_expectation_from_assignment,
)
from backend.algorithm_expectations.store import AlgorithmExpectationStore


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


def _unknown(
    *,
    cache_key: str,
    generation_attempts: int = 0,
) -> AlgorithmExpectationResolution:
    return AlgorithmExpectationResolution(
        expectation=None,
        status="unknown",
        cache_key=cache_key,
        generation_attempts=generation_attempts,
    )


def _resolution_from_expectation(
    expectation: AlgorithmExpectation,
    *,
    status: str,
    generation_attempts: int = 0,
) -> AlgorithmExpectationResolution:
    return AlgorithmExpectationResolution(
        expectation=expectation,
        status=status,  # type: ignore[arg-type]
        cache_key=expectation.cache_key,
        generation_attempts=generation_attempts,
    )


async def _resolve_cached(
    store: AlgorithmExpectationStore,
    assignment_id: str,
    cache_key: str,
) -> AlgorithmExpectation | None:
    cached = await store.find_by_cache_key(assignment_id, cache_key)
    if cached is None:
        return None
    if cached.active:
        return cached
    return await store.reactivate_exact(assignment_id, cache_key)


async def _persist_expectation(
    store: AlgorithmExpectationStore,
    context: AlgorithmExpectationContext,
    cache_key: str,
    candidate: AlgorithmExpectationCandidate,
    attempt: ExpectationAttempt,
    *,
    lease,
    verification_status: str = "verified",
) -> AlgorithmExpectation:
    lease.check()
    provider, model = _provider_and_model()
    expectation = AlgorithmExpectation(
        id=str(uuid.uuid4()),
        assignment_id=context.assignment_id,
        cache_key=cache_key,
        version=1,
        expected_complexity=candidate.expected_complexity,
        expected_approach=candidate.expected_approach,
        algorithm_families=candidate.algorithm_families,
        confidence=candidate.confidence,
        extractor_provider=attempt.provider or provider,
        extractor_model=attempt.model or model,
        verifier_provider=attempt.verifier_provider or attempt.provider or provider,
        verifier_model=attempt.verifier_model or attempt.model or model,
        schema_version=settings.algorithm_expectation_schema_version,
        extractor_prompt_version=settings.algorithm_expectation_extractor_prompt_version,
        verifier_prompt_version=settings.algorithm_expectation_verifier_prompt_version,
        assignment_hash=compute_assignment_hash(context),
        rubric_hash=compute_rubric_hash(context),
        verification_status=verification_status,  # type: ignore[arg-type]
        verification_reason="",
        active=True,
        created_at=_utc_now_iso(),
    )
    try:
        return await store.insert_verified(expectation, lease_check=lease.check)
    except AlgorithmExpectationLeaseLost:
        raise
    except asyncpg.UniqueViolationError:
        winner = await store.find_by_cache_key(context.assignment_id, cache_key)
        if winner is None:
            raise
        return winner


async def _generate_under_lock(
    context: AlgorithmExpectationContext,
    cache_key: str,
    *,
    store: AlgorithmExpectationStore,
    redis,
    generate_once: Callable[[AlgorithmExpectationContext], Awaitable[ExpectationAttempt]],
) -> AlgorithmExpectationResolution:
    try:
        async with expectation_generation_lock(
            redis,
            context.assignment_id,
            cache_key,
            ttl_seconds=settings.algorithm_expectation_lock_ttl_seconds,
            wait_seconds=settings.algorithm_expectation_lock_wait_seconds,
            poll_seconds=settings.algorithm_expectation_lock_poll_seconds,
        ) as lease:
            cached = await _resolve_cached(store, context.assignment_id, cache_key)
            if cached is not None:
                return _resolution_from_expectation(cached, status="available")

            generation_attempts = 0
            for _ in range(2):
                generation_attempts += 1
                try:
                    attempt = await generate_once(context)
                except Exception:
                    continue

                if not attempt.success or attempt.candidate is None:
                    continue

                try:
                    inserted = await _persist_expectation(
                        store,
                        context,
                        cache_key,
                        attempt.candidate,
                        attempt,
                        lease=lease,
                    )
                except AlgorithmExpectationLeaseLost:
                    return _unknown(
                        cache_key=cache_key,
                        generation_attempts=generation_attempts,
                    )
                return _resolution_from_expectation(
                    inserted,
                    status="available",
                    generation_attempts=generation_attempts,
                )

            fallback = infer_expectation_from_assignment(context)
            if fallback is not None:
                fallback_attempt = ExpectationAttempt(
                    candidate=fallback,
                    rejection_reason="",
                    provider="deterministic",
                    model="parser",
                    success=True,
                )
                try:
                    inserted = await _persist_expectation(
                        store,
                        context,
                        cache_key,
                        fallback,
                        fallback_attempt,
                        lease=lease,
                    )
                except AlgorithmExpectationLeaseLost:
                    return _unknown(
                        cache_key=cache_key,
                        generation_attempts=generation_attempts,
                    )
                return _resolution_from_expectation(
                    inserted,
                    status="deterministic_fallback",
                    generation_attempts=generation_attempts,
                )

            return _unknown(
                cache_key=cache_key,
                generation_attempts=generation_attempts,
            )
    except ExpectationGenerationLockUnavailable:
        return _unknown(cache_key=cache_key)


async def resolve_expectation(
    context: AlgorithmExpectationContext,
    *,
    store: AlgorithmExpectationStore,
    redis,
    generate_once: Callable[[AlgorithmExpectationContext], Awaitable[ExpectationAttempt]],
) -> AlgorithmExpectationResolution:
    provider, model = _provider_and_model()
    cache_key = compute_expectation_identity(context, provider, model).cache_key

    cached = await _resolve_cached(store, context.assignment_id, cache_key)
    if cached is not None:
        return _resolution_from_expectation(cached, status="available")

    try:
        return await asyncio.wait_for(
            _generate_under_lock(
                context,
                cache_key,
                store=store,
                redis=redis,
                generate_once=generate_once,
            ),
            timeout=settings.algorithm_expectation_total_timeout_seconds,
        )
    except asyncio.TimeoutError:
        return _unknown(cache_key=cache_key)
    except (asyncpg.PostgresError, RuntimeError, OSError):
        raise
