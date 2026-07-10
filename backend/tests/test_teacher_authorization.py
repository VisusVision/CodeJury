"""
Teacher-only route authorization and ownership policy tests (Phase 2A Task 4).

Runs in DEMO_MODE with in-memory SessionStore override.
"""

from __future__ import annotations

import copy
import unittest
from functools import partial
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.auth.dependencies import CSRF_HEADER, get_auth_session_store
from contextlib import asynccontextmanager

from backend.auth.sessions import SessionStore, acquire_user_lock, release_user_lock, user_lock
from frontend.backend import main

_DEMO_TEACHER_ID = "11111111-1111-4111-8111-111111111111"
_DEMO_TEACHER_EMAIL = "demo@agentgrade.local"
_DEMO_TEACHER_PASSWORD = "demo123"
_DEMO_STUDENT_NO = "20240001"
_DEMO_STUDENT_PASSWORD = "demo123"
_DEMO_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
_DEMO_DEPARTMENT_ID = "33333333-3333-4333-8333-333333333333"
_DEMO_COURSE_ID = "44444444-4444-4444-8444-444444444444"

TEACHER_ONLY_ROUTES = {
    ("GET", "/api/departments"),
    ("POST", "/api/departments"),
    ("DELETE", "/api/departments/{department_id}"),
    ("GET", "/api/courses"),
    ("POST", "/api/courses"),
    ("DELETE", "/api/courses/{course_id}"),
    ("GET", "/api/assignments"),
    ("POST", "/api/assignments"),
    ("DELETE", "/api/assignments/{assignment_id}"),
    ("GET", "/api/assignments/{assignment_id}/test-cases"),
    ("POST", "/api/assignments/{assignment_id}/test-cases/suggest"),
    ("PUT", "/api/assignments/{assignment_id}/test-cases"),
    ("GET", "/api/rubrics"),
    ("POST", "/api/rubrics/upsert"),
    ("PATCH", "/api/rubrics/by-assignment/{assignment_id}"),
    ("POST", "/api/rubric/suggest"),
    ("POST", "/api/faculty/assignment-assistant/example"),
    ("POST", "/api/faculty/assignment-assistant/suggestions"),
    ("GET", "/api/questions"),
    ("POST", "/api/questions"),
    ("DELETE", "/api/questions/{question_id}"),
    ("POST", "/api/assignment-questions/update"),
}


class _FakeSessionRedis:
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


