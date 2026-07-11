"""RED-phase tests for authoritative test selection orchestration."""

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

from backend.core.config import settings
from backend.testing.cache import (
    AssignmentTestContext,
    GenerationLockUnavailable,
    LeaseLost,
    compute_cache_identity,
)
from backend.testing.contracts import (
    AssignmentDifficulty,
    FormalTestCase,
    GeneratedTestSet,
    OracleValidation,
    TestSelection as SelectionResult,
)
from backend.testing.generator import GenerationAttemptResult
from backend.testing.store import DemoGeneratedTestSetStore

try:
    from backend.testing.selector import select_tests
except ImportError:  # pragma: no cover - RED phase
    select_tests = None  # type: ignore[assignment,misc]


def _provider_and_model() -> tuple[str, str]:
    provider = (settings.llm_provider or "ollama").strip().lower()
    if provider in {"nvidia_nim", "nim", "nvidia"}:
        return "nvidia_nim", settings.nvidia_nim_general_model
    return "ollama", settings.ollama_general_model


def _cache_key(context: AssignmentTestContext) -> str:
    provider, model = _provider_and_model()
    return compute_cache_identity(context, provider, model).cache_key


def _context(
    *,
    assignment_id: str = "assignment-1",
    title: str = "Sum Two Numbers",
    description: str = "Read two integers and print their sum.",
    rubric: list[dict] | None = None,
    difficulty: AssignmentDifficulty = "medium",
) -> AssignmentTestContext:
    return AssignmentTestContext(
        assignment_id=assignment_id,
        title=title,
        description=description,
        rubric=rubric or [{"name": "Correctness", "max_score": 100}],
        difficulty=difficulty,
    )


def _oracle() -> OracleValidation:
    return OracleValidation(
        status="verified",
        provider="ollama",
        model="qwen2.5:7b",
        schema_version="test-set-v1",
        verified_at="2026-01-01T00:00:00+00:00",
    )


def _case(
    case_id: str,
    *,
    visibility: str = "hidden",
    source: str = "auto_generated",
) -> FormalTestCase:
    return FormalTestCase(
        id=case_id,
        name=f"case-{case_id}",
        stdin=f"{case_id}\n",
        expected_stdout=f"{case_id}\n",
        visibility=visibility,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        oracle="llm_verified" if source == "auto_generated" else "teacher",
        oracle_validation=_oracle() if source == "auto_generated" else None,
    )


def _faculty_case(case_id: str = "faculty-1") -> FormalTestCase:
    return _case(case_id, visibility="public", source="manual")


def _verified_cases(
    total: int,
    *,
    public: int = 0,
    difficulty: AssignmentDifficulty = "medium",
) -> tuple[FormalTestCase, ...]:
    if public == 0 and difficulty == "medium":
        public = 2
    if public == 0 and difficulty == "easy":
        public = 1
    if public == 0 and difficulty == "hard":
        public = 2
    cases: list[FormalTestCase] = []
    for index in range(total):
        visibility = "public" if index < public else "hidden"
        cases.append(_case(str(index), visibility=visibility))
    return tuple(cases)


def _attempt_with_cases(
    total: int,
    *,
    public: int | None = None,
    difficulty: AssignmentDifficulty = "medium",
) -> GenerationAttemptResult:
    cases = _verified_cases(total, public=public or 0, difficulty=difficulty)
    return GenerationAttemptResult(
        cases=cases,
        rejected=(),
        provider="ollama",
        model="qwen2.5:7b",
        success=True,
    )


def _sufficient_medium_attempt() -> GenerationAttemptResult:
    return _attempt_with_cases(8, public=2, difficulty="medium")


