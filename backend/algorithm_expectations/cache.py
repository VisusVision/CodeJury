from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from backend.algorithm_expectations.contracts import (
    AlgorithmExpectationContext,
    ExpectationCacheIdentity,
)
from backend.core.config import settings

__all__ = [
    "AlgorithmExpectationContext",
    "AlgorithmExpectationLeaseLost",
    "ExpectationCacheIdentity",
    "ExpectationGenerationLockUnavailable",
    "ExpectationGenerationLockHandle",
    "acquire_expectation_generation_lock",
    "compute_assignment_hash",
    "compute_expectation_identity",
    "compute_rubric_hash",
    "expectation_generation_lock",
    "release_expectation_generation_lock",
]

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""

_EXTEND_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("expire", KEYS[1], ARGV[2])
end
return 0
"""


class ExpectationGenerationLockUnavailable(Exception):
    """Raised when an expectation generation lock cannot be acquired."""


class AlgorithmExpectationLeaseLost(Exception):
    """Raised when a held expectation generation lock lease is lost."""


class ExpectationGenerationLockHandle:
    def __init__(self, token: str) -> None:
        self.token = token
        self._lost = asyncio.Event()

    def mark_lost(self) -> None:
        self._lost.set()

    def check(self) -> None:
        if self._lost.is_set():
            raise AlgorithmExpectationLeaseLost(
                "expectation generation lock lease was lost before this operation completed; aborting fail-closed"
            )


def _expectation_lock_key(assignment_id: str, cache_key: str) -> str:
    return f"algorithm:expectation_lock:{assignment_id}:{cache_key}"


def compute_assignment_hash(context: AlgorithmExpectationContext) -> str:
    canonical = json.dumps(
        {"title": context.title, "description": context.description},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_rubric_hash(context: AlgorithmExpectationContext) -> str:
    canonical = json.dumps(context.rubric, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_expectation_identity(
    context: AlgorithmExpectationContext, provider: str, model: str
) -> ExpectationCacheIdentity:
    payload = {
        "title": context.title,
        "description": context.description,
        "rubric": context.rubric,
        "difficulty": context.difficulty,
        "provider": provider,
        "model": model,
        "schema_version": settings.algorithm_expectation_schema_version,
        "extractor_prompt_version": settings.algorithm_expectation_extractor_prompt_version,
        "verifier_prompt_version": settings.algorithm_expectation_verifier_prompt_version,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    cache_key = hashlib.sha256(canonical.encode()).hexdigest()
    return ExpectationCacheIdentity(cache_key=cache_key)


async def acquire_expectation_generation_lock(
    redis,
    assignment_id: str,
    cache_key: str,
    *,
    ttl_seconds: int = 180,
    max_attempts: int = 1,
    retry_delay_seconds: float = 0.05,
) -> str:
    key = _expectation_lock_key(assignment_id, cache_key)
    token = secrets.token_urlsafe(16)
    for attempt in range(max_attempts):
        try:
            acquired = await redis.set(key, token, nx=True, ex=ttl_seconds)
        except Exception as exc:
            raise ExpectationGenerationLockUnavailable(
                f"redis error acquiring expectation generation lock for {assignment_id}:{cache_key}"
            ) from exc
        if acquired:
            return token
        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_delay_seconds)
    raise ExpectationGenerationLockUnavailable(
        f"expectation generation lock contention exhausted for {assignment_id}:{cache_key}"
    )


async def release_expectation_generation_lock(
    redis, assignment_id: str, cache_key: str, token: str
) -> None:
    key = _expectation_lock_key(assignment_id, cache_key)
    try:
        await redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)
    except Exception:
        pass


async def _renew_expectation_generation_lock_periodically(
    redis,
    key: str,
    token: str,
    ttl_seconds: int,
    interval_seconds: float,
    handle: ExpectationGenerationLockHandle,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            renewed = await redis.eval(_EXTEND_LOCK_SCRIPT, 1, key, token, ttl_seconds)
        except Exception:
            handle.mark_lost()
            return
        if not renewed:
            handle.mark_lost()
            return


@asynccontextmanager
async def expectation_generation_lock(
    redis,
    assignment_id: str,
    cache_key: str,
    *,
    ttl_seconds: int = 180,
    wait_seconds: float | None = None,
    poll_seconds: float = 0.2,
):
    if wait_seconds is not None and wait_seconds > 0:
        max_attempts = max(1, int(wait_seconds / poll_seconds))
        retry_delay_seconds = poll_seconds
    else:
        max_attempts = 1
        retry_delay_seconds = 0.05

    token = await acquire_expectation_generation_lock(
        redis,
        assignment_id,
        cache_key,
        ttl_seconds=ttl_seconds,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )
    key = _expectation_lock_key(assignment_id, cache_key)
    handle = ExpectationGenerationLockHandle(token)
    renew_interval = max(ttl_seconds / 3, 0.01)
    renew_task = asyncio.create_task(
        _renew_expectation_generation_lock_periodically(
            redis, key, token, ttl_seconds, renew_interval, handle
        )
    )
    try:
        yield handle
    finally:
        renew_task.cancel()
        try:
            await renew_task
        except asyncio.CancelledError:
            pass
        await release_expectation_generation_lock(redis, assignment_id, cache_key, token)
