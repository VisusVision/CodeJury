"""
API Endpoint Testleri (FastAPI TestClient)

Tum testler DEMO_MODE'da calisir; PostgreSQL/Redis gerekmez.

Tasarim notlari:
- `_DEMO_MODE` modul yuklendiginde bir kez okunur. Test paketinde baska bir modul
  `frontend.backend.main`'i once import etmis olabileceginden, env'e guvenmek yerine
  modul global'ini dogrudan True yapariz; route handler'lari bu global'i cagri aninda
  okudugu icin import sirasindan bagimsiz, kararli sonuc alinir.
- Her test oncesi `_DEMO_STORE` derin kopyalanir, test sonrasi geri yuklenir (izolasyon).
- Disk yazimi (`_save_demo_store_to_disk`) ve odev guvenlik gecidi (LLM bagimli)
  no-op/patch edilir; testler deterministik kalir.
- Gercek rota yollari ve status kodlari main.py ile birebir dogrulanmistir.
"""

import copy
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth.dependencies import CSRF_HEADER, get_auth_session_store
from backend.auth.sessions import SessionStore
from frontend.backend import main


# Demo katalog sabitleri (main._DEMO_STORE ile ayni)
_DEMO_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
_DEMO_DEPARTMENT_ID = "33333333-3333-4333-8333-333333333333"
_DEMO_COURSE_ID = "44444444-4444-4444-8444-444444444444"
_DEMO_STUDENT_NO = "20240001"
_DEMO_STUDENT_TC = "11111111111"
_DEMO_STUDENT_PASSWORD = "demo123"
_EMRETEST_STUDENT_NO = "230501013"
_EMRETEST_STUDENT_PASSWORD = "emre123"
_DEMO_TEACHER_EMAIL = "demo@agentgrade.local"
_DEMO_TEACHER_PASSWORD = "demo123"


class _FakeSessionRedis:
    """In-memory Redis stand-in so login tests don't require a real Redis server."""

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


class ApiEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_demo_mode = main._DEMO_MODE
        main._DEMO_MODE = True
        # Demo ogretmeninin parola hash'i normalde startup hook'unda doldurulur;
        # testte startup calistirmadigimiz icin elle seed ediyoruz.
        main._DEMO_STORE["teachers"][0]["password_hash"] = main._hash_password(
            _DEMO_TEACHER_PASSWORD
        )
        for student in main._DEMO_STORE["students"]:
            if student["student_no"] == _DEMO_STUDENT_NO:
                student["password_hash"] = main._hash_password(_DEMO_STUDENT_PASSWORD)
        # Disk yazimini engelle (gercek .demo_store.json'a dokunma).
        cls._save_patcher = patch.object(main, "_save_demo_store_to_disk", lambda: None)
        cls._save_patcher.start()

        # Login testleri gercek Redis gerektirmesin diye bellek ici SessionStore
        # devreye alinir; ayni desen backend/tests/test_auth_api.py'de kullanilir.
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

    def _login_student(self) -> str:
        resp = self.client.post(
            "/api/student/login",
            json={"student_no": _DEMO_STUDENT_NO, "password": _DEMO_STUDENT_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        return self.client.cookies.get("agentgrade_csrf")

    def _csrf_headers(self, csrf: str) -> dict[str, str]:
        return {CSRF_HEADER: csrf}

    # ── Health ────────────────────────────────────────────────────────────────
    def test_health_returns_demo_mode_true(self):
        with patch.object(main, "_worker_readiness_snapshot", new=AsyncMock(return_value={
            "status": "ok", "analysis_ready": True,
            "worker_count": 1, "ready_worker_count": 1,
            "sandbox": {"mode": "pool", "pool_ready": True, "container_count": 2, "available_count": 2, "target_size": 2},
        })):
            resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["package"], "frontend")
        self.assertTrue(data["demo_mode"])

    def test_health_includes_llm_and_sandbox_runtime_config(self):
        with patch.object(main, "_worker_readiness_snapshot", new=AsyncMock(return_value={
            "status": "degraded", "analysis_ready": False,
            "worker_count": 0, "ready_worker_count": 0,
            "sandbox": {"mode": "unavailable", "pool_ready": False, "container_count": 0, "available_count": 0, "target_size": 0},
        })):
            resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        llm = data.get("llm")
        sandbox = data.get("sandbox")
        self.assertIsInstance(llm, dict)
        self.assertIsInstance(sandbox, dict)
        self.assertIn("general_model", llm)
        self.assertIn("coder_model", llm)
        self.assertIn("enabled", llm)
        self.assertIn("mode", sandbox)
        self.assertIn("pool_ready", sandbox)
        self.assertIn("analysis_ready", data)
        self.assertIn("worker_count", data)

    def test_upload_endpoint_enqueues_instead_of_running_pipeline(self):
        csrf = self._login_student()
        with (
            patch.object(main, "_enqueue_analysis_request", new=AsyncMock(return_value={"job_id": "job-upload", "status": "queued"})),
            patch.object(main, "run_analysis_pipeline", new=AsyncMock()) as pipeline,
        ):
            response = self.client.post(
                "/api/upload",
                files={"file": ("main.py", b"print('ok')", "text/x-python")},
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job_id"], "job-upload")
        pipeline.assert_not_awaited()

    # ── Students ────────────────────────────────────────────────────────────────
    def test_list_students_returns_seeded_student(self):
        self._login_teacher()
        resp = self.client.get("/api/students")
        self.assertEqual(resp.status_code, 200)
        numbers = [s["student_no"] for s in resp.json()]
        self.assertIn(_DEMO_STUDENT_NO, numbers)

    def test_create_student_valid(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/students",
            json={
                "student_no": "20259999",
                "tc_no": "22222222222",
                "first_name": "Yeni",
                "last_name": "Ogrenci",
                "class_year": 1,
                "department_id": _DEMO_DEPARTMENT_ID,
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["student_no"], "20259999")
        self.assertIn("id", data)

    def test_create_student_duplicate_returns_409(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/students",
            json={
                "student_no": _DEMO_STUDENT_NO,  # zaten var
                "tc_no": "33333333333",
                "first_name": "Kopya",
                "last_name": "Ogrenci",
                "class_year": 1,
                "department_id": _DEMO_DEPARTMENT_ID,
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 409)

    def test_create_student_invalid_tc_returns_400(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/students",
            json={
                "student_no": "20258888",
                "tc_no": "123",  # 11 haneli degil
                "first_name": "Hatali",
                "last_name": "Tc",
                "class_year": 1,
                "department_id": _DEMO_DEPARTMENT_ID,
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_student_missing_field_returns_422(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/students",
            json={"student_no": "1"},
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 422)

    # ── Student login ────────────────────────────────────────────────────────────
    def test_student_login_valid(self):
        resp = self.client.post(
            "/api/student/login",
            json={"student_no": _DEMO_STUDENT_NO, "password": _DEMO_STUDENT_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["student_no"], _DEMO_STUDENT_NO)

    def test_student_login_wrong_password_returns_401(self):
        resp = self.client.post(
            "/api/student/login",
            json={"student_no": _DEMO_STUDENT_NO, "password": "yanlis"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_student_login_rejects_legacy_tc_payload(self):
        resp = self.client.post(
            "/api/student/login",
            json={"student_no": _DEMO_STUDENT_NO, "tc_no": _DEMO_STUDENT_TC},
        )
        self.assertEqual(resp.status_code, 422)

    def test_student_login_emretest_password(self):
        resp = self.client.post(
            "/api/student/login",
            json={"student_no": _EMRETEST_STUDENT_NO, "password": _EMRETEST_STUDENT_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["student_no"], _EMRETEST_STUDENT_NO)

    # ── Teacher auth ────────────────────────────────────────────────────────────
    def test_teacher_register_valid(self):
        resp = self.client.post(
            "/api/teacher/register",
            json={
                "first_name": "Yeni",
                "last_name": "Ogretmen",
                "email": "yeni@ogretmen.local",
                "password": "parola123",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("id", resp.json())

    def test_teacher_register_duplicate_email_returns_409(self):
        resp = self.client.post(
            "/api/teacher/register",
            json={
                "first_name": "Kopya",
                "last_name": "Ogretmen",
                "email": _DEMO_TEACHER_EMAIL,  # zaten var
                "password": "parola123",
            },
        )
        self.assertEqual(resp.status_code, 409)

    def test_teacher_register_short_password_returns_400(self):
        resp = self.client.post(
            "/api/teacher/register",
            json={
                "first_name": "Kisa",
                "last_name": "Parola",
                "email": "kisa@ogretmen.local",
                "password": "123",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_teacher_login_valid(self):
        resp = self.client.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": _DEMO_TEACHER_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], _DEMO_TEACHER_EMAIL)

    def test_teacher_login_wrong_password_returns_401(self):
        resp = self.client.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": "yanlis"},
        )
        self.assertEqual(resp.status_code, 401)

    # ── Departments ────────────────────────────────────────────────────────────
    def test_list_departments(self):
        self._login_teacher()
        resp = self.client.get("/api/departments")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_create_department_valid(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/departments",
            json={"name": "Yeni Bolum"},
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("id", resp.json())

    def test_create_department_duplicate_returns_409(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/departments",
            json={"name": "Bilgisayar Muhendisligi"},
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 409)

    def test_create_department_invalid_json_returns_422(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/departments",
            content="duz metin",
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 422)

    # ── Courses ────────────────────────────────────────────────────────────────
    def test_list_courses(self):
        self._login_teacher()
        resp = self.client.get("/api/courses")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_create_course_valid(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/courses",
            json={
                "name": "Yeni Ders",
                "code": "YD101",
                "class_year": 2,
                "department_id": _DEMO_DEPARTMENT_ID,
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], "YD101")

    # ── Assignments ────────────────────────────────────────────────────────────
    def test_list_assignments(self):
        self._login_teacher()
        resp = self.client.get("/api/assignments")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_create_assignment_valid(self):
        csrf = self._login_teacher()
        # Odev guvenlik gecidi LLM'e bagli olabilir; deterministik kalmak icin patch'le.
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            resp = self.client.post(
                "/api/assignments",
                json={
                    "course_id": _DEMO_COURSE_ID,
                    "name": "Dizi Toplama Odevi",
                    "description": "Bir diziyi okuyup toplamini yazdirin.",
                },
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Dizi Toplama Odevi")

    def test_create_assignment_invalid_course_returns_400(self):
        csrf = self._login_teacher()
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            resp = self.client.post(
                "/api/assignments",
                json={"course_id": "yok-boyle-ders", "name": "Test"},
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(resp.status_code, 400)

    def test_create_assignment_with_manual_difficulty_sets_teacher_source(self):
        csrf = self._login_teacher()
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            resp = self.client.post(
                "/api/assignments",
                json={
                    "course_id": _DEMO_COURSE_ID,
                    "name": "Dosya Analizi",
                    "description": "CSV oku ve raporla",
                    "difficulty": "hard",
                },
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["difficulty"], "hard")
        self.assertEqual(data["difficulty_source"], "teacher")

    def test_create_assignment_with_ai_assistant_mode_sets_ai_selected_source(self):
        csrf = self._login_teacher()
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            resp = self.client.post(
                "/api/assignments",
                json={
                    "course_id": _DEMO_COURSE_ID,
                    "name": "X",
                    "difficulty": "easy",
                    "creation_mode": "ai_assistant",
                },
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["difficulty_source"], "ai_selected")

    def test_create_assignment_without_difficulty_defaults_to_medium_default_source(self):
        csrf = self._login_teacher()
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            resp = self.client.post(
                "/api/assignments",
                json={
                    "course_id": _DEMO_COURSE_ID,
                    "name": "Varsayilan Zorluk Odevi",
                    "description": "Aciklama",
                },
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["difficulty"], "medium")
        self.assertEqual(data["difficulty_source"], "default")

    def test_create_assignment_rejects_invalid_difficulty(self):
        csrf = self._login_teacher()
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            resp = self.client.post(
                "/api/assignments",
                json={
                    "course_id": _DEMO_COURSE_ID,
                    "name": "Gecersiz Zorluk",
                    "difficulty": "impossible",
                },
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(resp.status_code, 400)

    def test_list_assignments_includes_difficulty_fields(self):
        csrf = self._login_teacher()
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            create_resp = self.client.post(
                "/api/assignments",
                json={
                    "course_id": _DEMO_COURSE_ID,
                    "name": "Liste Zorluk Odevi",
                    "description": "Liste testi",
                    "difficulty": "easy",
                },
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(create_resp.status_code, 200)
        list_resp = self.client.get("/api/assignments")
        self.assertEqual(list_resp.status_code, 200)
        for item in list_resp.json():
            self.assertIn("difficulty", item)
            self.assertIn("difficulty_source", item)

    def test_assignment_detail_includes_difficulty_fields(self):
        csrf = self._login_teacher()
        with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
            create_resp = self.client.post(
                "/api/assignments",
                json={
                    "course_id": _DEMO_COURSE_ID,
                    "name": "Detay Zorluk Odevi",
                    "description": "Detay testi",
                    "difficulty": "medium",
                },
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(create_resp.status_code, 200)
        assignment_id = create_resp.json()["id"]
        detail_resp = self.client.get(f"/api/assignments/{assignment_id}")
        self.assertEqual(detail_resp.status_code, 200)
        data = detail_resp.json()
        self.assertIn("difficulty", data)
        self.assertIn("difficulty_source", data)

    def test_legacy_assignment_without_difficulty_is_lazily_inferred(self):
        csrf = self._login_teacher()
        legacy_assignment_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        main._DEMO_STORE["assignments"].append(
            {
                "id": legacy_assignment_id,
                "course_id": _DEMO_COURSE_ID,
                "name": "Legacy Difficulty Assignment",
                "description": "Eski kayit",
                "due_date": None,
                "created_by": None,
                "created_at": main._demo_now(),
            }
        )
        detail_resp = self.client.get(
            f"/api/assignments/{legacy_assignment_id}",
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(detail_resp.status_code, 200)
        data = detail_resp.json()
        self.assertIn(data["difficulty"], {"easy", "medium", "hard"})
        self.assertEqual(data["difficulty_source"], "inferred")

    # ── Rubrics ────────────────────────────────────────────────────────────────
    def test_assignment_test_cases_can_be_replaced_and_listed(self):
        csrf = self._login_teacher()
        payload = {
            "test_cases": [
                {
                    "name": "public normal",
                    "stdin": "6\n",
                    "expected_stdout": "36\n",
                    "expected_exit_code": 0,
                    "visibility": "public",
                    "source": "manual",
                },
                {
                    "name": "hidden zero",
                    "stdin": "0\n",
                    "expected_stdout": "0\n",
                    "visibility": "hidden",
                    "source": "ai",
                },
            ]
        }

        put_resp = self.client.put(
            f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases",
            json=payload,
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(put_resp.status_code, 200)

        get_resp = self.client.get(f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases")
        self.assertEqual(get_resp.status_code, 200)
        rows = get_resp.json()
        self.assertEqual([row["display_order"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["assignment_id"], _DEMO_ASSIGNMENT_ID)
        self.assertEqual(rows[0]["visibility"], "public")
        self.assertEqual(rows[1]["visibility"], "hidden")
        self.assertEqual(rows[1]["source"], "ai")

    def test_analyze_uses_saved_assignment_test_cases_when_request_has_no_override(self):
        main._DEMO_STORE.setdefault("assignment_test_cases", []).append(
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "name": "saved public",
                "stdin": "7\n",
                "expected_stdout": "49\n",
                "expected_exit_code": 0,
                "visibility": "public",
                "source": "manual",
                "display_order": 1,
            }
        )

        async def fake_create_analysis_job(_store, request, *, owner=None):
            return {"job_id": "job-saved-tests", "status": "queued", "request": request}

        csrf = self._login_student()
        store = MagicMock(redis=object())
        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=store)),
            patch.object(main, "get_worker_readiness", new=AsyncMock(return_value={
                "status": "ok", "analysis_ready": True,
                "worker_count": 1, "ready_worker_count": 1,
                "sandbox": {"mode": "pool", "pool_ready": True, "container_count": 2, "available_count": 2, "target_size": 2},
            })),
            patch.object(main, "create_analysis_job", new=AsyncMock(side_effect=fake_create_analysis_job)),
        ):
            resp = self.client.post(
                "/api/analyze",
                json={
                    "file_name": "main.py",
                    "file_content": "print(int(input()) ** 2)\n",
                    "assignment_id": _DEMO_ASSIGNMENT_ID,
                },
                headers=self._csrf_headers(csrf),
            )

        self.assertEqual(resp.status_code, 200)
        request = resp.json()["request"]
        self.assertEqual(request["test_cases"][0]["name"], "saved public")
        self.assertEqual(request["test_cases"][0]["expected_stdout"], "49\n")

    def test_assignment_test_case_suggestions_are_ai_source_and_not_persisted(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases/suggest",
            headers=self._csrf_headers(csrf),
        )

        self.assertEqual(resp.status_code, 200)
        suggestions = resp.json()["suggestions"]
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertTrue(all(row["source"] == "ai" for row in suggestions))

        saved_resp = self.client.get(f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases")
        self.assertEqual(saved_resp.status_code, 200)
        self.assertEqual(saved_resp.json(), [])

    def test_list_rubrics(self):
        self._login_teacher()
        resp = self.client.get("/api/rubrics")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_get_rubric_by_assignment(self):
        self._login_teacher()
        resp = self.client.get(f"/api/rubrics/by-assignment/{_DEMO_ASSIGNMENT_ID}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["assignment_id"], _DEMO_ASSIGNMENT_ID)

    @staticmethod
    def _valid_rubric_criteria():
        # Kisitlar: 10-20 kriter, her biri 5-10 puan, toplam 100.
        return [
            {"name": f"Kriter {i + 1}", "description": f"Aciklama {i + 1}", "max_score": 10}
            for i in range(10)
        ]

    def test_upsert_rubric_updates_existing(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/rubrics/upsert",
            json={
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "criteria": self._valid_rubric_criteria(),
                "status": "draft",
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["assignment_id"], _DEMO_ASSIGNMENT_ID)
        self.assertEqual(data["status"], "draft")

    def test_upsert_rubric_invalid_status_returns_400(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/rubrics/upsert",
            json={
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "criteria": self._valid_rubric_criteria(),
                "status": "gecersiz",
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 400)

    def test_upsert_rubric_too_few_criteria_returns_400(self):
        csrf = self._login_teacher()
        resp = self.client.post(
            "/api/rubrics/upsert",
            json={
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "criteria": [{"name": "Tek", "description": "D", "max_score": 100}],
                "status": "draft",
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_rubric_status(self):
        csrf = self._login_teacher()
        resp = self.client.patch(
            f"/api/rubrics/by-assignment/{_DEMO_ASSIGNMENT_ID}",
            json={"status": "approved"},
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "approved")

    # ── Upload history ────────────────────────────────────────────────────────────
    def test_create_upload_history_returns_status_ok(self):
        csrf = self._login_student()
        resp = self.client.post(
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
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_list_upload_history_by_student(self):
        csrf = self._login_student()
        self.client.post(
            "/api/upload-history",
            json={
                "student_first_name": "Demo",
                "student_last_name": "Student",
                "student_no": _DEMO_STUDENT_NO,
                "uploaded_file_name": "odev.py",
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "score": 90,
                "has_error": False,
            },
            headers=self._csrf_headers(csrf),
        )
        resp = self.client.get(f"/api/upload-history?student_no={_DEMO_STUDENT_NO}")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertIsInstance(rows, list)
        self.assertTrue(any(r["student_no"] == _DEMO_STUDENT_NO for r in rows))

    # ── Evaluations ────────────────────────────────────────────────────────────
    def test_submit_evaluation_after_upload(self):
        csrf = self._login_student()
        # Once skorlu bir teslim olusturulur -> bekleyen degerlendirme acilir.
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
        resp = self.client.post(
            "/api/evaluations",
            json={
                "student_no": _DEMO_STUDENT_NO,
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "usefulness": 5,
                "accuracy": 4,
                "clarity": 5,
                "comment": "Tesekkurler",
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "submitted")
        self.assertEqual(data["usefulness"], 5)

    def test_submit_evaluation_invalid_score_returns_400(self):
        csrf = self._login_student()
        resp = self.client.post(
            "/api/evaluations",
            json={
                "student_no": _DEMO_STUDENT_NO,
                "assignment_id": _DEMO_ASSIGNMENT_ID,
                "usefulness": 9,  # 1..5 disinda
                "accuracy": 4,
                "clarity": 5,
            },
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_evaluations(self):
        self._login_teacher()
        resp = self.client.get("/api/evaluations")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    # ── Analyze (kuyruk patch'li) ────────────────────────────────────────────────
    def test_analyze_enqueues_job(self):
        csrf = self._login_student()
        store = MagicMock(redis=object())
        with (
            patch.object(main, "_fetch_assignment_brief_for_pipeline", new=AsyncMock(return_value="brief")),
            patch.object(main, "_fetch_faculty_rubric_criteria_for_pipeline", new=AsyncMock(return_value=[])),
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=store)),
            patch.object(main, "get_worker_readiness", new=AsyncMock(return_value={
                "status": "ok", "analysis_ready": True,
                "worker_count": 1, "ready_worker_count": 1,
                "sandbox": {"mode": "pool", "pool_ready": True, "container_count": 2, "available_count": 2, "target_size": 2},
            })),
            patch.object(main, "create_analysis_job", new=AsyncMock(return_value={"job_id": "job-1", "status": "queued"})),
        ):
            resp = self.client.post(
                "/api/analyze",
                json={
                    "file_name": "main.py",
                    "file_content": "print('ok')",
                    "assignment_id": _DEMO_ASSIGNMENT_ID,
                },
                headers=self._csrf_headers(csrf),
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"job_id": "job-1", "status": "queued"})

    def test_analyze_missing_content_returns_422(self):
        csrf = self._login_student()
        resp = self.client.post(
            "/api/analyze",
            json={"file_name": "main.py"},
            headers=self._csrf_headers(csrf),
        )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
