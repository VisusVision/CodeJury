from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Protocol

from backend.auth.models import AuthPrincipal, AuthRole, IssuedSession, SessionRecord

_VALID_ROLES: frozenset[str] = frozenset({"student", "teacher"})


class UserLockUnavailable(Exception):
    """Raised when a per-user auth lock cannot be acquired (Redis failure or contention exhausted)."""


class LockLost(UserLockUnavailable):
    """Raised when a held per-user lock lease is lost before the guarded operation completes."""


class UserLockHandle:
    """Yielded by user_lock(). Callers MUST call check() immediately before any
    security-critical persistence step (e.g. issuing a session, writing a password
    hash, revoking sessions) so a lost lease aborts the operation instead of silently
    continuing without exclusivity."""

    def __init__(self, token: str) -> None:
        self.token = token
        self._lost = asyncio.Event()

    def mark_lost(self) -> None:
        self._lost.set()

    def check(self) -> None:
        if self._lost.is_set():
            raise LockLost(
                "per-user lock lease was lost before this operation completed; aborting fail-closed"
            )


_USER_LOCK_PREFIX = "auth:userlock:"

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

_LOCKED_SESSION_WRITE_SCRIPT = """
if redis.call("get", KEYS[1]) ~= ARGV[1] then
  return 0
end
redis.call("set", KEYS[2], ARGV[2], "EX", ARGV[3])
redis.call("sadd", KEYS[3], ARGV[4])
redis.call("expire", KEYS[3], ARGV[3])
return 1
"""

_LOCKED_REVOKE_SCRIPT = """
if redis.call("get", KEYS[1]) ~= ARGV[1] then
  return -1
end
local members = redis.call("smembers", KEYS[2])
local deleted = 0
for _, member in ipairs(members) do
  local removed = redis.call("del", ARGV[2] .. member)
  if removed == 1 then
    deleted = deleted + 1
  end
end
redis.call("del", KEYS[2])
return deleted
"""


def _user_lock_key(role: str, user_id: str) -> str:
    return f"{_USER_LOCK_PREFIX}{role}:{user_id}"


async def acquire_user_lock(
    redis,
    role: str,
    user_id: str,
    *,
    ttl_seconds: int = 10,
    max_attempts: int = 40,
    retry_delay_seconds: float = 0.05,
) -> str:
    """Acquire a short-TTL per-user lock (SET NX EX pattern). Returns a unique owner token that
    MUST be passed to release_user_lock to release it. Retries on contention up to max_attempts
    with a short delay between attempts. Raises UserLockUnavailable if the Redis call itself fails,
    or if contention is never resolved within max_attempts (fail closed in both cases — callers must
    turn this into an HTTP 503, never proceed as if the lock were held)."""
    key = _user_lock_key(role, user_id)
    token = secrets.token_urlsafe(16)
    for attempt in range(max_attempts):
        try:
            acquired = await redis.set(key, token, nx=True, ex=ttl_seconds)
        except Exception as exc:
            raise UserLockUnavailable(f"redis error acquiring lock for {role}:{user_id}") from exc
        if acquired:
            return token
        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_delay_seconds)
    raise UserLockUnavailable(f"lock contention exhausted for {role}:{user_id}")


async def release_user_lock(redis, role: str, user_id: str, token: str) -> None:
    """Release the lock ONLY if it is still owned by this exact token (atomic compare-and-delete
    via a single Lua EVAL — one Redis command, no TOCTOU window between read and delete).
    Swallows Redis errors here (best-effort on release; the TTL is the ultimate safety net if release
    fails for any reason — do NOT raise from this function, callers rely on it being safe to await
    unconditionally in a `finally` block)."""
    key = _user_lock_key(role, user_id)
    try:
        await redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)
    except Exception:
        pass


