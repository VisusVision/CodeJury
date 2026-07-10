from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.auth.dependencies import get_auth_session_store
from backend.auth.models import AuthPrincipal
from backend.auth.sessions import SessionStore, hash_token
from frontend.backend import main

SESSION_TTL = 28800


class FakeSessionRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.expirations: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.sets.pop(key, None)
        self.expirations.pop(key, None)

    async def sadd(self, key: str, *values: str) -> None:
        bucket = self.sets.setdefault(key, set())
        bucket.update(values)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    async def srem(self, key: str, *values: str) -> None:
        bucket = self.sets.get(key)
        if bucket is None:
            return
        for value in values:
            bucket.discard(value)

    async def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds


def _session_key(session_hash: str) -> str:
    return f"auth:session:{session_hash}"


def _user_index_key(user_id: str, role: str) -> str:
    return f"auth:user_sessions:{role}:{user_id}"


@pytest.fixture
def redis() -> FakeSessionRedis:
    return FakeSessionRedis()


@pytest.fixture
def store(redis: FakeSessionRedis) -> SessionStore:
    return SessionStore(redis, ttl_seconds=SESSION_TTL)


@pytest.mark.asyncio
async def test_create_session_stores_only_hashes_with_eight_hour_ttl(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    issued = await store.create_session("user-1", "student")

    session_hash = hash_token(issued.session_token)
    session_key = _session_key(session_hash)
    stored_raw = redis.values[session_key]

    assert issued.session_token not in stored_raw
    assert issued.csrf_token not in stored_raw
    assert hash_token(issued.csrf_token) in stored_raw
    assert redis.expirations[session_key] == SESSION_TTL


@pytest.mark.asyncio
async def test_read_session_returns_principal_and_missing_returns_none(
    store: SessionStore,
) -> None:
    issued = await store.create_session("user-42", "teacher")

    principal = await store.read_session(issued.session_token)
    assert principal == AuthPrincipal(
        user_id="user-42",
        role="teacher",
        session_hash=hash_token(issued.session_token),
        csrf_hash=hash_token(issued.csrf_token),
    )

    assert await store.read_session("nonexistent-token") is None


@pytest.mark.asyncio
async def test_revoke_current_and_revoke_all_user_sessions(
    store: SessionStore,
) -> None:
    first = await store.create_session("user-9", "student")
    second = await store.create_session("user-9", "student")

    await store.revoke_session(first.session_token)
    assert await store.read_session(first.session_token) is None
    assert await store.read_session(second.session_token) is not None

    revoked_count = await store.revoke_user_sessions("user-9", "student")
    assert revoked_count == 1
    assert await store.read_session(second.session_token) is None


@pytest.mark.asyncio
async def test_read_session_returns_none_for_malformed_json(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    raw_token = "known-raw-session-token"
    session_hash = hash_token(raw_token)
    session_key = _session_key(session_hash)
    redis.values[session_key] = "{not-valid-json"

    assert await store.read_session(raw_token) is None


@pytest.mark.asyncio
async def test_read_session_returns_none_for_unknown_role(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    raw_token = "another-raw-session-token"
    session_hash = hash_token(raw_token)
    session_key = _session_key(session_hash)
    redis.values[session_key] = json.dumps(
        {
            "user_id": "user-x",
            "role": "admin",
            "csrf_hash": "abc123",
            "created_at": "2026-07-10T12:00:00Z",
        }
    )

    assert await store.read_session(raw_token) is None


@pytest.mark.asyncio
async def test_revoke_session_removes_hash_from_user_index(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    issued = await store.create_session("user-index", "student")
    session_hash = hash_token(issued.session_token)
    index_key = _user_index_key("user-index", "student")

    assert session_hash in await redis.smembers(index_key)

    await store.revoke_session(issued.session_token)

    assert session_hash not in await redis.smembers(index_key)


@pytest.mark.asyncio
async def test_create_session_refreshes_user_index_ttl(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    await store.create_session("user-ttl", "teacher")
    index_key = _user_index_key("user-ttl", "teacher")

    assert index_key in redis.expirations
    assert redis.expirations[index_key] == SESSION_TTL


@pytest.mark.asyncio
async def test_get_auth_session_store_creates_only_one_client_under_concurrent_calls() -> None:
    fake_app = SimpleNamespace(state=SimpleNamespace())
    fake_request = SimpleNamespace(app=fake_app)
    sentinel_redis = object()

    with patch(
        "backend.auth.dependencies.create_redis_client",
        return_value=sentinel_redis,
    ) as mock_create:
        stores = await asyncio.gather(
            get_auth_session_store(fake_request),
            get_auth_session_store(fake_request),
            get_auth_session_store(fake_request),
        )

    assert mock_create.call_count == 1
    assert stores[0] is stores[1] is stores[2]
    assert stores[0].redis is sentinel_redis


@pytest.mark.asyncio
async def test_shutdown_auth_session_store_closes_redis_client() -> None:
    mock_redis = MagicMock()
    mock_redis.aclose = AsyncMock()
    store = SessionStore(mock_redis, ttl_seconds=SESSION_TTL)
    main.app.state.auth_session_store = store

    try:
        await main._shutdown_auth_session_store()
        mock_redis.aclose.assert_awaited_once()
        assert getattr(main.app.state, "auth_session_store", "missing") is None
    finally:
        if hasattr(main.app.state, "auth_session_store"):
            delattr(main.app.state, "auth_session_store")