class TeacherAuthorizationTests(unittest.TestCase):
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

        cls._fake_redis = _FakeSessionRedis()
        cls._session_store = SessionStore(cls._fake_redis, ttl_seconds=28800)

        async def _override_store():
            return cls._session_store

        main.app.dependency_overrides[get_auth_session_store] = _override_store

        cls.client_a = TestClient(main.app)
        cls.client_b = TestClient(main.app)

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
        self.client_a.cookies.clear()
        self.client_b.cookies.clear()

    def tearDown(self):
        main._DEMO_STORE.clear()
        main._DEMO_STORE.update(copy.deepcopy(self._store_snapshot))

    def _login_teacher(
        self,
        client: TestClient | None = None,
        *,
        email: str = _DEMO_TEACHER_EMAIL,
        password: str = _DEMO_TEACHER_PASSWORD,
    ) -> str:
        c = client or self.client_a
        resp = c.post("/api/teacher/login", json={"email": email, "password": password})
        self.assertEqual(resp.status_code, 200)
        return c.cookies.get("agentgrade_csrf")

    def _csrf_headers(self, csrf: str) -> dict[str, str]:
        return {CSRF_HEADER: csrf}

    def _register_teacher_b(self) -> tuple[str, str]:
        resp = self.client_b.post(
            "/api/teacher/register",
            json={
                "first_name": "Other",
                "last_name": "Teacher",
                "email": "teacherb@test.local",
                "password": "parola123",
            },
        )
        self.assertEqual(resp.status_code, 200)
        teacher_id = resp.json()["id"]
        csrf = self._login_teacher(self.client_b, email="teacherb@test.local", password="parola123")
        return teacher_id, csrf

    def _call_route_anonymous(self, method: str, path: str):
        client = TestClient(main.app)
        if method == "GET":
            return client.get(path)
        if method == "POST":
            if path == "/api/departments":
                return client.post(path, json={"name": "Anon Dept"})
            if path == "/api/courses":
                return client.post(
                    path,
                    json={"name": "Anon", "code": "AN101", "class_year": 1},
                )
            if path == "/api/assignments":
                return client.post(
                    path,
                    json={"course_id": _DEMO_COURSE_ID, "name": "Anon Assignment"},
                )
            if path.endswith("/test-cases/suggest"):
                return client.post(path)
            if path.endswith("/test-cases"):
                return client.put(path, json={"test_cases": []})
            if path == "/api/rubrics/upsert":
                return client.post(
                    path,
                    json={
                        "assignment_id": _DEMO_ASSIGNMENT_ID,
                        "criteria": [
                            {"name": f"K{i}", "description": "D", "max_score": 10}
                            for i in range(10)
                        ],
                        "status": "draft",
                    },
                )
            if path == "/api/rubric/suggest":
                return client.post(
                    path,
                    json={"assignment_title": "T", "assignment_description": "D"},
                )
            if path == "/api/faculty/assignment-assistant/example":
                return client.post(
                    path,
                    json={"assignment_title": "T", "assignment_description": "D"},
                )
            if path == "/api/faculty/assignment-assistant/suggestions":
                return client.post(path, json={"course_hint": "Python odevi"})
            if path == "/api/questions":
                return client.post(path, json={"content": "Anon question?"})
            if path == "/api/assignment-questions/update":
                return client.post(
                    path,
                    json={"assignment_id": _DEMO_ASSIGNMENT_ID, "question_ids": []},
                )
            return client.post(path, json={})
        if method == "PUT":
            return client.put(path, json={"test_cases": []})
        if method == "PATCH":
            return client.patch(path, json={"status": "draft"})
        if method == "DELETE":
            return client.delete(path)
        raise AssertionError(f"Unsupported method: {method}")

    def test_teacher_only_routes_reject_anonymous_access(self):
        path_params = {
            "department_id": _DEMO_DEPARTMENT_ID,
            "course_id": _DEMO_COURSE_ID,
            "assignment_id": _DEMO_ASSIGNMENT_ID,
            "question_id": "77777777-7777-4777-8777-777777777777",
        }
        for method, route_template in sorted(TEACHER_ONLY_ROUTES):
            path = route_template.format(**path_params)
            with self.subTest(method=method, path=path):
                resp = self._call_route_anonymous(method, path)
                self.assertEqual(resp.status_code, 401, resp.text)

    def test_department_ownership_list_and_delete(self):
        csrf_a = self._login_teacher(self.client_a)
        teacher_b_id, csrf_b = self._register_teacher_b()

        create_resp = self.client_a.post(
            "/api/departments",
            json={"name": "Teacher A Dept"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(create_resp.status_code, 200)
        dept_id = create_resp.json()["id"]

        list_a = self.client_a.get("/api/departments")
        list_b = self.client_b.get("/api/departments")
        self.assertIn(dept_id, [d["id"] for d in list_a.json()])
        self.assertNotIn(dept_id, [d["id"] for d in list_b.json()])

        del_b = self.client_b.delete(
            f"/api/departments/{dept_id}",
            headers=self._csrf_headers(csrf_b),
        )
        self.assertEqual(del_b.status_code, 404)

        del_a = self.client_a.delete(
            f"/api/departments/{dept_id}",
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(del_a.status_code, 200)

    def test_legacy_department_visible_but_not_mutable(self):
        csrf_a = self._login_teacher(self.client_a)
        _, csrf_b = self._register_teacher_b()

        legacy_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        main._DEMO_STORE["departments"].append(
            {
                "id": legacy_id,
                "name": "Legacy Dept",
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )

        list_a = self.client_a.get("/api/departments")
        list_b = self.client_b.get("/api/departments")
        self.assertIn(legacy_id, [d["id"] for d in list_a.json()])
        self.assertIn(legacy_id, [d["id"] for d in list_b.json()])

        del_a = self.client_a.delete(
            f"/api/departments/{legacy_id}",
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(del_a.status_code, 403)

        del_b = self.client_b.delete(
            f"/api/departments/{legacy_id}",
            headers=self._csrf_headers(csrf_b),
        )
        self.assertEqual(del_b.status_code, 403)

    def test_course_creation_respects_department_ownership(self):
        csrf_a = self._login_teacher(self.client_a)
        teacher_b_id, csrf_b = self._register_teacher_b()

        dept_b = self.client_b.post(
            "/api/departments",
            json={"name": "Dept B Only"},
            headers=self._csrf_headers(csrf_b),
        )
        self.assertEqual(dept_b.status_code, 200)
        dept_b_id = dept_b.json()["id"]

        legacy_dept_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        main._DEMO_STORE["departments"].append(
            {
                "id": legacy_dept_id,
                "name": "Legacy Dept For Course",
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )

        cross = self.client_a.post(
            "/api/courses",
            json={
                "name": "Cross Dept Course",
                "code": "CD101",
                "class_year": 1,
                "department_id": dept_b_id,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(cross.status_code, 404)

        legacy_course = self.client_a.post(
            "/api/courses",
            json={
                "name": "Legacy Dept Course",
                "code": "LD101",
                "class_year": 1,
                "department_id": legacy_dept_id,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(legacy_course.status_code, 403)

        own_dept = self.client_a.post(
            "/api/departments",
            json={"name": "Dept A Own"},
            headers=self._csrf_headers(csrf_a),
        )
        own_course = self.client_a.post(
            "/api/courses",
            json={
                "name": "Own Course",
                "code": "OC101",
                "class_year": 2,
                "department_id": own_dept.json()["id"],
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(own_course.status_code, 200)
        self.assertEqual(own_course.json()["created_by"], _DEMO_TEACHER_ID)

    def test_assignment_creation_respects_course_ownership(self):
        csrf_a = self._login_teacher(self.client_a)
        _, csrf_b = self._register_teacher_b()

        dept_b = self.client_b.post(
            "/api/departments",
            json={"name": "Dept For Course B"},
            headers=self._csrf_headers(csrf_b),
        )
        course_b = self.client_b.post(
            "/api/courses",
            json={
                "name": "Course B",
                "code": "CB101",
                "class_year": 1,
                "department_id": dept_b.json()["id"],
            },
            headers=self._csrf_headers(csrf_b),
        )
        course_b_id = course_b.json()["id"]

        legacy_course_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        main._DEMO_STORE["courses"].append(
            {
                "id": legacy_course_id,
                "name": "Legacy Course",
                "code": "LC101",
                "class_year": 1,
                "department_id": None,
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )

        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            cross = self.client_a.post(
                "/api/assignments",
                json={"course_id": course_b_id, "name": "Cross Assignment"},
                headers=self._csrf_headers(csrf_a),
            )
            self.assertEqual(cross.status_code, 404)

            legacy = self.client_a.post(
                "/api/assignments",
                json={"course_id": legacy_course_id, "name": "Legacy Course Assignment"},
                headers=self._csrf_headers(csrf_a),
            )
            self.assertEqual(legacy.status_code, 403)

            own = self.client_a.post(
                "/api/assignments",
                json={"course_id": _DEMO_COURSE_ID, "name": "Own Assignment"},
                headers=self._csrf_headers(csrf_a),
            )
            self.assertEqual(own.status_code, 200)
            self.assertEqual(own.json()["created_by"], _DEMO_TEACHER_ID)

    def test_assignment_test_cases_cross_owner_and_legacy(self):
        csrf_a = self._login_teacher(self.client_a)
        _, csrf_b = self._register_teacher_b()

        dept_b = self.client_b.post(
            "/api/departments",
            json={"name": "Dept TC"},
            headers=self._csrf_headers(csrf_b),
        )
        course_b = self.client_b.post(
            "/api/courses",
            json={
                "name": "Course TC",
                "code": "CTC101",
                "class_year": 1,
                "department_id": dept_b.json()["id"],
            },
            headers=self._csrf_headers(csrf_b),
        )
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            assignment_b = self.client_b.post(
                "/api/assignments",
                json={"course_id": course_b.json()["id"], "name": "Assignment TC"},
                headers=self._csrf_headers(csrf_b),
            )
        assignment_b_id = assignment_b.json()["id"]

        get_cross = self.client_a.get(f"/api/assignments/{assignment_b_id}/test-cases")
        self.assertEqual(get_cross.status_code, 404)

        put_cross = self.client_a.put(
            f"/api/assignments/{assignment_b_id}/test-cases",
            json={"test_cases": []},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(put_cross.status_code, 404)

        legacy_assignment_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        main._DEMO_STORE["assignments"].append(
            {
                "id": legacy_assignment_id,
                "course_id": _DEMO_COURSE_ID,
                "name": "Legacy Assignment",
                "description": None,
                "due_date": None,
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )

        get_legacy = self.client_a.get(f"/api/assignments/{legacy_assignment_id}/test-cases")
        self.assertEqual(get_legacy.status_code, 200)

        put_legacy = self.client_a.put(
            f"/api/assignments/{legacy_assignment_id}/test-cases",
            json={"test_cases": []},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(put_legacy.status_code, 403)

    def test_rubric_upsert_and_patch_cross_owner_and_legacy(self):
        csrf_a = self._login_teacher(self.client_a)
        _, csrf_b = self._register_teacher_b()

        dept_b = self.client_b.post(
            "/api/departments",
            json={"name": "Dept Rubric"},
            headers=self._csrf_headers(csrf_b),
        )
        course_b = self.client_b.post(
            "/api/courses",
            json={
                "name": "Course Rubric",
                "code": "CR101",
                "class_year": 1,
                "department_id": dept_b.json()["id"],
            },
            headers=self._csrf_headers(csrf_b),
        )
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            assignment_b = self.client_b.post(
                "/api/assignments",
                json={"course_id": course_b.json()["id"], "name": "Assignment Rubric"},
                headers=self._csrf_headers(csrf_b),
            )
        assignment_b_id = assignment_b.json()["id"]

        criteria = [
            {"name": f"Kriter {i}", "description": f"D{i}", "max_score": 10}
            for i in range(10)
        ]

        upsert_cross = self.client_a.post(
            "/api/rubrics/upsert",
            json={"assignment_id": assignment_b_id, "criteria": criteria, "status": "draft"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(upsert_cross.status_code, 404)

        patch_cross = self.client_a.patch(
            f"/api/rubrics/by-assignment/{assignment_b_id}",
            json={"status": "approved"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(patch_cross.status_code, 404)

        legacy_assignment_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        main._DEMO_STORE["assignments"].append(
            {
                "id": legacy_assignment_id,
                "course_id": _DEMO_COURSE_ID,
                "name": "Legacy Rubric Assignment",
                "description": None,
                "due_date": None,
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )
        main._DEMO_STORE["rubrics"].append(
            {
                "id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                "assignment_id": legacy_assignment_id,
                "criteria": criteria,
                "status": "draft",
                "created_by": None,
                "created_at": main._demo_now(),
                "updated_at": main._demo_now(),
            }
        )

        patch_legacy = self.client_a.patch(
            f"/api/rubrics/by-assignment/{legacy_assignment_id}",
            json={"status": "approved"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(patch_legacy.status_code, 403)

    def test_created_by_spoof_in_body_is_ignored(self):
        csrf_a = self._login_teacher(self.client_a)
        fake_id = "00000000-0000-4000-8000-000000000099"

        dept = self.client_a.post(
            "/api/departments",
            json={"name": "Spoof Dept", "created_by": fake_id},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(dept.status_code, 200)
        self.assertEqual(dept.json()["created_by"], _DEMO_TEACHER_ID)

        course = self.client_a.post(
            "/api/courses",
            json={
                "name": "Spoof Course",
                "code": "SC101",
                "class_year": 1,
                "department_id": _DEMO_DEPARTMENT_ID,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(course.status_code, 200)
        self.assertEqual(course.json()["created_by"], _DEMO_TEACHER_ID)

        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            assignment = self.client_a.post(
                "/api/assignments",
                json={"course_id": _DEMO_COURSE_ID, "name": "Spoof Assignment"},
                headers=self._csrf_headers(csrf_a),
            )
        self.assertEqual(assignment.status_code, 200)
        self.assertEqual(assignment.json()["created_by"], _DEMO_TEACHER_ID)

    def test_question_ownership_create_and_delete(self):
        csrf_a = self._login_teacher(self.client_a)
        _, csrf_b = self._register_teacher_b()

        created = self.client_a.post(
            "/api/questions",
            json={"content": "Teacher A question?"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(created.status_code, 200)
        question_id = created.json()["id"]
        self.assertEqual(created.json()["created_by"], _DEMO_TEACHER_ID)

        del_b = self.client_b.delete(
            f"/api/questions/{question_id}",
            headers=self._csrf_headers(csrf_b),
        )
        self.assertEqual(del_b.status_code, 404)

        del_a = self.client_a.delete(
            f"/api/questions/{question_id}",
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(del_a.status_code, 200)

    def test_mutation_without_csrf_returns_403(self):
        self._login_teacher(self.client_a)
        resp = self.client_a.post("/api/departments", json={"name": "No CSRF Dept"})
        self.assertEqual(resp.status_code, 403)

    def test_teacher_cannot_change_other_teacher_email_or_password(self):
        csrf_a = self._login_teacher(self.client_a)
        teacher_b_id, _ = self._register_teacher_b()

        email_resp = self.client_a.patch(
            f"/api/teacher/{teacher_b_id}/email",
            json={"email": "hijack@test.local"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(email_resp.status_code, 404)

        password_resp = self.client_a.patch(
            f"/api/teacher/{teacher_b_id}/password",
            json={"current_password": _DEMO_TEACHER_PASSWORD, "new_password": "yeni123456"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(password_resp.status_code, 404)

    def test_teacher_email_update_ignores_path_identity_and_uses_principal(self):
        csrf_a = self._login_teacher(self.client_a)
        new_email = "updated-demo@agentgrade.local"

        resp = self.client_a.patch(
            f"/api/teacher/{_DEMO_TEACHER_ID}/email",
            json={"email": new_email},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], new_email)

    def test_password_change_revokes_all_teacher_sessions(self):
        csrf_a = self._login_teacher(self.client_a)
        client_second = TestClient(main.app)
        self._login_teacher(client_second)

        resp = self.client_a.patch(
            f"/api/teacher/{_DEMO_TEACHER_ID}/password",
            json={"current_password": _DEMO_TEACHER_PASSWORD, "new_password": "yeniparola1"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(resp.status_code, 200)

        me_a = self.client_a.get("/api/auth/me")
        me_second = client_second.get("/api/auth/me")
        self.assertEqual(me_a.status_code, 401)
        self.assertEqual(me_second.status_code, 401)

    def test_password_change_revokes_sessions_before_persisting_new_password(self):
        csrf_a = self._login_teacher(self.client_a)
        client_pre_change = TestClient(main.app)
        self._login_teacher(client_pre_change)

        new_password = "yeniparola1"
        resp = self.client_a.patch(
            f"/api/teacher/{_DEMO_TEACHER_ID}/password",
            json={"current_password": _DEMO_TEACHER_PASSWORD, "new_password": new_password},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(resp.status_code, 200)

        old_login = TestClient(main.app)
        old_login_resp = old_login.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": _DEMO_TEACHER_PASSWORD},
        )
        self.assertEqual(old_login_resp.status_code, 401)

        new_login = TestClient(main.app)
        new_login_resp = new_login.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": new_password},
        )
        self.assertEqual(new_login_resp.status_code, 200)

        me_pre_change = client_pre_change.get("/api/auth/me")
        self.assertEqual(me_pre_change.status_code, 401)

    def test_password_change_returns_503_and_leaves_password_unchanged_when_lock_lease_lost(self):
        """Fail-closed: lost per-user lock lease must abort before session revoke / password write."""
        csrf_a = self._login_teacher(self.client_a)
        original_hash = main._DEMO_STORE["teachers"][0]["password_hash"]
        new_password = "yeniparola1"

        @asynccontextmanager
        async def user_lock_with_immediate_lease_loss(redis, role, user_id, *, ttl_seconds=10):
            async with user_lock(redis, role, user_id, ttl_seconds=ttl_seconds) as lock:
                lock.mark_lost()
                yield lock

        with patch("frontend.backend.main.user_lock", user_lock_with_immediate_lease_loss):
            resp = self.client_a.patch(
                f"/api/teacher/{_DEMO_TEACHER_ID}/password",
                json={"current_password": _DEMO_TEACHER_PASSWORD, "new_password": new_password},
                headers=self._csrf_headers(csrf_a),
            )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["detail"], "Oturum servisine ulaşılamıyor")
        self.assertEqual(main._DEMO_STORE["teachers"][0]["password_hash"], original_hash)

        new_login = TestClient(main.app)
        new_login_resp = new_login.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": new_password},
        )
        self.assertEqual(new_login_resp.status_code, 401)

    def test_password_change_returns_503_and_leaves_password_unchanged_when_revoke_fails(self):
        csrf_a = self._login_teacher(self.client_a)
        new_password = "yeniparola1"

        with patch.object(
            type(self)._session_store,
            "revoke_user_sessions",
            new=AsyncMock(side_effect=ConnectionError("redis down")),
        ):
            resp = self.client_a.patch(
                f"/api/teacher/{_DEMO_TEACHER_ID}/password",
                json={"current_password": _DEMO_TEACHER_PASSWORD, "new_password": new_password},
                headers=self._csrf_headers(csrf_a),
            )
        self.assertEqual(resp.status_code, 503)

        old_login = TestClient(main.app)
        old_login_resp = old_login.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": _DEMO_TEACHER_PASSWORD},
        )
        self.assertEqual(old_login_resp.status_code, 200)

        new_login = TestClient(main.app)
        new_login_resp = new_login.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": new_password},
        )
        self.assertEqual(new_login_resp.status_code, 401)

    def test_login_and_password_change_use_same_user_lock_key(self):
        """Deterministic proof that login and password-change share the per-user lock key."""
        csrf_a = self._login_teacher(self.client_a)
        calls: list[tuple[str, str]] = []

        async def _spy_acquire(redis, role, user_id, **kwargs):
            calls.append((role, user_id))
            return await acquire_user_lock(redis, role, user_id, **kwargs)

        with patch("backend.auth.sessions.acquire_user_lock", side_effect=_spy_acquire):
            login_resp = TestClient(main.app).post(
                "/api/teacher/login",
                json={"email": _DEMO_TEACHER_EMAIL, "password": _DEMO_TEACHER_PASSWORD},
            )
            self.assertEqual(login_resp.status_code, 200)

            pwd_resp = self.client_a.patch(
                f"/api/teacher/{_DEMO_TEACHER_ID}/password",
                json={"current_password": _DEMO_TEACHER_PASSWORD, "new_password": "yeniparola2"},
                headers=self._csrf_headers(csrf_a),
            )
            self.assertEqual(pwd_resp.status_code, 200)

        teacher_lock_calls = [
            (role, user_id) for role, user_id in calls if role == "teacher"
        ]
        self.assertGreaterEqual(len(teacher_lock_calls), 2)
        self.assertTrue(
            all(user_id == _DEMO_TEACHER_ID for _, user_id in teacher_lock_calls),
            f"Expected all teacher lock calls for {_DEMO_TEACHER_ID}, got {teacher_lock_calls}",
        )

    def test_login_returns_503_when_user_lock_held_for_entire_retry_budget(self):
        """While password-change holds the per-user lock, login must fail closed with 503."""
        import asyncio

        async def _hold_lock():
            return await acquire_user_lock(
                type(self)._fake_redis, "teacher", _DEMO_TEACHER_ID
            )

        token = asyncio.run(_hold_lock())
        try:
            fast_acquire = partial(
                acquire_user_lock,
                max_attempts=3,
                retry_delay_seconds=0.01,
            )
            with patch("backend.auth.sessions.acquire_user_lock", fast_acquire):
                resp = TestClient(main.app).post(
                    "/api/teacher/login",
                    json={"email": _DEMO_TEACHER_EMAIL, "password": _DEMO_TEACHER_PASSWORD},
                )
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.json()["detail"], "Oturum servisine ulaşılamıyor")
        finally:
            asyncio.run(
                release_user_lock(
                    type(self)._fake_redis, "teacher", _DEMO_TEACHER_ID, token
                )
            )

    def test_teacher_lists_students_only_in_owned_or_legacy_departments(self):
        csrf_a = self._login_teacher(self.client_a)
        teacher_b_id, csrf_b = self._register_teacher_b()

        dept_a = self.client_a.post(
            "/api/departments",
            json={"name": "Dept A Students"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(dept_a.status_code, 200)
        dept_a_id = dept_a.json()["id"]

        student_a = self.client_a.post(
            "/api/students",
            json={
                "student_no": "20251001",
                "tc_no": "10000000001",
                "first_name": "Student",
                "last_name": "A",
                "class_year": 1,
                "department_id": dept_a_id,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(student_a.status_code, 200)
        student_a_no = student_a.json()["student_no"]

        dept_b = self.client_b.post(
            "/api/departments",
            json={"name": "Dept B Students"},
            headers=self._csrf_headers(csrf_b),
        )
        self.assertEqual(dept_b.status_code, 200)
        dept_b_id = dept_b.json()["id"]

        student_b = self.client_b.post(
            "/api/students",
            json={
                "student_no": "20251002",
                "tc_no": "10000000002",
                "first_name": "Student",
                "last_name": "B",
                "class_year": 1,
                "department_id": dept_b_id,
            },
            headers=self._csrf_headers(csrf_b),
        )
        self.assertEqual(student_b.status_code, 200)
        student_b_no = student_b.json()["student_no"]

        legacy_dept_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        legacy_student_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        main._DEMO_STORE["departments"].append(
            {
                "id": legacy_dept_id,
                "name": "Legacy Dept Students",
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )
        main._DEMO_STORE["students"].append(
            {
                "id": legacy_student_id,
                "student_no": "20251003",
                "tc_no": "10000000003",
                "first_name": "Legacy",
                "last_name": "Student",
                "class_year": 1,
                "department_id": legacy_dept_id,
                "password_hash": main._hash_password(_DEMO_STUDENT_PASSWORD),
                "created_at": main._demo_now(),
            }
        )

        list_a = self.client_a.get("/api/students")
        self.assertEqual(list_a.status_code, 200)
        numbers_a = [s["student_no"] for s in list_a.json()]
        self.assertIn(student_a_no, numbers_a)
        self.assertIn("20251003", numbers_a)
        self.assertNotIn(student_b_no, numbers_a)

        list_b = self.client_b.get("/api/students")
        self.assertEqual(list_b.status_code, 200)
        numbers_b = [s["student_no"] for s in list_b.json()]
        self.assertIn(student_b_no, numbers_b)
        self.assertIn("20251003", numbers_b)
        self.assertNotIn(student_a_no, numbers_b)

    def test_teacher_cannot_create_update_delete_student_in_other_or_legacy_department(self):
        csrf_a = self._login_teacher(self.client_a)
        _, csrf_b = self._register_teacher_b()

        dept_b = self.client_b.post(
            "/api/departments",
            json={"name": "Dept B Mutate"},
            headers=self._csrf_headers(csrf_b),
        )
        self.assertEqual(dept_b.status_code, 200)
        dept_b_id = dept_b.json()["id"]

        legacy_dept_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        main._DEMO_STORE["departments"].append(
            {
                "id": legacy_dept_id,
                "name": "Legacy Dept Mutate",
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )

        dept_a = self.client_a.post(
            "/api/departments",
            json={"name": "Dept A Mutate"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(dept_a.status_code, 200)
        dept_a_id = dept_a.json()["id"]

        cross_create = self.client_a.post(
            "/api/students",
            json={
                "student_no": "20252001",
                "tc_no": "20000000001",
                "first_name": "Cross",
                "last_name": "Create",
                "class_year": 1,
                "department_id": dept_b_id,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(cross_create.status_code, 404)

        legacy_create = self.client_a.post(
            "/api/students",
            json={
                "student_no": "20252002",
                "tc_no": "20000000002",
                "first_name": "Legacy",
                "last_name": "Create",
                "class_year": 1,
                "department_id": legacy_dept_id,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(legacy_create.status_code, 403)

        own_create = self.client_a.post(
            "/api/students",
            json={
                "student_no": "20252003",
                "tc_no": "20000000003",
                "first_name": "Own",
                "last_name": "Create",
                "class_year": 1,
                "department_id": dept_a_id,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(own_create.status_code, 200)
        own_student_id = own_create.json()["id"]

        move_cross = self.client_a.patch(
            f"/api/students/{own_student_id}",
            json={
                "student_no": "20252003",
                "tc_no": "20000000003",
                "first_name": "Own",
                "last_name": "Create",
                "class_year": 1,
                "department_id": dept_b_id,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(move_cross.status_code, 404)

        move_legacy = self.client_a.patch(
            f"/api/students/{own_student_id}",
            json={
                "student_no": "20252003",
                "tc_no": "20000000003",
                "first_name": "Own",
                "last_name": "Create",
                "class_year": 1,
                "department_id": legacy_dept_id,
            },
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(move_legacy.status_code, 403)

        legacy_student_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        main._DEMO_STORE["students"].append(
            {
                "id": legacy_student_id,
                "student_no": "20252004",
                "tc_no": "20000000004",
                "first_name": "Legacy",
                "last_name": "Direct",
                "class_year": 1,
                "department_id": legacy_dept_id,
                "password_hash": main._hash_password(_DEMO_STUDENT_PASSWORD),
                "created_at": main._demo_now(),
            }
        )

        del_legacy = self.client_a.delete(
            f"/api/students/{legacy_student_id}",
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(del_legacy.status_code, 403)

        del_own = self.client_a.delete(
            f"/api/students/{own_student_id}",
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(del_own.status_code, 200)

    def test_csv_import_rejects_rows_for_unowned_department(self):
        csrf_a = self._login_teacher(self.client_a)
        _, csrf_b = self._register_teacher_b()

        dept_a = self.client_a.post(
            "/api/departments",
            json={"name": "CSV Dept A"},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(dept_a.status_code, 200)
        dept_a_name = dept_a.json()["name"]

        dept_b = self.client_b.post(
            "/api/departments",
            json={"name": "CSV Dept B"},
            headers=self._csrf_headers(csrf_b),
        )
        self.assertEqual(dept_b.status_code, 200)
        dept_b_name = dept_b.json()["name"]

        legacy_dept_name = "CSV Legacy Dept"
        main._DEMO_STORE["departments"].append(
            {
                "id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                "name": legacy_dept_name,
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )

        csv_bytes = (
            "student_no,tc_no,first_name,last_name,department,class_year\n"
            f"20253001,30000000001,CSV,Own,{dept_a_name},1\n"
            f"20253002,30000000002,CSV,Other,{dept_b_name},1\n"
            f"20253003,30000000003,CSV,Legacy,{legacy_dept_name},1\n"
        ).encode("utf-8")

        resp = self.client_a.post(
            "/api/students/import-csv",
            files={"file": ("students.csv", csv_bytes, "text/csv")},
            headers=self._csrf_headers(csrf_a),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        created_nos = [s["student_no"] for s in data["created"]]
        skipped_nos = [s["student_no"] for s in data["skipped"]]
        self.assertIn("20253001", created_nos)
        self.assertIn("20253002", skipped_nos)
        self.assertIn("20253003", skipped_nos)

    def test_teacher_evaluation_list_contains_only_owned_assignments(self):
        csrf_a = self._login_teacher(self.client_a)
        _, csrf_b = self._register_teacher_b()

        dept_b = self.client_b.post(
            "/api/departments",
            json={"name": "Dept Eval B"},
            headers=self._csrf_headers(csrf_b),
        )
        course_b = self.client_b.post(
            "/api/courses",
            json={
                "name": "Course Eval B",
                "code": "CEB101",
                "class_year": 1,
                "department_id": dept_b.json()["id"],
            },
            headers=self._csrf_headers(csrf_b),
        )
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            assignment_b = self.client_b.post(
                "/api/assignments",
                json={"course_id": course_b.json()["id"], "name": "Assignment Eval B"},
                headers=self._csrf_headers(csrf_b),
            )
        assignment_b_id = assignment_b.json()["id"]

        eval_a_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        eval_b_id = "00000000-0000-4000-8000-000000000001"
        main._DEMO_STORE["evaluations"] = [
            {
                "id": eval_a_id,
                "student_first_name": "Demo",
                "student_last_name": "Student",
                "student_no": _DEMO_STUDENT_NO,
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "uploaded_file_name": "a.py",
                "score": 80,
                "usefulness": None,
                "accuracy": None,
                "clarity": None,
                "comment": "",
                "status": "pending",
                "created_at": main._demo_now(),
                "submitted_at": None,
            },
            {
                "id": eval_b_id,
                "student_first_name": "Other",
                "student_last_name": "Student",
                "student_no": "20249999",
                "assignment_id": assignment_b_id,
                "uploaded_file_name": "b.py",
                "score": 70,
                "usefulness": None,
                "accuracy": None,
                "clarity": None,
                "comment": "",
                "status": "pending",
                "created_at": main._demo_now(),
                "submitted_at": None,
            },
        ]

        resp = self.client_a.get("/api/evaluations")
        self.assertEqual(resp.status_code, 200)
        eval_ids = [item["id"] for item in resp.json()]
        self.assertIn(eval_a_id, eval_ids)
        self.assertNotIn(eval_b_id, eval_ids)


class TeacherPgLoginSecurityTests(unittest.TestCase):
    def test_pg_login_verifies_against_freshly_fetched_password_not_a_pre_lock_snapshot(self):
        old_password = "oldpass1"
        new_password = "newpass2"
        email = "pgteacher@test.local"
        teacher_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        old_hash = main._hash_password(old_password)
        new_hash = main._hash_password(new_password)

        class FakePool:
            def __init__(self) -> None:
                self.call_count = 0

            async def fetchrow(self, query, *args):
                self.call_count += 1
                normalized = " ".join(query.split())
                if "SELECT id FROM public.teachers" in normalized and "password_hash" not in normalized:
                    return {"id": teacher_id}
                if self.call_count == 1 or "password_hash" not in normalized:
                    return {
                        "id": teacher_id,
                        "first_name": "Test",
                        "last_name": "Teacher",
                        "email": email,
                        "password_hash": old_hash,
                        "created_at": "2026-07-10T12:00:00Z",
                    }
                return {
                    "id": teacher_id,
                    "first_name": "Test",
                    "last_name": "Teacher",
                    "email": email,
                    "password_hash": new_hash,
                    "created_at": "2026-07-10T12:00:00Z",
                }

        pool = FakePool()
        fake_redis = _FakeSessionRedis()
        session_store = SessionStore(fake_redis, ttl_seconds=28800)
        orig_demo = main._DEMO_MODE

        async def override_store():
            return session_store

        main.app.dependency_overrides[get_auth_session_store] = override_store
        main.app.state.auth_session_store = session_store
        main._DEMO_MODE = False
        try:
            with patch.object(main, "_get_db_pool", new=AsyncMock(return_value=pool)):
                client = TestClient(main.app)
                resp = client.post(
                    "/api/teacher/login",
                    json={"email": email, "password": old_password},
                )
        finally:
            main._DEMO_MODE = orig_demo
            main.app.dependency_overrides.pop(get_auth_session_store, None)
            if hasattr(main.app.state, "auth_session_store"):
                delattr(main.app.state, "auth_session_store")

        self.assertEqual(resp.status_code, 401)
        self.assertGreaterEqual(pool.call_count, 2)


if __name__ == "__main__":
    unittest.main()
