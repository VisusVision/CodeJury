"""RED-phase tests for algorithm expectation resolution orchestration."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from backend.algorithm_analysis.contracts import ComplexityEstimate
from backend.algorithm_expectations.cache import (
    AlgorithmExpectationContext,
    AlgorithmExpectationLeaseLost,
    ExpectationGenerationLockUnavailable,
    compute_assignment_hash,
    compute_expectation_identity,
    compute_rubric_hash,
)
from backend.algorithm_expectations.contracts import (
    AlgorithmExpectation,
    AlgorithmExpectationResolution,
)
from backend.algorithm_expectations.store import DemoAlgorithmExpectationStore
from backend.core.config import settings
from backend.testing.contracts import AssignmentDifficulty

try:
    from backend.algorithm_expectations.generator import (
        AlgorithmExpectationCandidate,
        ExpectationAttempt,
    )
    from backend.algorithm_expectations.service import resolve_expectation
except ImportError:  # pragma: no cover - RED phase
    AlgorithmExpectationCandidate = None  # type: ignore[assignment,misc]
    ExpectationAttempt = None  # type: ignore[assignment,misc]
    resolve_expectation = None  # type: ignore[assignment,misc]


def _provider_and_model() -> tuple[str, str]:
    provider = (settings.llm_provider or "ollama").strip().lower()
    if provider in {"nvidia_nim", "nim", "nvidia"}:
        return "nvidia_nim", settings.nvidia_nim_general_model
    return "ollama", settings.ollama_general_model


def _cache_key(context: AlgorithmExpectationContext) -> str:
    provider, model = _provider_and_model()
    return compute_expectation_identity(context, provider, model).cache_key


def _context(
    *,
    assignment_id: str = "assignment-1",
    title: str = "Binary Search",
    description: str = "Implement binary search on a sorted array.",
    rubric: tuple[dict, ...] | None = None,
    difficulty: AssignmentDifficulty = "medium",
) -> AlgorithmExpectationContext:
    return AlgorithmExpectationContext(
        assignment_id=assignment_id,
        title=title,
        description=description,
        rubric=rubric or ({"name": "Correctness", "max_score": 100},),
        difficulty=difficulty,
    )


def _complexity(*, source: str = "llm") -> ComplexityEstimate:
    return ComplexityEstimate(
        expression="O(log n)",
        family="single_variable",
        rank=1,
        confidence=0.9,
        source=source,  # type: ignore[arg-type]
    )


def _candidate(*, source: str = "llm") -> AlgorithmExpectationCandidate:
    assert AlgorithmExpectationCandidate is not None
    return AlgorithmExpectationCandidate(
        expected_complexity=_complexity(source=source),
        expected_approach="binary search",
        algorithm_families=("binary_search",),
        confidence=0.9,
    )


def _successful_attempt(*, source: str = "llm") -> ExpectationAttempt:
    assert ExpectationAttempt is not None
    return ExpectationAttempt(
        candidate=_candidate(source=source),
        rejection_reason="",
        provider="ollama",
        model="qwen2.5:7b",
        success=True,
    )


def _failed_attempt(*, reason: str = "verification_failed") -> ExpectationAttempt:
    assert ExpectationAttempt is not None
    return ExpectationAttempt(
        candidate=None,
        rejection_reason=reason,
        provider="ollama",
        model="qwen2.5:7b",
        success=False,
    )


def _expectation(
    context: AlgorithmExpectationContext,
    *,
    expectation_id: str = "exp-1",
    active: bool = True,
    cache_key: str | None = None,
    version: int = 1,
    source: str = "llm",
) -> AlgorithmExpectation:
    provider, model = _provider_and_model()
    return AlgorithmExpectation(
        id=expectation_id,
        assignment_id=context.assignment_id,
        cache_key=cache_key or _cache_key(context),
        version=version,
        expected_complexity=_complexity(source=source),
        expected_approach="binary search",
        algorithm_families=("binary_search",),
        confidence=0.9,
        extractor_provider=provider,
        extractor_model=model,
        verifier_provider=provider,
        verifier_model=model,
        schema_version=settings.algorithm_expectation_schema_version,
        extractor_prompt_version=settings.algorithm_expectation_extractor_prompt_version,
        verifier_prompt_version=settings.algorithm_expectation_verifier_prompt_version,
        verification_status="verified",
        active=active,
    )


def _make_demo_store() -> DemoAlgorithmExpectationStore:
    return DemoAlgorithmExpectationStore({"algorithm_expectations": []})


class FakeCacheRedis:
    """Minimal async Redis double for expectation lock tests."""

    def __init__(self, *, monotonic: float | None = None) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self._expires_at: dict[str, float] = {}
        self._monotonic = monotonic if monotonic is not None else time.monotonic()

    def _now(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._monotonic += seconds

    def _purge_expired(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is not None and self._now() >= expires_at:
            self.values.pop(key, None)
            self.expirations.pop(key, None)
            self._expires_at.pop(key, None)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        self._purge_expired(key)
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
            self._expires_at[key] = self._now() + ex
        return True

    async def get(self, key: str) -> str | None:
        self._purge_expired(key)
        return self.values.get(key)

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any):
        key = keys_and_args[0]
        self._purge_expired(key)
        token = keys_and_args[1]
        if self.values.get(key) != token:
            return 0
        if "expire" in script:
            ttl_seconds = float(keys_and_args[2])
            self.expirations[key] = int(ttl_seconds)
            self._expires_at[key] = self._now() + ttl_seconds
            return 1
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        self._expires_at.pop(key, None)
        return 1


def _lock_key(assignment_id: str, cache_key: str) -> str:
    return f"algorithm:expectation_lock:{assignment_id}:{cache_key}"


@pytest.fixture
def redis() -> FakeCacheRedis:
    return FakeCacheRedis()


@pytest.fixture
def context() -> AlgorithmExpectationContext:
    return _context()


async def _resolve(
    context: AlgorithmExpectationContext,
    *,
    store: DemoAlgorithmExpectationStore | AsyncMock | None = None,
    redis: FakeCacheRedis | None = None,
    generate_once: AsyncMock | None = None,
) -> AlgorithmExpectationResolution:
    assert resolve_expectation is not None
    return await resolve_expectation(
        context,
        store=store or _make_demo_store(),
        redis=redis or FakeCacheRedis(),
        generate_once=generate_once or AsyncMock(return_value=_successful_attempt()),
    )


@pytest.mark.asyncio
async def test_active_exact_cache_hit_is_used_without_generation(
    context: AlgorithmExpectationContext,
    redis: FakeCacheRedis,
) -> None:
    store = _make_demo_store()
    cached = _expectation(context, expectation_id="active-exp", version=3)
    store._container["algorithm_expectations"].append(
        {
            "id": cached.id,
            "assignment_id": cached.assignment_id,
            "cache_key": cached.cache_key,
            "version": 3,
            "complexity": cached.expected_complexity.model_dump(),
            "expected_approach": cached.expected_approach,
            "algorithm_families": list(cached.algorithm_families),
            "confidence": cached.confidence,
            "extractor_provider": cached.extractor_provider,
            "extractor_model": cached.extractor_model,
            "verifier_provider": cached.verifier_provider,
            "verifier_model": cached.verifier_model,
            "schema_version": cached.schema_version,
            "extractor_prompt_version": cached.extractor_prompt_version,
            "verifier_prompt_version": cached.verifier_prompt_version,
            "assignment_hash": "",
            "rubric_hash": "",
            "verification_status": cached.verification_status,
            "verification_reason": "",
            "active": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "deactivated_at": None,
        }
    )

    resolution = await _resolve(
        context,
        store=store,
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert resolution.status == "available"
    assert resolution.expectation is not None
    assert resolution.expectation.id == "active-exp"
    assert resolution.expectation.version == 3
    assert resolution.generation_attempts == 0


@pytest.mark.asyncio
async def test_inactive_exact_cache_is_reactivated(
    context: AlgorithmExpectationContext,
    redis: FakeCacheRedis,
) -> None:
    store = _make_demo_store()
    cache_key = _cache_key(context)
    store._container["algorithm_expectations"].append(
        {
            "id": "inactive-exp",
            "assignment_id": context.assignment_id,
            "cache_key": cache_key,
            "version": 2,
            "complexity": _complexity().model_dump(),
            "expected_approach": "binary search",
            "algorithm_families": ["binary_search"],
            "confidence": 0.9,
            "extractor_provider": "ollama",
            "extractor_model": "qwen2.5:7b",
            "verifier_provider": "ollama",
            "verifier_model": "qwen2.5:7b",
            "schema_version": settings.algorithm_expectation_schema_version,
            "extractor_prompt_version": settings.algorithm_expectation_extractor_prompt_version,
            "verifier_prompt_version": settings.algorithm_expectation_verifier_prompt_version,
            "assignment_hash": "",
            "rubric_hash": "",
            "verification_status": "verified",
            "verification_reason": "",
            "active": False,
            "created_at": "2026-01-01T00:00:00+00:00",
            "deactivated_at": "2026-01-02T00:00:00+00:00",
        }
    )

    resolution = await _resolve(
        context,
        store=store,
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert resolution.status == "available"
    assert resolution.expectation is not None
    assert resolution.expectation.id == "inactive-exp"
    assert resolution.generation_attempts == 0
    reactivated = await store.find_by_cache_key(context.assignment_id, cache_key)
    assert reactivated is not None
    assert reactivated.active is True


@pytest.mark.asyncio
async def test_two_failed_attempts_then_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
    redis: FakeCacheRedis,
) -> None:
    context = _context(description="Implement binary search. Required complexity O(log n).")
    generate_once = AsyncMock(
        side_effect=[_failed_attempt(), _failed_attempt(reason="verifier_false")]
    )

    resolution = await _resolve(context, store=_make_demo_store(), redis=redis, generate_once=generate_once)

    assert resolution.status == "deterministic_fallback"
    assert resolution.generation_attempts == 2
    assert resolution.expectation is not None
    assert resolution.expectation.expected_complexity.source == "deterministic_fallback"
    assert resolution.expectation.expected_complexity.expression == "O(log n)"
    assert generate_once.await_count == 2


@pytest.mark.asyncio
async def test_two_failures_without_explicit_phrases_return_unknown_fail_soft(
    redis: FakeCacheRedis,
) -> None:
    context = _context(description="Solve the assignment efficiently.")
    generate_once = AsyncMock(side_effect=[_failed_attempt(), _failed_attempt()])

    resolution = await _resolve(context, store=_make_demo_store(), redis=redis, generate_once=generate_once)

    assert resolution.status == "unknown"
    assert resolution.expectation is None
    assert resolution.generation_attempts == 2
    assert generate_once.await_count == 2


@pytest.mark.asyncio
async def test_generation_exception_fails_soft_with_two_attempts(
    context: AlgorithmExpectationContext,
    redis: FakeCacheRedis,
) -> None:
    resolution = await _resolve(
        context,
        store=_make_demo_store(),
        redis=redis,
        generate_once=AsyncMock(side_effect=RuntimeError("llm down")),
    )

    assert resolution.status == "unknown"
    assert resolution.expectation is None
    assert resolution.generation_attempts == 2


@pytest.mark.asyncio
async def test_one_failure_then_success_persists_expectation(
    context: AlgorithmExpectationContext,
    redis: FakeCacheRedis,
) -> None:
    generate_once = AsyncMock(
        side_effect=[_failed_attempt(), _successful_attempt()],
    )

    resolution = await _resolve(
        context,
        store=_make_demo_store(),
        redis=redis,
        generate_once=generate_once,
    )

    assert resolution.status == "available"
    assert resolution.generation_attempts == 2
    assert resolution.expectation is not None
    assert resolution.expectation.expected_complexity.source == "llm"
    assert generate_once.await_count == 2


@pytest.mark.asyncio
async def test_lock_timeout_returns_unknown_fail_soft(
    context: AlgorithmExpectationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "algorithm_expectation_lock_wait_seconds", 0)
    redis = FakeCacheRedis()
    cache_key = _cache_key(context)
    await redis.set(_lock_key(context.assignment_id, cache_key), "foreign-holder", ex=600)

    resolution = await _resolve(
        context,
        store=_make_demo_store(),
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert resolution.status == "unknown"
    assert resolution.expectation is None
    assert resolution.generation_attempts == 0


@pytest.mark.asyncio
async def test_lease_loss_before_insert_returns_unknown_without_persistence(
    context: AlgorithmExpectationContext,
    redis: FakeCacheRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.algorithm_expectations import service as service_module

    @asynccontextmanager
    async def _lease_that_loses(redis_client, assignment_id, cache_key, *, ttl_seconds=180, **kwargs):
        handle = MagicMock()
        handle.check.side_effect = AlgorithmExpectationLeaseLost("lease lost")
        yield handle

    monkeypatch.setattr(service_module, "expectation_generation_lock", _lease_that_loses)

    store = _make_demo_store()
    resolution = await _resolve(
        context,
        store=store,
        redis=redis,
        generate_once=AsyncMock(return_value=_successful_attempt()),
    )

    assert resolution.status == "unknown"
    assert resolution.expectation is None
    assert resolution.generation_attempts == 1
    assert store._container["algorithm_expectations"] == []


@pytest.mark.asyncio
async def test_lease_loss_during_insert_returns_unknown_without_persistence(
    context: AlgorithmExpectationContext,
    redis: FakeCacheRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.algorithm_expectations.cache import ExpectationGenerationLockHandle
    from backend.algorithm_expectations import service as service_module

    handle = ExpectationGenerationLockHandle("lease-token")

    @asynccontextmanager
    async def _lease_with_delayed_loss(redis_client, assignment_id, cache_key, *, ttl_seconds=180, **kwargs):
        task = asyncio.create_task(_mark_lost_after(handle, 0.02))
        try:
            yield handle
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _mark_lost_after(lock_handle: ExpectationGenerationLockHandle, delay: float) -> None:
        await asyncio.sleep(delay)
        lock_handle.mark_lost()

    base_store = _make_demo_store()

    class _DelayedInsertStore(DemoAlgorithmExpectationStore):
        async def insert_verified(self, expectation, *, lease_check=None):
            await asyncio.sleep(0.05)
            return await super().insert_verified(expectation, lease_check=lease_check)

    store = _DelayedInsertStore(base_store._container)
    monkeypatch.setattr(service_module, "expectation_generation_lock", _lease_with_delayed_loss)

    resolution = await resolve_expectation(
        context,
        store=store,
        redis=redis,
        generate_once=AsyncMock(return_value=_successful_attempt()),
    )

    assert resolution.status == "unknown"
    assert resolution.expectation is None
    assert resolution.generation_attempts == 1
    assert not store._container["algorithm_expectations"]


@pytest.mark.asyncio
async def test_insert_unique_race_recovers_winner_from_store(
    context: AlgorithmExpectationContext,
    redis: FakeCacheRedis,
) -> None:
    winner = _expectation(context, expectation_id="winner-exp", version=2)
    store = AsyncMock(spec=DemoAlgorithmExpectationStore)
    store.find_by_cache_key = AsyncMock(side_effect=[None, None, winner])
    store.reactivate_exact = AsyncMock(return_value=None)
    store.insert_verified = AsyncMock(side_effect=asyncpg.UniqueViolationError("duplicate"))

    resolution = await _resolve(
        context,
        store=store,
        redis=redis,
        generate_once=AsyncMock(return_value=_successful_attempt()),
    )

    assert resolution.status == "available"
    assert resolution.expectation is not None
    assert resolution.expectation.id == "winner-exp"
    assert resolution.expectation.version == 2


@pytest.mark.asyncio
async def test_concurrent_resolve_expectation_runs_generator_once_and_shares_id(
    context: AlgorithmExpectationContext,
) -> None:
    redis = FakeCacheRedis()
    store = _make_demo_store()
    generation_calls = 0
    release = asyncio.Event()

    async def generate_once(_ctx: AlgorithmExpectationContext) -> ExpectationAttempt:
        nonlocal generation_calls
        generation_calls += 1
        await release.wait()
        return _successful_attempt()

    task_a = asyncio.create_task(
        _resolve(context, store=store, redis=redis, generate_once=generate_once)
    )
    task_b = asyncio.create_task(
        _resolve(context, store=store, redis=redis, generate_once=generate_once)
    )

    await asyncio.sleep(0.05)
    release.set()
    resolution_a, resolution_b = await asyncio.gather(task_a, task_b)

    assert generation_calls == 1
    assert resolution_a.status == "available"
    assert resolution_b.status == "available"
    assert resolution_a.expectation is not None
    assert resolution_b.expectation is not None
    assert resolution_a.expectation.id == resolution_b.expectation.id
    assert resolution_a.expectation.version == resolution_b.expectation.version


@pytest.mark.asyncio
async def test_persist_expectation_populates_assignment_and_rubric_hashes(
    context: AlgorithmExpectationContext,
    redis: FakeCacheRedis,
) -> None:
    store = _make_demo_store()

    resolution = await _resolve(
        context,
        store=store,
        redis=redis,
        generate_once=AsyncMock(return_value=_successful_attempt()),
    )

    assert resolution.status == "available"
    assert resolution.expectation is not None
    assert resolution.expectation.assignment_hash
    assert resolution.expectation.rubric_hash
    assert resolution.expectation.assignment_hash == compute_assignment_hash(context)
    assert resolution.expectation.rubric_hash == compute_rubric_hash(context)

    stored = await store.find_by_cache_key(
        context.assignment_id, resolution.expectation.cache_key
    )
    assert stored is not None
    assert stored.assignment_hash == compute_assignment_hash(context)
    assert stored.rubric_hash == compute_rubric_hash(context)
