"""RED-phase tests for generated-test cache identity and Redis generation locks."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from backend.testing.cache import (
    AssignmentTestContext,
    GenerationLockUnavailable,
    LeaseLost,
    acquire_generation_lock,
    compute_cache_identity,
    generation_lock,
    release_generation_lock,
)
from backend.testing.contracts import AssignmentDifficulty

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""


def _lock_key(assignment_id: str, cache_key: str) -> str:
    return f"testing:generation_lock:{assignment_id}:{cache_key}"


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


class FakeCacheRedis:
    """In-memory async Redis double for generation-lock lease tests."""

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

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        self._expires_at.pop(key, None)

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


class _RenewalFailCacheRedis(FakeCacheRedis):
    """Fake Redis that can force renewal EVAL to fail deterministically."""

    def __init__(
        self,
        *,
        renewal_result: int | None = None,
        renewal_error: Exception | None = None,
    ) -> None:
        super().__init__()
        self._renewal_result = renewal_result
        self._renewal_error = renewal_error
        self.renewal_eval_calls = 0

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any):
        if "expire" in script:
            self.renewal_eval_calls += 1
            if self._renewal_error is not None:
                raise self._renewal_error
            if self._renewal_result is not None:
                return self._renewal_result
        return await super().eval(script, numkeys, *keys_and_args)


async def _wait_until(predicate, *, timeout: float = 1.0, interval: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met before timeout")


@pytest.fixture
def redis() -> FakeCacheRedis:
    return FakeCacheRedis()


# --- Canonical hash tests ---


def test_cache_key_is_stable_for_reordered_rubric_keys() -> None:
    first = _context(rubric=[{"name": "A", "max_score": 50}])
    second = _context(rubric=[{"max_score": 50, "name": "A"}])
    assert compute_cache_identity(first, "ollama", "qwen").cache_key == compute_cache_identity(
        second, "ollama", "qwen"
    ).cache_key


def test_cache_key_changes_for_prompt_model_or_difficulty() -> None:
    keys = {
        compute_cache_identity(_context(difficulty=difficulty), provider, model).cache_key
        for difficulty, provider, model in [
            ("easy", "ollama", "qwen"),
            ("hard", "ollama", "qwen"),
            ("hard", "nvidia_nim", "qwen"),
        ]
    }
    assert len(keys) == 3


def test_cache_key_changes_for_different_title_or_description() -> None:
    base = _context()
    different_title = _context(title="Multiply Two Numbers")
    different_description = _context(description="Read two integers and print their product.")

    base_key = compute_cache_identity(base, "ollama", "qwen").cache_key
    assert compute_cache_identity(different_title, "ollama", "qwen").cache_key != base_key
    assert compute_cache_identity(different_description, "ollama", "qwen").cache_key != base_key


def test_cache_key_is_64_hex_chars() -> None:
    identity = compute_cache_identity(_context(), "ollama", "qwen")
    assert len(identity.cache_key) == 64
    assert all(ch in "0123456789abcdef" for ch in identity.cache_key)


def test_compute_cache_identity_has_no_student_code_parameter() -> None:
    varnames = compute_cache_identity.__code__.co_varnames
    assert "student_code" not in varnames
    assert "source_code" not in varnames


# --- Redis lease tests ---


@pytest.mark.asyncio
async def test_generation_lock_blocks_concurrent_acquire_for_same_key(redis: FakeCacheRedis) -> None:
    assignment_id = "assignment-lock-1"
    cache_key = "b" * 64
    async with generation_lock(redis, assignment_id, cache_key, ttl_seconds=10) as first:
        assert first.token
        with pytest.raises(GenerationLockUnavailable):
            await acquire_generation_lock(
                redis,
                assignment_id,
                cache_key,
                ttl_seconds=10,
                max_attempts=1,
                retry_delay_seconds=0.01,
            )


@pytest.mark.asyncio
async def test_generation_lock_allows_different_keys_concurrently(redis: FakeCacheRedis) -> None:
    assignment_id = "assignment-lock-2"
    cache_key_a = "c" * 64
    cache_key_b = "d" * 64
    async with generation_lock(redis, assignment_id, cache_key_a, ttl_seconds=10) as first:
        async with generation_lock(redis, assignment_id, cache_key_b, ttl_seconds=10) as second:
            assert first.token != second.token
            assert await redis.get(_lock_key(assignment_id, cache_key_a)) == first.token
            assert await redis.get(_lock_key(assignment_id, cache_key_b)) == second.token


@pytest.mark.asyncio
async def test_generation_lock_owner_only_release(redis: FakeCacheRedis) -> None:
    assignment_id = "assignment-lock-3"
    cache_key = "e" * 64
    key = _lock_key(assignment_id, cache_key)

    token = await acquire_generation_lock(redis, assignment_id, cache_key, ttl_seconds=10)
    assert await redis.get(key) == token

    foreign_deleted = await redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, "foreign-token")
    assert foreign_deleted == 0
    assert await redis.get(key) == token

    await release_generation_lock(redis, assignment_id, cache_key, token)
    assert key not in redis.values

    new_token = await acquire_generation_lock(
        redis,
        assignment_id,
        cache_key,
        ttl_seconds=10,
        max_attempts=1,
    )
    assert new_token
    await release_generation_lock(redis, assignment_id, cache_key, new_token)


@pytest.mark.asyncio
async def test_generation_lock_renewal_extends_beyond_original_ttl(redis: FakeCacheRedis) -> None:
    assignment_id = "assignment-lock-4"
    cache_key = "f" * 64
    key = _lock_key(assignment_id, cache_key)
    ttl_seconds = 1

    async with generation_lock(redis, assignment_id, cache_key, ttl_seconds=ttl_seconds) as handle:
        await asyncio.sleep(0.35)
        handle.check()
        assert key in redis.values
        assert await redis.get(key) == handle.token

        with pytest.raises(GenerationLockUnavailable):
            await acquire_generation_lock(
                redis,
                assignment_id,
                cache_key,
                ttl_seconds=ttl_seconds,
                max_attempts=1,
            )

        await asyncio.sleep(0.75)
        handle.check()
        assert key in redis.values
        assert await redis.get(key) == handle.token


@pytest.mark.asyncio
async def test_generation_lock_marks_lost_when_renewal_fails() -> None:
    redis = _RenewalFailCacheRedis(renewal_result=0)
    assignment_id = "assignment-lock-5"
    cache_key = "0" * 64

    async with generation_lock(redis, assignment_id, cache_key, ttl_seconds=0.2) as handle:
        await _wait_until(lambda: redis.renewal_eval_calls >= 1)
        with pytest.raises(LeaseLost):
            handle.check()


@pytest.mark.asyncio
async def test_generation_lock_check_before_use_after_loss_raises() -> None:
    redis = _RenewalFailCacheRedis(renewal_result=0)
    assignment_id = "assignment-lock-6"
    cache_key = "1" * 64

    async with generation_lock(redis, assignment_id, cache_key, ttl_seconds=0.2) as handle:
        await _wait_until(lambda: redis.renewal_eval_calls >= 1)
        with pytest.raises(LeaseLost):
            handle.check()
        with pytest.raises(LeaseLost):
            handle.check()
