"""
Auth cookie, CSRF, session dependency, and /api/auth/* endpoint tests.

Runs in DEMO_MODE with an in-memory fake Redis SessionStore override.
"""

from __future__ import annotations

import asyncio
import copy
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_auth_session_store, require_student, require_teacher
from backend.auth.models import AuthPrincipal
from backend.auth.sessions import SessionStore
from frontend.backend import main

_DEMO_STUDENT_NO = "20240001"
_DEMO_STUDENT_PASSWORD = "demo123"
_DEMO_TEACHER_EMAIL = "demo@agentgrade.local"
_DEMO_TEACHER_PASSWORD = "demo123"


class FakeSessionRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.expirations: dict[str, int] = {}

    def reset(self) -> None:
        self.values.clear()
        self.sets.clear()
        self.expirations.clear()

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool | None:
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

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

    async def eval(self, script: str, numkeys: int, *keys_and_args):
        if "smembers" in script:
            lock_key = keys_and_args[0]
            index_key = keys_and_args[1]
            token = keys_and_args[2]
            session_prefix = keys_and_args[3]
            if self.values.get(lock_key) != token:
                return -1
            members = list(self.sets.get(index_key, set()))
            deleted = 0
            for member in members:
                session_key = f"{session_prefix}{member}"
                if session_key in self.values:
                    self.values.pop(session_key, None)
                    deleted += 1
            self.sets.pop(index_key, None)
            self.expirations.pop(index_key, None)
            return deleted

        if "sadd" in script and numkeys >= 3:
            lock_key = keys_and_args[0]
            session_key = keys_and_args[1]
            index_key = keys_and_args[2]
            token = keys_and_args[3]
            session_json = keys_and_args[4]
            ttl_seconds = int(keys_and_args[5])
            session_hash = keys_and_args[6]
            if self.values.get(lock_key) != token:
                return 0
            self.values[session_key] = session_json
            self.expirations[session_key] = ttl_seconds
            bucket = self.sets.setdefault(index_key, set())
            bucket.add(session_hash)
            self.expirations[index_key] = ttl_seconds
            return 1

        key = keys_and_args[0]
        token = keys_and_args[1]
        if self.values.get(key) != token:
            return 0
        if "expire" in script:
            ttl_seconds = float(keys_and_args[2])
            self.expirations[key] = ttl_seconds
            return 1
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        return 1


def _set_cookie_headers(response) -> list[str]:
    if hasattr(response.headers, "get_list"):
        return response.headers.get_list("set-cookie")
    return [value for key, value in response.headers.items() if key.lower() == "set-cookie"]


def _cookie_header_for(headers: list[str], name: str) -> str | None:
    prefix = f"{name}="
    for header in headers:
        if header.startswith(prefix):
            return header
    return None