async def _renew_user_lock_periodically(
    redis,
    key: str,
    token: str,
    ttl_seconds: int,
    interval_seconds: float,
    handle: UserLockHandle,
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
async def user_lock(redis, role: str, user_id: str, *, ttl_seconds: int = 10):
    token = await acquire_user_lock(redis, role, user_id, ttl_seconds=ttl_seconds)
    key = _user_lock_key(role, user_id)
    handle = UserLockHandle(token)
    renew_interval = max(ttl_seconds / 3, 0.01)
    renew_task = asyncio.create_task(
        _renew_user_lock_periodically(
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
        await release_user_lock(redis, role, user_id, token)


class RedisLike(Protocol):
    def set(self, key: str, value: str, ex: int | None = None) -> Awaitable[Any]: ...
    def get(self, key: str) -> Awaitable[Any]: ...
    def delete(self, key: str) -> Awaitable[Any]: ...
    def sadd(self, key: str, *values: str) -> Awaitable[Any]: ...
    def smembers(self, key: str) -> Awaitable[set[Any]]: ...
    def srem(self, key: str, *values: str) -> Awaitable[Any]: ...
    def expire(self, key: str, seconds: int) -> Awaitable[Any]: ...
    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Awaitable[Any]: ...


_SESSION_KEY_PREFIX = "auth:session:"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _session_key(session_hash: str) -> str:
    return f"{_SESSION_KEY_PREFIX}{session_hash}"


def _user_index_key(user_id: str, role: AuthRole) -> str:
    return f"auth:user_sessions:{role}:{user_id}"


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_session_record(raw: Any) -> SessionRecord | None:
    raw = _decode(raw)
    if raw in (None, ""):
        return None
    try:
        data = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    user_id = data.get("user_id")
    role = data.get("role")
    csrf_hash = data.get("csrf_hash")
    created_at = data.get("created_at")
    if not isinstance(user_id, str) or not user_id:
        return None
    if not isinstance(role, str) or role not in _VALID_ROLES:
        return None
    if not isinstance(csrf_hash, str) or not csrf_hash:
        return None
    if not isinstance(created_at, str) or not created_at:
        return None

    return SessionRecord(
        user_id=user_id,
        role=role,  # type: ignore[arg-type]
        csrf_hash=csrf_hash,
        created_at=created_at,
    )


class SessionStore:
    def __init__(self, redis: RedisLike, *, ttl_seconds: int = 28800) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def create_session(self, user_id: str, role: AuthRole) -> IssuedSession:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        session_hash = hash_token(session_token)
        csrf_hash = hash_token(csrf_token)
        created_at = _utc_now_iso()

        record = SessionRecord(
            user_id=user_id,
            role=role,
            csrf_hash=csrf_hash,
            created_at=created_at,
        )
        session_key = _session_key(session_hash)
        index_key = _user_index_key(user_id, role)

        await self.redis.set(session_key, _json_dumps(asdict(record)), ex=self.ttl_seconds)
        await self.redis.sadd(index_key, session_hash)
        await self.redis.expire(index_key, self.ttl_seconds)

        principal = AuthPrincipal(
            user_id=user_id,
            role=role,
            session_hash=session_hash,
            csrf_hash=csrf_hash,
        )
        return IssuedSession(
            session_token=session_token,
            csrf_token=csrf_token,
            principal=principal,
        )

    async def create_session_if_lock_held(
        self, user_id: str, role: AuthRole, lock_token: str
    ) -> IssuedSession:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        session_hash = hash_token(session_token)
        csrf_hash = hash_token(csrf_token)
        created_at = _utc_now_iso()

        record = SessionRecord(
            user_id=user_id,
            role=role,
            csrf_hash=csrf_hash,
            created_at=created_at,
        )
        lock_key = _user_lock_key(role, user_id)
        session_key = _session_key(session_hash)
        index_key = _user_index_key(user_id, role)

        try:
            written = await self.redis.eval(
                _LOCKED_SESSION_WRITE_SCRIPT,
                3,
                lock_key,
                session_key,
                index_key,
                lock_token,
                _json_dumps(asdict(record)),
                self.ttl_seconds,
                session_hash,
            )
        except Exception as exc:
            raise UserLockUnavailable(
                f"redis error creating session under lock for {role}:{user_id}"
            ) from exc

        if not written:
            raise LockLost(
                "per-user lock lease was lost before session write; aborting fail-closed"
            )

        principal = AuthPrincipal(
            user_id=user_id,
            role=role,
            session_hash=session_hash,
            csrf_hash=csrf_hash,
        )
        return IssuedSession(
            session_token=session_token,
            csrf_token=csrf_token,
            principal=principal,
        )

    async def read_session(self, raw_token: str) -> AuthPrincipal | None:
        session_hash = hash_token(raw_token)
        raw = await self.redis.get(_session_key(session_hash))
        record = _parse_session_record(raw)
        if record is None:
            return None
        return AuthPrincipal(
            user_id=record.user_id,
            role=record.role,
            session_hash=session_hash,
            csrf_hash=record.csrf_hash,
        )

    async def revoke_session(self, raw_token: str) -> None:
        session_hash = hash_token(raw_token)
        session_key = _session_key(session_hash)
        raw = await self.redis.get(session_key)
        record = _parse_session_record(raw)

        await self.redis.delete(session_key)

        if record is not None:
            index_key = _user_index_key(record.user_id, record.role)
            await self.redis.srem(index_key, session_hash)

    async def revoke_user_sessions(self, user_id: str, role: AuthRole) -> int:
        index_key = _user_index_key(user_id, role)
        members = await self.redis.smembers(index_key)
        deleted_count = 0

        for member in members:
            session_hash = _decode(member)
            if not isinstance(session_hash, str) or not session_hash:
                continue
            session_key = _session_key(session_hash)
            if await self.redis.get(session_key) is not None:
                await self.redis.delete(session_key)
                deleted_count += 1

        await self.redis.delete(index_key)
        return deleted_count

    async def revoke_user_sessions_if_lock_held(
        self, user_id: str, role: AuthRole, lock_token: str
    ) -> int:
        lock_key = _user_lock_key(role, user_id)
        index_key = _user_index_key(user_id, role)

        try:
            deleted = await self.redis.eval(
                _LOCKED_REVOKE_SCRIPT,
                2,
                lock_key,
                index_key,
                lock_token,
                _SESSION_KEY_PREFIX,
            )
        except Exception as exc:
            raise UserLockUnavailable(
                f"redis error revoking sessions under lock for {role}:{user_id}"
            ) from exc

        if deleted == -1:
            raise LockLost(
                "per-user lock lease was lost before session revoke; aborting fail-closed"
            )

        return int(deleted)
