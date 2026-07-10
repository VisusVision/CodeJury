"""
Student self-access and server-bound identity tests (Phase 2A Task 6).

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

_DEMO_TEACHER_EMAIL = "demo@agentgrade.local"
_DEMO_TEACHER_PASSWORD = "demo123"
_DEMO_STUDENT_NO = "20240001"
_DEMO_STUDENT_ID = "22222222-2222-4222-8222-222222222222"
_DEMO_STUDENT_PASSWORD = "demo123"
_EMRETEST_STUDENT_ID = "22222222-2222-4222-8222-333333333333"
_EMRETEST_STUDENT_NO = "230501013"
_DEMO_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
_DEMO_DEPARTMENT_ID = "33333333-3333-4333-8333-333333333333"
_DEMO_COURSE_ID = "44444444-4444-4444-8444-444444444444"


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


class StudentAuthorizationTests(unittest.TestCase):
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
            if student["student_no"] == _EMRETEST_STUDENT_NO:
                student["password_hash"] = main._hash_password("emre123")

        cls._save_patcher = patch.object(main, "_save_demo_store_to_disk", lambda: None)
        cls._save_patcher.start()

        cls._fake_redis = _FakeSessionRedis()
        cls._session_store = SessionStore(cls._fake_redis, ttl_seconds=28800)

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
        self.client.cookies.clear()

    def tearDown(self):
        main._DEMO_STORE.clear()
        main._DEMO_STORE.update(copy.deepcopy(self._store_snapshot))

    def _login_teacher(self) -> str:
        resp = self.client.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": _DEMO_TEACHER_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        return self.client.cookies.get("agentgrade_csrf")

    def _login_student(
        self,
        client: TestClient | None = None,
        *,
        student_no: str = _DEMO_STUDENT_NO,
        password: str = _DEMO_STUDENT_PASSWORD,
    ) -> str:
        c = client or self.client
        resp = c.post(
            "/api/student/login",
            json={"student_no": student_no, "password": password},
        )
        self.assertEqual(resp.status_code, 200)
        return c.cookies.get("agentgrade_csrf")

    def _csrf_headers(self, csrf: str) -> dict[str, str]:
        return {CSRF_HEADER: csrf}

    @staticmethod
    def _valid_rubric_criteria():
        return [
            {"name": f"Kriter {i + 1}", "description": f"Aciklama {i + 1}", "max_score": 10}
            for i in range(10)
        ]

    def test_student_courses_uses_session_user_not_path_user(self):
        csrf = self._login_student()
        resp = self.client.get(
            f"/api/student/{_EMRETEST_STUDENT_ID}/courses",
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 200)
        course_ids = [c["id"] for c in resp.json()]
        self.assertIn(_DEMO_COURSE_ID, course_ids)

    def test_student_cannot_read_unenrolled_course_or_assignment(self):
        csrf_teacher = self._login_teacher()
        dept_resp = self.client.post(
            "/api/departments",
            json={"name": "Mismatch Dept"},
            headers=self._csrf_headers(csrf_teacher),
        )
        self.assertEqual(dept_resp.status_code, 200)
        mismatch_dept_id = dept_resp.json()["id"]

        course_resp = self.client.post(
            "/api/courses",
            json={
                "name": "Mismatch Course",
                "code": "MC401",
                "class_year": 4,
                "department_id": mismatch_dept_id,
            },
            headers=self._csrf_headers(csrf_teacher),
        )
        self.assertEqual(course_resp.status_code, 200)
        mismatch_course_id = course_resp.json()["id"]

        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            assignment_resp = self.client.post(
                "/api/assignments",
                json={"course_id": mismatch_course_id, "name": "Mismatch Assignment"},
                headers=self._csrf_headers(csrf_teacher),
            )
        self.assertEqual(assignment_resp.status_code, 200)
        mismatch_assignment_id = assignment_resp.json()["id"]

        rubric_resp = self.client.post(
            "/api/rubrics/upsert",
            json={
                "assignment_id": mismatch_assignment_id,
                "criteria": self._valid_rubric_criteria(),
                "status": "approved",
            },
            headers=self._csrf_headers(csrf_teacher),
        )
        self.assertEqual(rubric_resp.status_code, 200)

        self.client.cookies.clear()
        self._login_student()

        course_detail = self.client.get(f"/api/courses/{mismatch_course_id}")
        self.assertEqual(course_detail.status_code, 404)

        assignments_list = self.client.get(f"/api/courses/{mismatch_course_id}/assignments")
        self.assertEqual(assignments_list.status_code, 200)
        self.assertEqual(assignments_list.json(), [])

        assignment_detail = self.client.get(f"/api/assignments/{mismatch_assignment_id}")
        self.assertEqual(assignment_detail.status_code, 404)

        self.client.cookies.clear()
        csrf_teacher = self._login_teacher()
        draft_assignment_id = _DEMO_ASSIGNMENT_ID
        draft_resp = self.client.post(
            "/api/rubrics/upsert",
            json={
                "assignment_id": draft_assignment_id,
                "criteria": self._valid_rubric_criteria(),
                "status": "draft",
            },
            headers=self._csrf_headers(csrf_teacher),
        )
        self.assertEqual(draft_resp.status_code, 200)

        self.client.cookies.clear()
        self._login_student()
        student_rubric = self.client.get(f"/api/rubrics/by-assignment/{draft_assignment_id}")
        self.assertEqual(student_rubric.status_code, 200)
        self.assertIsNone(student_rubric.json())

        self.client.cookies.clear()
        self._login_teacher()
        teacher_rubric = self.client.get(f"/api/rubrics/by-assignment/{draft_assignment_id}")
        self.assertEqual(teacher_rubric.status_code, 200)
        self.assertIsNotNone(teacher_rubric.json())
        self.assertEqual(teacher_rubric.json()["status"], "draft")

    def test_upload_history_uses_session_profile_and_ignores_spoofed_student_fields(self):
        csrf = self._login_student()
        post_resp = self.client.post(
            "/api/upload-history",
            json={
                "student_first_name": "Spoofed",
                "student_last_name": "Identity",
                "student_no": _EMRETEST_STUDENT_NO,
                "uploaded_file_name": "odev.py",
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "score": 85,
                "has_error": False,
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(post_resp.status_code, 200)

        list_resp = self.client.get(f"/api/upload-history?student_no={_EMRETEST_STUDENT_NO}")
        self.assertEqual(list_resp.status_code, 200)
        rows = list_resp.json()
        self.assertTrue(rows)
        latest = rows[0]
        self.assertEqual(latest["student_no"], _DEMO_STUDENT_NO)
        self.assertEqual(latest["student_first_name"], "Demo")
        self.assertEqual(latest["student_last_name"], "Student")

    def test_current_evaluation_uses_session_student(self):
        csrf = self._login_student()
        self.client.post(
            "/api/upload-history",
            json={
                "student_first_name": "Demo",
                "student_last_name": "Student",
                "student_no": _DEMO_STUDENT_NO,
                "uploaded_file_name": "odev.py",
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "score": 88,
                "has_error": False,
            },
            headers=self._csrf_headers(csrf),
        )

        resp = self.client.get(
            f"/api/evaluations/current?student_no={_EMRETEST_STUDENT_NO}&assignment_id={_DEMO_ASSIGNMENT_ID}"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["student_no"], _DEMO_STUDENT_NO)
        self.assertEqual(data["assignment_id"], _DEMO_ASSIGNMENT_ID)

    def test_submit_evaluation_ignores_spoofed_student_no(self):
        csrf = self._login_student()
        self.client.post(
            "/api/upload-history",
            json={
                "student_first_name": "Demo",
                "student_last_name": "Student",
                "student_no": _DEMO_STUDENT_NO,
                "uploaded_file_name": "odev.py",
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "score": 88,
                "has_error": False,
            },
            headers=self._csrf_headers(csrf),
        )

        submit_resp = self.client.post(
            "/api/evaluations",
            json={
                "student_no": _EMRETEST_STUDENT_NO,
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "usefulness": 5,
                "accuracy": 4,
                "clarity": 5,
                "comment": "Tesekkurler",
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(submit_resp.status_code, 200)
        data = submit_resp.json()
        self.assertEqual(data["status"], "submitted")
        self.assertEqual(data["student_no"], _DEMO_STUDENT_NO)

    def test_teacher_role_cannot_call_student_mutations(self):
        csrf = self._login_teacher()

        upload_resp = self.client.post(
            "/api/upload-history",
            json={
                "student_first_name": "Demo",
                "student_last_name": "Student",
                "student_no": _DEMO_STUDENT_NO,
                "uploaded_file_name": "odev.py",
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "score": 85,
                "has_error": False,
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(upload_resp.status_code, 403)

        eval_resp = self.client.post(
            "/api/evaluations",
            json={
                "student_no": _DEMO_STUDENT_NO,
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "usefulness": 5,
                "accuracy": 4,
                "clarity": 5,
                "comment": "",
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(eval_resp.status_code, 403)

        courses_resp = self.client.get(f"/api/student/{_DEMO_STUDENT_ID}/courses")
        self.assertEqual(courses_resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