def _generated_set(
    context: AssignmentTestContext,
    *,
    set_id: str = "set-1",
    active: bool = True,
    cases: tuple[FormalTestCase, ...] | None = None,
    cache_key: str | None = None,
    version: int = 1,
) -> GeneratedTestSet:
    provider, model = _provider_and_model()
    return GeneratedTestSet(
        id=set_id,
        assignment_id=context.assignment_id,
        cache_key=cache_key or _cache_key(context),
        version=version,
        difficulty=context.difficulty,
        cases=cases or _verified_cases(8, public=2, difficulty=context.difficulty),
        provider=provider,
        model=model,
        schema_version=settings.test_generation_schema_version,
        prompt_version=settings.test_generation_prompt_version,
        active=active,
    )


def _make_demo_store() -> DemoGeneratedTestSetStore:
    return DemoGeneratedTestSetStore({"generated_test_sets": []})


class FakeCacheRedis:
    """Minimal async Redis double for selector lock tests."""

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
    return f"testing:generation_lock:{assignment_id}:{cache_key}"


@pytest.fixture
def redis() -> FakeCacheRedis:
    return FakeCacheRedis()


@pytest.fixture
def context() -> AssignmentTestContext:
    return _context()


async def _select(
    context: AssignmentTestContext,
    language: str,
    *,
    load_faculty: AsyncMock | None = None,
    store: DemoGeneratedTestSetStore | AsyncMock | None = None,
    redis: FakeCacheRedis | None = None,
    generate_once: AsyncMock | None = None,
) -> SelectionResult:
    assert select_tests is not None, "backend.testing.selector.select_tests is missing"
    return await select_tests(
        context,
        language,
        load_faculty=load_faculty or AsyncMock(return_value=[]),
        store=store or _make_demo_store(),
        redis=redis or FakeCacheRedis(),
        generate_once=generate_once or AsyncMock(return_value=_sufficient_medium_attempt()),
    )


# --- Faculty priority ---


@pytest.mark.asyncio
async def test_faculty_tests_take_priority_and_suppress_generation(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    store = _make_demo_store()
    cached = _generated_set(context)
    await store.insert_verified_set(cached)

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[_faculty_case()]),
        store=store,
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert selection.source == "faculty"
    assert selection.test_evidence_status == "available"
    assert selection.cases == (_faculty_case(),)
    assert selection.generation_attempts == 0
    assert selection.test_set_id is None


@pytest.mark.asyncio
async def test_faculty_tests_suppress_cache_even_when_active_set_exists(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    store = _make_demo_store()
    cached = _generated_set(context, set_id="cached-set")
    await store.insert_verified_set(cached)

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[_faculty_case("faculty-only")]),
        store=store,
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert selection.source == "faculty"
    assert selection.cases[0].id == "faculty-only"
    assert selection.test_set_id is None


# --- Language and assignment guards ---