class AuthApiTests(unittest.TestCase):
    _fake_redis: FakeSessionRedis
    _session_store: SessionStore

    @classmethod
    def setUpClass(cls):
        cls._orig_demo_mode = main._DEMO_MODE
        main._DEMO_MODE = True
        main._DEMO_STORE["teachers"][0]["password_hash"] = main._hash_password(
            _DEMO_TEACHER_PASSWORD
        )
        for student in main._DEMO_STORE["students"]:
            if student["student_no"] == _DEMO_STUDENT_NO:
                student["password_hash"] = main._hash_password(_DEMO_STUDENT_PASSWORD)

        cls._save_patcher = patch.object(main, "_save_demo_store_to_disk", lambda: None)
        cls._save_patcher.start()

        cls._fake_redis = FakeSessionRedis()
        cls._session_store = SessionStore(cls._fake_redis, ttl_seconds=28800)
        main.app.state.auth_session_store = cls._session_store

        async def _override_store():
            return cls._session_store

        main.app.dependency_overrides[get_auth_session_store] = _override_store
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.pop(get_auth_session_store, None)
        if hasattr(main.app.state, "auth_session_store"):
            delattr(main.app.state, "auth_session_store")
        cls._save_patcher.stop()
        main._DEMO_MODE = cls._orig_demo_mode

    def setUp(self):
        self._store_snapshot = copy.deepcopy(main._DEMO_STORE)
        self._fake_redis.reset()
        main.app.state.auth_session_store = type(self)._session_store

    def tearDown(self):
        main._DEMO_STORE.clear()
        main._DEMO_STORE.update(copy.deepcopy(self._store_snapshot))

    def _student_login(self):
        return self.client.post(
            "/api/student/login",
            json={"student_no": _DEMO_STUDENT_NO, "password": _DEMO_STUDENT_PASSWORD},
        )

    def _teacher_login(self):
        return self.client.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": _DEMO_TEACHER_PASSWORD},
        )

    def test_student_login_sets_secure_contract_cookies(self):
        resp = self._student_login()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["student_no"], _DEMO_STUDENT_NO)

        headers = _set_cookie_headers(resp)
        session_cookie = _cookie_header_for(headers, "agentgrade_session")
        csrf_cookie = _cookie_header_for(headers, "agentgrade_csrf")
        self.assertIsNotNone(session_cookie)
        self.assertIsNotNone(csrf_cookie)

        session_lower = session_cookie.lower()
        self.assertIn("httponly", session_lower)
        self.assertIn("samesite=lax", session_lower)
        self.assertIn("max-age=28800", session_lower)

        csrf_lower = csrf_cookie.lower()
        self.assertNotIn("httponly", csrf_lower)

    def test_teacher_login_sets_secure_contract_cookies(self):
        resp = self._teacher_login()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], _DEMO_TEACHER_EMAIL)

        headers = _set_cookie_headers(resp)
        session_cookie = _cookie_header_for(headers, "agentgrade_session")
        csrf_cookie = _cookie_header_for(headers, "agentgrade_csrf")
        self.assertIsNotNone(session_cookie)
        self.assertIsNotNone(csrf_cookie)

        session_lower = session_cookie.lower()
        self.assertIn("httponly", session_lower)
        self.assertIn("samesite=lax", session_lower)
        self.assertIn("max-age=28800", session_lower)

        csrf_lower = csrf_cookie.lower()
        self.assertNotIn("httponly", csrf_lower)

    def test_teacher_register_does_not_set_auth_cookies(self):
        resp = self.client.post(
            "/api/teacher/register",
            json={
                "first_name": "Yeni",
                "last_name": "Ogretmen",
                "email": "auth-test@ogretmen.local",
                "password": "parola123",
            },
        )
        self.assertIn(resp.status_code, {200, 201})
        headers = _set_cookie_headers(resp)
        self.assertIsNone(_cookie_header_for(headers, "agentgrade_session"))
        self.assertIsNone(_cookie_header_for(headers, "agentgrade_csrf"))

    def test_me_requires_session_and_returns_role_profile(self):
        resp = self.client.get("/api/auth/me")
        self.assertEqual(resp.status_code, 401)

        login_resp = self._student_login()
        self.assertEqual(login_resp.status_code, 200)

        me_resp = self.client.get("/api/auth/me")
        self.assertEqual(me_resp.status_code, 200)
        body = me_resp.json()
        self.assertEqual(body["role"], "student")
        self.assertEqual(body["user"]["student_no"], _DEMO_STUDENT_NO)
        # Safe GET does not require CSRF header (explicit assertion for spec).

    def test_me_returns_teacher_profile_after_teacher_login(self):
        login_resp = self._teacher_login()
        self.assertEqual(login_resp.status_code, 200)

        me_resp = self.client.get("/api/auth/me")
        self.assertEqual(me_resp.status_code, 200)
        body = me_resp.json()
        self.assertEqual(body["role"], "teacher")
        self.assertEqual(body["user"]["email"], _DEMO_TEACHER_EMAIL)

    def test_logout_is_idempotent_and_clears_cookies(self):
        login_resp = self._student_login()
        self.assertEqual(login_resp.status_code, 200)
        csrf_value = self.client.cookies.get("agentgrade_csrf")
        self.assertIsNotNone(csrf_value)

        logout_resp = self.client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": csrf_value},
        )
        self.assertEqual(logout_resp.status_code, 204)

        me_resp = self.client.get("/api/auth/me")
        self.assertEqual(me_resp.status_code, 401)

        second_logout = self.client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": csrf_value},
        )
        self.assertEqual(second_logout.status_code, 204)

    def test_logout_without_csrf_on_valid_session_is_forbidden(self):
        login_resp = self._student_login()
        self.assertEqual(login_resp.status_code, 200)

        logout_resp = self.client.post("/api/auth/logout")
        self.assertEqual(logout_resp.status_code, 403)

        me_resp = self.client.get("/api/auth/me")
        self.assertEqual(me_resp.status_code, 200)

    def test_auth_cookie_secure_setting_adds_secure_flag(self):
        original = main.settings.auth_cookie_secure
        try:
            main.settings.auth_cookie_secure = True
            resp = self._student_login()
            self.assertEqual(resp.status_code, 200)
            headers = _set_cookie_headers(resp)
            session_cookie = _cookie_header_for(headers, "agentgrade_session")
            self.assertIsNotNone(session_cookie)
            self.assertIn("secure", session_cookie.lower())
        finally:
            main.settings.auth_cookie_secure = original

    def test_redis_failure_on_login_returns_503_without_cookies(self):
        async def _boom(*_args, **_kwargs):
            raise RuntimeError("redis down")

        with patch.object(self._session_store, "create_session_if_lock_held", side_effect=_boom):
            resp = self.client.post(
                "/api/student/login",
                json={"student_no": _DEMO_STUDENT_NO, "password": _DEMO_STUDENT_PASSWORD},
            )
        self.assertEqual(resp.status_code, 503)
        headers = _set_cookie_headers(resp)
        self.assertIsNone(_cookie_header_for(headers, "agentgrade_session"))
        self.assertIsNone(_cookie_header_for(headers, "agentgrade_csrf"))

    def test_require_student_and_require_teacher_reject_wrong_role_directly(self):
        teacher_principal = AuthPrincipal(
            user_id="t-1",
            role="teacher",
            session_hash="sh",
            csrf_hash="ch",
        )
        student_principal = AuthPrincipal(
            user_id="s-1",
            role="student",
            session_hash="sh",
            csrf_hash="ch",
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(require_student(principal=teacher_principal))
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(require_teacher(principal=student_principal))
        self.assertEqual(ctx.exception.status_code, 403)

        self.assertIs(
            asyncio.run(require_student(principal=student_principal)),
            student_principal,
        )
        self.assertIs(
            asyncio.run(require_teacher(principal=teacher_principal)),
            teacher_principal,
        )

    def test_safe_get_method_does_not_require_csrf(self):
        login_resp = self._student_login()
        self.assertEqual(login_resp.status_code, 200)

        me_resp = self.client.get("/api/auth/me")
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()["role"], "student")

    def test_logout_returns_503_when_redis_raises_during_session_read(self):
        login_resp = self._student_login()
        self.assertEqual(login_resp.status_code, 200)
        csrf_value = self.client.cookies.get("agentgrade_csrf")
        self.assertIsNotNone(csrf_value)

        with patch.object(
            self._session_store,
            "read_session",
            new_callable=AsyncMock,
            side_effect=ConnectionError("redis down"),
        ):
            logout_resp = self.client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": csrf_value},
            )
        self.assertEqual(logout_resp.status_code, 503)
        self.assertEqual(logout_resp.json()["detail"], "Oturum servisine ulaşılamıyor")

    def test_logout_returns_503_when_redis_raises_during_session_revoke(self):
        login_resp = self._student_login()
        self.assertEqual(login_resp.status_code, 200)
        csrf_value = self.client.cookies.get("agentgrade_csrf")
        self.assertIsNotNone(csrf_value)

        with patch.object(
            self._session_store,
            "revoke_session",
            new_callable=AsyncMock,
            side_effect=ConnectionError("redis down"),
        ):
            logout_resp = self.client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": csrf_value},
            )
        self.assertEqual(logout_resp.status_code, 503)
        self.assertEqual(logout_resp.json()["detail"], "Oturum servisine ulaşılamıyor")

        me_resp = self.client.get("/api/auth/me")
        self.assertEqual(me_resp.status_code, 200)

    def test_logout_does_not_clear_cookies_on_503(self):
        login_resp = self._student_login()
        self.assertEqual(login_resp.status_code, 200)
        csrf_value = self.client.cookies.get("agentgrade_csrf")
        self.assertIsNotNone(csrf_value)

        with patch.object(
            self._session_store,
            "read_session",
            new_callable=AsyncMock,
            side_effect=ConnectionError("redis down"),
        ):
            logout_resp = self.client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": csrf_value},
            )
        self.assertEqual(logout_resp.status_code, 503)
        headers = _set_cookie_headers(logout_resp)
        self.assertIsNone(_cookie_header_for(headers, "agentgrade_session"))
        self.assertIsNone(_cookie_header_for(headers, "agentgrade_csrf"))

        me_resp = self.client.get("/api/auth/me")
        self.assertEqual(me_resp.status_code, 200)
