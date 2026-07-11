from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass

from backend.testing.contracts import AssignmentDifficulty

_SCHEMA_VERSION = "test-set-v1"
_GENERATOR_PROMPT_VERSION = "test-generator-v1"
_VERIFIER_PROMPT_VERSION = "test-verifier-v1"

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


@dataclass(frozen=True)
class AssignmentTestContext:
    assignment_id: str
    title: str
    description: str
    rubric: list[dict]
    difficulty: AssignmentDifficulty


@dataclass(frozen=True)
class CacheIdentity:
    cache_key: str


class GenerationLockUnavailable(Exception):
    """Raised when a generation lock cannot be acquired (contention exhausted)."""


class LeaseLost(Exception):
    """Raised when a held generation lock lease is lost before the guarded operation completes."""


class GenerationLockHandle:
    def __init__(self, token: str) -> None:
        self.token = token
        self._lost = asyncio.Event()

    def mark_lost(self) -> None:
        self._lost.set()

    def check(self) -> None:
        if self._lost.is_set():
            raise LeaseLost(
                "generation lock lease was lost before this operation completed; aborting fail-closed"
            )


def _generation_lock_key(assignment_id: str, cache_key: str) -> str:
    return f"testing:generation_lock:{assignment_id}:{cache_key}"


def compute_cache_identity(
    context: AssignmentTestContext, provider: str, model: str
) -> CacheIdentity:
    payload = {
        "title": context.title,
        "description": context.description,
        "rubric": context.rubric,
        "difficulty": context.difficulty,
        "provider": provider,
        "model": model,
        "schema_version": _SCHEMA_VERSION,
        "generator_prompt_version": _GENERATOR_PROMPT_VERSION,
        "verifier_prompt_version": _VERIFIER_PROMPT_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    cache_key = hashlib.sha256(canonical.encode()).hexdigest()
    return CacheIdentity(cache_key=cache_key)


async def acquire_generation_lock(
    redis,
    assignment_id: str,
    cache_key: str,
    *,
    ttl_seconds: int = 180,
    max_attempts: int = 1,
    retry_delay_seconds: float = 0.05,
) -> str:
    key = _generation_lock_key(assignment_id, cache_key)
    token = secrets.token_urlsafe(16)
    for attempt in range(max_attempts):
        try:
            acquired = await redis.set(key, token, nx=True, ex=ttl_seconds)
        except Exception as exc:
            raise GenerationLockUnavailable(
                f"redis error acquiring generation lock for {assignment_id}:{cache_key}"
            ) from exc
        if acquired:
            return token
        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_delay_seconds)
    raise GenerationLockUnavailable(
        f"generation lock contention exhausted for {assignment_id}:{cache_key}"
    )


async def release_generation_lock(
    redis, assignment_id: str, cache_key: str, token: str
) -> None:
    key = _generation_lock_key(assignment_id, cache_key)
    try:
        await redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)
    except Exception:
        pass


async def _renew_generation_lock_periodically(
    redis,
    key: str,
    token: str,
    ttl_seconds: int,
    interval_seconds: float,
    handle: GenerationLockHandle,
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
async def generation_lock(
    redis, assignment_id: str, cache_key: str, *, ttl_seconds: int = 180
):
    token = await acquire_generation_lock(
        redis, assignment_id, cache_key, ttl_seconds=ttl_seconds, max_attempts=1
    )
    key = _generation_lock_key(assignment_id, cache_key)
    handle = GenerationLockHandle(token)
    renew_interval = max(ttl_seconds / 3, 0.01)
    renew_task = asyncio.create_task(
        _renew_generation_lock_periodically(
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
        await release_generation_lock(redis, assignment_id, cache_key, token)
