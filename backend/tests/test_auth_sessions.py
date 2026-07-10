from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.auth.dependencies import get_auth_session_store
from backend.auth.models import AuthPrincipal
from backend.auth.sessions import (
    LockLost,
    SessionStore,
    UserLockUnavailable,
    acquire_user_lock,
    hash_token,
    release_user_lock,
    user_lock,
)
from frontend.backend import main

SESSION_TTL = 28800


class FakeSessionRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.expirations: dict[str, int] = {}
        self._expires_at: dict[str, float] = {}

    def _purge_expired(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is not None and time.monotonic() >= expires_at:
            self.values.pop(key, None)
            self.sets.pop(key, None)
            self.expirations.pop(key, None)
            self._expires_at.pop(key, None)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool | None:
        self._purge_expired(key)
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
            self._expires_at[key] = time.monotonic() + ex
        return True

    async def get(self, key: str) -> str | None:
        self._purge_expired(key)
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

    async def eval(self, script: str, numkeys: int, *keys_and_args):
        if "smembers" in script:
            lock_key = keys_and_args[0]
            index_key = keys_and_args[1]
            token = keys_and_args[2]
            session_prefix = keys_and_args[3]
            self._purge_expired(lock_key)
            if self.values.get(lock_key) != token:
                return -1
            members = list(self.sets.get(index_key, set()))
            deleted = 0
            for member in members:
                session_key = f"{session_prefix}{member}"
                if session_key in self.values:
                    self.values.pop(session_key, None)
                    self.expirations.pop(session_key, None)
                    self._expires_at.pop(session_key, None)
                    deleted += 1
            self.sets.pop(index_key, None)
            self.expirations.pop(index_key, None)
            self._expires_at.pop(index_key, None)
            return deleted

        if "sadd" in script and numkeys >= 3:
            lock_key = keys_and_args[0]
            session_key = keys_and_args[1]
            index_key = keys_and_args[2]
            token = keys_and_args[3]
            session_json = keys_and_args[4]
            ttl_seconds = int(keys_and_args[5])
            session_hash = keys_and_args[6]
            self._purge_expired(lock_key)
            if self.values.get(lock_key) != token:
                return 0
            self.values[session_key] = session_json
            self.expirations[session_key] = ttl_seconds
            self._expires_at[session_key] = time.monotonic() + ttl_seconds
            bucket = self.sets.setdefault(index_key, set())
            bucket.add(session_hash)
            self.expirations[index_key] = ttl_seconds
            self._expires_at[index_key] = time.monotonic() + ttl_seconds
            return 1

        key = keys_and_args[0]
        self._purge_expired(key)
        token = keys_and_args[1]
        if self.values.get(key) != token:
            return 0
        if "expire" in script:
            ttl_seconds = float(keys_and_args[2])
            self.expirations[key] = ttl_seconds
            self._expires_at[key] = time.monotonic() + ttl_seconds
            return 1
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        self._expires_at.pop(key, None)
        return 1


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
async def test_acquire_and_release_user_lock_round_trip(redis: FakeSessionRedis) -> None:
    token = await acquire_user_lock(redis, "teacher", "user-1")
    assert token
    assert redis.values["auth:userlock:teacher:user-1"] == token
    await release_user_lock(redis, "teacher", "user-1", token)
    assert "auth:userlock:teacher:user-1" not in redis.values


@pytest.mark.asyncio
async def test_second_acquire_fails_while_lock_is_held(redis: FakeSessionRedis) -> None:
    token = await acquire_user_lock(redis, "student", "user-2", max_attempts=1)
    with pytest.raises(UserLockUnavailable):
        await acquire_user_lock(redis, "student", "user-2", max_attempts=1)
    await release_user_lock(redis, "student", "user-2", token)


@pytest.mark.asyncio
async def test_release_only_succeeds_for_the_owning_token(redis: FakeSessionRedis) -> None:
    token = await acquire_user_lock(redis, "teacher", "user-3")
    await release_user_lock(redis, "teacher", "user-3", "wrong-token")
    assert "auth:userlock:teacher:user-3" in redis.values
    with pytest.raises(UserLockUnavailable):
        await acquire_user_lock(redis, "teacher", "user-3", max_attempts=1)
    await release_user_lock(redis, "teacher", "user-3", token)
    new_token = await acquire_user_lock(redis, "teacher", "user-3", max_attempts=1)
    await release_user_lock(redis, "teacher", "user-3", new_token)


@pytest.mark.asyncio
async def test_acquire_raises_user_lock_unavailable_when_redis_raises(
    redis: FakeSessionRedis,
) -> None:
    async def failing_set(*_args, **_kwargs):
        raise ConnectionError("redis down")

    with patch.object(redis, "set", side_effect=failing_set):
        with pytest.raises(UserLockUnavailable, match="redis error"):
            await acquire_user_lock(redis, "teacher", "user-4", max_attempts=1)


@pytest.mark.asyncio
async def test_acquire_retries_and_eventually_raises_when_contention_never_clears(
    redis: FakeSessionRedis,
) -> None:
    holder_token = await acquire_user_lock(redis, "teacher", "user-5")
    with pytest.raises(UserLockUnavailable, match="contention exhausted"):
        await acquire_user_lock(
            redis,
            "teacher",
            "user-5",
            max_attempts=3,
            retry_delay_seconds=0.01,
        )
    await release_user_lock(redis, "teacher", "user-5", holder_token)


@pytest.mark.asyncio
async def test_release_is_atomic_against_a_new_owner_after_expiry_and_reacquire(
    redis: FakeSessionRedis,
) -> None:
    old_token = await acquire_user_lock(redis, "teacher", "user-race", ttl_seconds=10)
    key = "auth:userlock:teacher:user-race"
    redis.values.pop(key, None)
    redis.expirations.pop(key, None)
    redis._expires_at.pop(key, None)
    new_token = await acquire_user_lock(redis, "teacher", "user-race", ttl_seconds=10)

    await release_user_lock(redis, "teacher", "user-race", old_token)

    assert key in redis.values
    assert redis.values[key] == new_token


class _RenewalFailRedis(FakeSessionRedis):
    """Fake Redis that fails lock renewal EVAL calls deterministically."""

    def __init__(self, *, renewal_result: int | None = None, renewal_error: Exception | None = None) -> None:
        super().__init__()
        self._renewal_result = renewal_result
        self._renewal_error = renewal_error
        self.renewal_eval_calls = 0

    async def eval(self, script: str, numkeys: int, *keys_and_args):
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


@pytest.mark.asyncio
async def test_user_lock_check_raises_lock_lost_when_renewal_eval_returns_zero() -> None:
    redis = _RenewalFailRedis(renewal_result=0)
    async with user_lock(redis, "teacher", "user-lost-zero", ttl_seconds=0.2) as lock:
        await _wait_until(lambda: redis.renewal_eval_calls >= 1)
        with pytest.raises(LockLost, match="lease was lost"):
            lock.check()


@pytest.mark.asyncio
async def test_user_lock_check_raises_lock_lost_when_renewal_eval_raises() -> None:
    redis = _RenewalFailRedis(renewal_error=ConnectionError("redis down"))
    async with user_lock(redis, "teacher", "user-lost-error", ttl_seconds=0.2) as lock:
        await _wait_until(lambda: redis.renewal_eval_calls >= 1)
        with pytest.raises(LockLost, match="lease was lost"):
            lock.check()


@pytest.mark.asyncio
async def test_lock_lease_is_renewed_and_survives_past_the_original_ttl(
    redis: FakeSessionRedis,
) -> None:
    async with user_lock(redis, "teacher", "user-renew", ttl_seconds=0.2) as lock:
        await asyncio.sleep(0.1)
        lock.check()
        with pytest.raises(UserLockUnavailable):
            await acquire_user_lock(redis, "teacher", "user-renew", max_attempts=1)
        await asyncio.sleep(0.25)
        lock.check()
        with pytest.raises(UserLockUnavailable):
            await acquire_user_lock(redis, "teacher", "user-renew", max_attempts=1)


@pytest.mark.asyncio
async def test_renewal_stops_and_lock_releases_when_context_manager_exits(
    redis: FakeSessionRedis,
) -> None:
    key = "auth:userlock:teacher:user-release"
    async with user_lock(redis, "teacher", "user-release", ttl_seconds=0.2):
        assert key in redis.values
    assert key not in redis.values
    token = await acquire_user_lock(redis, "teacher", "user-release", max_attempts=1)
    await release_user_lock(redis, "teacher", "user-release", token)


@pytest.mark.asyncio
async def test_create_session_if_lock_held_fails_closed_when_token_mismatched(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    user_id = "user-lock-mismatch"
    role = "teacher"
    lock_key = f"auth:userlock:{role}:{user_id}"
    redis.values[lock_key] = "actual-owner-token"

    with pytest.raises(LockLost):
        await store.create_session_if_lock_held(user_id, role, "wrong-token")

    session_keys = [key for key in redis.values if key.startswith("auth:session:")]
    index_keys = [key for key in redis.sets if key.startswith("auth:user_sessions:")]
    assert session_keys == []
    assert index_keys == []


@pytest.mark.asyncio
async def test_revoke_user_sessions_if_lock_held_fails_closed_when_token_mismatched(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    user_id = "user-revoke-mismatch"
    role = "teacher"
    await store.create_session(user_id, role)
    await store.create_session(user_id, role)
    index_key = _user_index_key(user_id, role)
    session_hashes_before = await redis.smembers(index_key)
    assert len(session_hashes_before) == 2

    lock_key = f"auth:userlock:{role}:{user_id}"
    redis.values[lock_key] = "actual-owner-token"

    with pytest.raises(LockLost):
        await store.revoke_user_sessions_if_lock_held(user_id, role, "wrong-token")

    assert await redis.smembers(index_key) == session_hashes_before
    for session_hash in session_hashes_before:
        assert await redis.get(_session_key(session_hash)) is not None


@pytest.mark.asyncio
async def test_create_session_if_lock_held_succeeds_when_token_matches(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    user_id = "user-lock-match"
    role = "student"
    lock_key = f"auth:userlock:{role}:{user_id}"
    token = "matching-lock-token"
    redis.values[lock_key] = token

    issued = await store.create_session_if_lock_held(user_id, role, token)

    session_hash = hash_token(issued.session_token)
    session_key = _session_key(session_hash)
    index_key = _user_index_key(user_id, role)
    assert session_hash in await redis.smembers(index_key)
    assert await redis.get(session_key) is not None
    assert await store.read_session(issued.session_token) is not None


@pytest.mark.asyncio
async def test_revoke_user_sessions_if_lock_held_succeeds_when_token_matches(
    store: SessionStore,
    redis: FakeSessionRedis,
) -> None:
    user_id = "user-revoke-match"
    role = "teacher"
    first = await store.create_session(user_id, role)
    second = await store.create_session(user_id, role)

    lock_key = f"auth:userlock:{role}:{user_id}"
    token = "matching-revoke-token"
    redis.values[lock_key] = token

    deleted = await store.revoke_user_sessions_if_lock_held(user_id, role, token)

    assert deleted == 2
    assert await store.read_session(first.session_token) is None
    assert await store.read_session(second.session_token) is None
    assert await redis.smembers(_user_index_key(user_id, role)) == set()


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