@pytest.mark.parametrize("language", ["cpp", "c++", "java"])
@pytest.mark.asyncio
async def test_non_python_without_faculty_returns_unavailable(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
    language: str,
) -> None:
    store = _make_demo_store()
    cached = _generated_set(context)
    await store.insert_verified_set(cached)

    selection = await _select(
        context,
        language,
        load_faculty=AsyncMock(return_value=[]),
        store=store,
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert selection.source == "none"
    assert selection.test_evidence_status == "unavailable"
    assert selection.cases == ()
    assert selection.generation_attempts == 0
    assert selection.test_set_id is None


@pytest.mark.asyncio
async def test_assignment_less_python_returns_unavailable_without_cache_or_generation(
    redis: FakeCacheRedis,
) -> None:
    context = _context(assignment_id="")
    store = _make_demo_store()
    find_mock = AsyncMock(wraps=store.find_by_cache_key)
    store.find_by_cache_key = find_mock  # type: ignore[method-assign]

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=store,
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert selection.source == "none"
    assert selection.test_evidence_status == "unavailable"
    assert selection.cases == ()
    assert selection.generation_attempts == 0
    find_mock.assert_not_called()


# --- Cache hits and reactivation ---


@pytest.mark.asyncio
async def test_active_exact_cache_hit_is_used_without_generation(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    store = _make_demo_store()
    cached = _generated_set(context, set_id="active-set", version=3)
    store._container["generated_test_sets"].append(
        {
            "id": cached.id,
            "assignment_id": cached.assignment_id,
            "cache_key": cached.cache_key,
            "version": 3,
            "difficulty": cached.difficulty,
            "cases": [case.model_dump() for case in cached.cases],
            "provider": cached.provider,
            "model": cached.model,
            "schema_version": cached.schema_version,
            "prompt_version": cached.prompt_version,
            "assignment_hash": "",
            "rubric_hash": "",
            "oracle_validation": [],
            "active": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "deactivated_at": None,
        }
    )

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=store,
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert selection.source == "auto_generated"
    assert selection.test_evidence_status == "available"
    assert selection.test_set_id == "active-set"
    assert selection.cache_key == cached.cache_key
    assert selection.cache_version == 3
    assert selection.generation_attempts == 0
    assert len(selection.cases) == 8


@pytest.mark.asyncio
async def test_inactive_exact_cache_is_reactivated_when_faculty_empty(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    store = _make_demo_store()
    cache_key = _cache_key(context)
    inactive = _generated_set(context, set_id="inactive-set", active=False, cache_key=cache_key)
    store._container["generated_test_sets"].append(
        {
            "id": inactive.id,
            "assignment_id": inactive.assignment_id,
            "cache_key": inactive.cache_key,
            "version": inactive.version,
            "difficulty": inactive.difficulty,
            "cases": [case.model_dump() for case in inactive.cases],
            "provider": inactive.provider,
            "model": inactive.model,
            "schema_version": inactive.schema_version,
            "prompt_version": inactive.prompt_version,
            "assignment_hash": "",
            "rubric_hash": "",
            "oracle_validation": [],
            "active": False,
            "created_at": "2026-01-01T00:00:00+00:00",
            "deactivated_at": "2026-01-02T00:00:00+00:00",
        }
    )

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=store,
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert selection.source == "auto_generated"
    assert selection.test_evidence_status == "available"
    assert selection.test_set_id == "inactive-set"
    assert selection.generation_attempts == 0
    reactivated = await store.find_by_cache_key(context.assignment_id, cache_key)
    assert reactivated is not None
    assert reactivated.active is True


@pytest.mark.asyncio
async def test_stale_inactive_cache_key_is_not_reactivated(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    store = _make_demo_store()
    stale_key = "0" * 64
    stale = _generated_set(context, set_id="stale-set", active=False, cache_key=stale_key)
    store._container["generated_test_sets"].append(
        {
            "id": stale.id,
            "assignment_id": stale.assignment_id,
            "cache_key": stale.cache_key,
            "version": stale.version,
            "difficulty": stale.difficulty,
            "cases": [case.model_dump() for case in stale.cases],
            "provider": stale.provider,
            "model": stale.model,
            "schema_version": stale.schema_version,
            "prompt_version": stale.prompt_version,
            "assignment_hash": "",
            "rubric_hash": "",
            "oracle_validation": [],
            "active": False,
            "created_at": "2026-01-01T00:00:00+00:00",
            "deactivated_at": "2026-01-02T00:00:00+00:00",
        }
    )

    winner = _generated_set(context, set_id="fresh-set")
    generate_once = AsyncMock(return_value=_sufficient_medium_attempt())

    async def insert_and_return(test_set: GeneratedTestSet) -> GeneratedTestSet:
        return await DemoGeneratedTestSetStore(store._container).insert_verified_set(
            winner.model_copy(update={"id": test_set.id, "cases": test_set.cases})
        )

    store.insert_verified_set = insert_and_return  # type: ignore[method-assign]

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=store,
        redis=redis,
        generate_once=generate_once,
    )

    assert selection.source == "auto_generated"
    assert selection.test_set_id != "stale-set"
    assert generate_once.await_count == 1
    stale_row = await store.find_by_cache_key(context.assignment_id, stale_key)
    assert stale_row is not None
    assert stale_row.active is False


# --- Generation attempts and fail-soft ---


@pytest.mark.asyncio
async def test_two_insufficient_attempts_return_unavailable_with_empty_cases(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    generate_once = AsyncMock(
        side_effect=[
            _attempt_with_cases(3),
            _attempt_with_cases(2),
        ]
    )

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=_make_demo_store(),
        redis=redis,
        generate_once=generate_once,
    )

    assert selection.test_evidence_status == "unavailable"
    assert selection.source == "none"
    assert selection.cases == ()
    assert selection.generation_attempts == 2
    assert generate_once.await_count == 2


@pytest.mark.asyncio
async def test_one_insufficient_then_sufficient_attempt_persists_set(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    generate_once = AsyncMock(
        side_effect=[
            _attempt_with_cases(3),
            _sufficient_medium_attempt(),
        ]
    )

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=_make_demo_store(),
        redis=redis,
        generate_once=generate_once,
    )

    assert selection.test_evidence_status == "available"
    assert selection.source == "auto_generated"
    assert selection.generation_attempts == 2
    assert selection.test_set_id is not None
    assert len(selection.cases) == 8
    assert generate_once.await_count == 2


@pytest.mark.asyncio
async def test_lock_timeout_returns_unavailable_fail_soft(
    context: AssignmentTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "test_generation_lock_wait_seconds", 0)
    redis = FakeCacheRedis()
    cache_key = _cache_key(context)
    await redis.set(_lock_key(context.assignment_id, cache_key), "foreign-holder", ex=600)

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=_make_demo_store(),
        redis=redis,
        generate_once=AsyncMock(side_effect=AssertionError("must not run")),
    )

    assert selection.test_evidence_status == "unavailable"
    assert selection.source == "none"
    assert selection.cases == ()
    assert selection.generation_attempts == 0


@pytest.mark.asyncio
async def test_lease_loss_before_insert_returns_unavailable_fail_soft(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.testing import selector as selector_module

    @asynccontextmanager
    async def _lease_that_loses(redis_client, assignment_id, cache_key, *, ttl_seconds=180, **kwargs):
        handle = MagicMock()
        handle.check.side_effect = LeaseLost("lease lost")
        yield handle

    monkeypatch.setattr(selector_module, "generation_lock", _lease_that_loses)

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=_make_demo_store(),
        redis=redis,
        generate_once=AsyncMock(return_value=_sufficient_medium_attempt()),
    )

    assert selection.test_evidence_status == "unavailable"
    assert selection.source == "none"
    assert selection.cases == ()
    assert selection.generation_attempts == 1


@pytest.mark.asyncio
async def test_lease_loss_during_insert_returns_unavailable_fail_soft(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.testing.cache import GenerationLockHandle
    from backend.testing import selector as selector_module

    handle = GenerationLockHandle("lease-token")

    @asynccontextmanager
    async def _lease_with_delayed_loss(redis_client, assignment_id, cache_key, *, ttl_seconds=180, **kwargs):
        task = asyncio.create_task(_mark_lost_after(handle, 0.02))
        try:
            yield handle
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _mark_lost_after(lock_handle: GenerationLockHandle, delay: float) -> None:
        await asyncio.sleep(delay)
        lock_handle.mark_lost()

    base_store = _make_demo_store()

    class _DelayedInsertStore(DemoGeneratedTestSetStore):
        async def insert_verified_set(self, test_set, *, lease_check=None):
            await asyncio.sleep(0.05)
            return await super().insert_verified_set(test_set, lease_check=lease_check)

    store = _DelayedInsertStore(base_store._container)

    monkeypatch.setattr(selector_module, "generation_lock", _lease_with_delayed_loss)

    selection = await select_tests(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=store,
        redis=redis,
        generate_once=AsyncMock(return_value=_sufficient_medium_attempt()),
    )

    assert selection.test_evidence_status == "unavailable"
    assert selection.source == "none"
    assert selection.cases == ()
    assert selection.generation_attempts == 1
    assert not store._container["generated_test_sets"]


@pytest.mark.asyncio
async def test_insert_unique_race_recovers_winner_from_store(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    winner = _generated_set(context, set_id="winner-set", version=2)
    store = AsyncMock(spec=DemoGeneratedTestSetStore)
    store.find_by_cache_key = AsyncMock(side_effect=[None, None, winner])
    store.reactivate_exact = AsyncMock(return_value=None)
    store.insert_verified_set = AsyncMock(side_effect=asyncpg.UniqueViolationError("duplicate"))

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=store,
        redis=redis,
        generate_once=AsyncMock(return_value=_sufficient_medium_attempt()),
    )

    assert selection.test_evidence_status == "available"
    assert selection.source == "auto_generated"
    assert selection.test_set_id == "winner-set"
    assert selection.cache_version == 2
    assert store.find_by_cache_key.await_count >= 2


@pytest.mark.asyncio
async def test_generation_exception_fails_soft_to_unavailable(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=_make_demo_store(),
        redis=redis,
        generate_once=AsyncMock(side_effect=RuntimeError("llm down")),
    )

    assert selection.test_evidence_status == "unavailable"
    assert selection.source == "none"
    assert selection.cases == ()
    assert selection.generation_attempts == 1


# --- Concurrency ---


@pytest.mark.asyncio
async def test_concurrent_select_tests_runs_generator_once_and_shares_set_id(
    context: AssignmentTestContext,
) -> None:
    redis = FakeCacheRedis()
    store = _make_demo_store()
    generation_calls = 0
    release = asyncio.Event()

    async def generate_once(_ctx: AssignmentTestContext) -> GenerationAttemptResult:
        nonlocal generation_calls
        generation_calls += 1
        await release.wait()
        return _sufficient_medium_attempt()

    task_a = asyncio.create_task(
        _select(
            context,
            "python",
            load_faculty=AsyncMock(return_value=[]),
            store=store,
            redis=redis,
            generate_once=generate_once,
        )
    )
    task_b = asyncio.create_task(
        _select(
            context,
            "python",
            load_faculty=AsyncMock(return_value=[]),
            store=store,
            redis=redis,
            generate_once=generate_once,
        )
    )

    await asyncio.sleep(0.05)
    release.set()
    selection_a, selection_b = await asyncio.gather(task_a, task_b)

    assert generation_calls == 1
    assert selection_a.test_evidence_status == "available"
    assert selection_b.test_evidence_status == "available"
    assert selection_a.test_set_id == selection_b.test_set_id
    assert selection_a.cache_key == selection_b.cache_key


# --- Count policy selection shape ---


@pytest.mark.asyncio
async def test_selected_cases_keep_public_hidden_ratio_for_medium(
    context: AssignmentTestContext,
    redis: FakeCacheRedis,
) -> None:
    cases = _verified_cases(10, public=3, difficulty="medium")
    attempt = GenerationAttemptResult(
        cases=cases,
        rejected=(),
        provider="ollama",
        model="qwen2.5:7b",
        success=True,
    )

    selection = await _select(
        context,
        "python",
        load_faculty=AsyncMock(return_value=[]),
        store=_make_demo_store(),
        redis=redis,
        generate_once=AsyncMock(return_value=attempt),
    )

    public_cases = [case for case in selection.cases if case.visibility == "public"]
    hidden_cases = [case for case in selection.cases if case.visibility == "hidden"]
    assert len(selection.cases) == 8
    assert len(public_cases) == 2
    assert len(hidden_cases) == 6
    assert [case.id for case in public_cases] == ["0", "1"]
    assert [case.id for case in hidden_cases] == ["3", "4", "5", "6", "7", "8"]
