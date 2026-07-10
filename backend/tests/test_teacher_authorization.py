"""
Teacher-only route authorization and ownership policy tests (Phase 2A Task 4).

Runs in DEMO_MODE with in-memory SessionStore override.
"""

from __future__ import annotations

import copy
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.auth.dependencies import CSRF_HEADER, get_auth_session_store
from backend.auth.sessions import SessionStore
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


if __name__ == "__main__":
    unittest.main()
