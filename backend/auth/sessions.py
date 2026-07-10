from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Protocol

from backend.auth.models import AuthPrincipal, AuthRole, IssuedSession, SessionRecord

_VALID_ROLES: frozenset[str] = frozenset({"student", "teacher"})


class RedisLike(Protocol):
    def set(self, key: str, value: str, ex: int | None = None) -> Awaitable[Any]: ...
    def get(self, key: str) -> Awaitable[Any]: ...
    def delete(self, key: str) -> Awaitable[Any]: ...
    def sadd(self, key: str, *values: str) -> Awaitable[Any]: ...
    def smembers(self, key: str) -> Awaitable[set[Any]]: ...
    def srem(self, key: str, *values: str) -> Awaitable[Any]: ...
    def expire(self, key: str, seconds: int) -> Awaitable[Any]: ...


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _session_key(session_hash: str) -> str:
    return f"auth:session:{session_hash}"


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
