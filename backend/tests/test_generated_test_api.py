"""Phase 2B Task 7: teacher suggest, generated-set read, and promote API tests."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.agents.base import LLMInferenceError
from backend.auth.dependencies import CSRF_HEADER, get_auth_session_store
from backend.auth.sessions import SessionStore
from backend.testing.contracts import FormalTestCase, GeneratedTestSet, OracleValidation
from backend.testing.generator import GenerationAttemptResult
from frontend.backend import main

_DEMO_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
_DEMO_COURSE_ID = "44444444-4444-4444-8444-444444444444"
_DEMO_TEACHER_EMAIL = "demo@agentgrade.local"
_DEMO_TEACHER_PASSWORD = "demo123"
_DEMO_STUDENT_NO = "20240001"
_DEMO_STUDENT_PASSWORD = "demo123"


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


def _oracle() -> OracleValidation:
    return OracleValidation(
        status="verified",
        provider="ollama",
        model="qwen2.5:7b",
        schema_version="test-set-v1",
        verified_at="2026-01-01T00:00:00+00:00",
    )


def _case(
    case_id: str,
    *,
    visibility: str = "hidden",
    source: str = "auto_generated",
) -> FormalTestCase:
    return FormalTestCase(
        id=case_id,
        name=f"case-{case_id}",
        stdin=f"{case_id}\n",
        expected_stdout=f"{case_id}\n",
        visibility=visibility,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        oracle="llm_verified" if source == "auto_generated" else "teacher",
        oracle_validation=_oracle() if source == "auto_generated" else None,
    )


def _verified_medium_cases() -> tuple[FormalTestCase, ...]:
    cases: list[FormalTestCase] = []
    for index in range(8):
        visibility = "public" if index < 2 else "hidden"
        cases.append(_case(f"case-{index}", visibility=visibility))
    return tuple(cases)


def _generation_result(cases: tuple[FormalTestCase, ...] | None = None) -> GenerationAttemptResult:
    resolved = cases or _verified_medium_cases()
    return GenerationAttemptResult(
        cases=resolved,
        rejected=(),
        provider="ollama",
        model="qwen2.5:7b",
        success=True,
    )


def _seed_generated_set(
    *,
    set_id: str = "set-1",
    assignment_id: str = _DEMO_ASSIGNMENT_ID,
    cases: tuple[FormalTestCase, ...] | None = None,
    active: bool = True,
) -> GeneratedTestSet:
    resolved = cases or _verified_medium_cases()
    test_set = GeneratedTestSet(
        id=set_id,
        assignment_id=assignment_id,
        cache_key="a" * 64,
        version=1,
        difficulty="medium",
        cases=resolved,
        provider="ollama",
        model="qwen2.5:7b",
        schema_version="test-set-v1",
        prompt_version="test-generator-v1",
        active=active,
        created_at=main._demo_now(),
    )
    row = {
        "id": test_set.id,
        "assignment_id": test_set.assignment_id,
        "cache_key": test_set.cache_key,
        "version": test_set.version,
        "difficulty": test_set.difficulty,
        "cases": [case.model_dump() for case in test_set.cases],
        "provider": test_set.provider,
        "model": test_set.model,
        "schema_version": test_set.schema_version,
        "prompt_version": test_set.prompt_version,
        "assignment_hash": "",
        "rubric_hash": "",
        "oracle_validation": [],
        "active": active,
        "created_at": test_set.created_at,
        "deactivated_at": None,
    }
    main._DEMO_STORE.setdefault("generated_test_sets", []).append(row)
    return test_set


@pytest.fixture()
def api_client():
    orig_demo_mode = main._DEMO_MODE
    main._DEMO_MODE = True
    main._DEMO_STORE["teachers"][0]["password_hash"] = main._hash_password(_DEMO_TEACHER_PASSWORD)
    for student in main._DEMO_STORE["students"]:
        if student["student_no"] == _DEMO_STUDENT_NO:
            student["password_hash"] = main._hash_password(_DEMO_STUDENT_PASSWORD)

    store_snapshot = copy.deepcopy(main._DEMO_STORE)
    fake_redis = _FakeSessionRedis()
    session_store = SessionStore(fake_redis, ttl_seconds=28800)

    async def _override_store():
        return session_store

    save_patcher = patch.object(main, "_save_demo_store_to_disk", lambda: None)
    save_patcher.start()
    main.app.dependency_overrides[get_auth_session_store] = _override_store
    main.app.state.auth_session_store = session_store
    client = TestClient(main.app)

    def _login_teacher() -> str:
        resp = client.post(
            "/api/teacher/login",
            json={"email": _DEMO_TEACHER_EMAIL, "password": _DEMO_TEACHER_PASSWORD},
        )
        assert resp.status_code == 200
        return client.cookies.get("agentgrade_csrf")

    def _login_student() -> str:
        resp = client.post(
            "/api/student/login",
            json={"student_no": _DEMO_STUDENT_NO, "password": _DEMO_STUDENT_PASSWORD},
        )
        assert resp.status_code == 200
        return client.cookies.get("agentgrade_csrf")

    yield {
        "client": client,
        "login_teacher": _login_teacher,
        "login_student": _login_student,
        "csrf_headers": lambda csrf: {CSRF_HEADER: csrf},
        "reset_store": lambda: (
            main._DEMO_STORE.clear(),
            main._DEMO_STORE.update(copy.deepcopy(store_snapshot)),
            fake_redis.reset(),
            setattr(main.app.state, "auth_session_store", session_store),
        ),
    }

    client.cookies.clear()
    main.app.dependency_overrides.pop(get_auth_session_store, None)
    save_patcher.stop()
    main._DEMO_MODE = orig_demo_mode
    main._DEMO_STORE.clear()
    main._DEMO_STORE.update(store_snapshot)


def test_suggest_does_not_persist(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    cases = _verified_medium_cases()

    with patch(
        "frontend.backend.main.generate_and_verify_once",
        new=AsyncMock(return_value=_generation_result(cases)),
    ):
        resp = api_client["client"].post(
            f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases/suggest",
            headers=api_client["csrf_headers"](csrf),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["persisted"] is False
    assert body["verified_count"] == len(cases)
    assert len(body["suggestions"]) == len(cases)
    assert all(row["source"] in {"auto_generated", "ai_approved"} for row in body["suggestions"])

    saved = api_client["client"].get(f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases")
    assert saved.status_code == 200
    assert saved.json() == []


def test_suggest_returns_503_on_llm_failure_without_write(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()

    with patch(
        "frontend.backend.main.generate_and_verify_once",
        new=AsyncMock(side_effect=LLMInferenceError("boom")),
    ):
        resp = api_client["client"].post(
            f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases/suggest",
            headers=api_client["csrf_headers"](csrf),
        )

    assert resp.status_code == 503
    saved = api_client["client"].get(f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases")
    assert saved.status_code == 200
    assert saved.json() == []


def test_suggest_returns_503_on_insufficient_generation_without_write(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    sparse = (_case("only-one", visibility="public"),)

    with patch(
        "frontend.backend.main.generate_and_verify_once",
        new=AsyncMock(return_value=_generation_result(sparse)),
    ):
        resp = api_client["client"].post(
            f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases/suggest",
            headers=api_client["csrf_headers"](csrf),
        )

    assert resp.status_code == 503
    saved = api_client["client"].get(f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases")
    assert saved.json() == []


@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("POST", "/api/assignments/{assignment_id}/test-cases/suggest"),
        ("GET", "/api/assignments/{assignment_id}/generated-test-set"),
        (
            "POST",
            "/api/assignments/{assignment_id}/generated-test-sets/{set_id}/promote",
        ),
    ],
)
def test_generated_test_routes_reject_anonymous(api_client, method, path_template):
    api_client["reset_store"]()
    path = path_template.format(assignment_id=_DEMO_ASSIGNMENT_ID, set_id="set-1")
    client = api_client["client"]
    if method == "GET":
        resp = client.get(path)
    else:
        resp = client.post(path, json={"case_ids": ["case-0"], "mode": "replace"})
    assert resp.status_code == 401


def test_generated_test_routes_reject_student(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_student"]()
    headers = api_client["csrf_headers"](csrf)
    client = api_client["client"]

    suggest = client.post(
        f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/test-cases/suggest",
        headers=headers,
    )
    assert suggest.status_code == 403

    read_set = client.get(f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/generated-test-set")
    assert read_set.status_code == 403

    promote = client.post(
        f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/generated-test-sets/set-1/promote",
        json={"case_ids": ["case-0"], "mode": "replace"},
        headers=headers,
    )
    assert promote.status_code == 403


def test_generated_test_set_read_returns_404_when_missing(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    resp = api_client["client"].get(
        f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/generated-test-set",
        headers=api_client["csrf_headers"](csrf),
    )
    assert resp.status_code == 404


def test_generated_test_set_read_returns_active_set(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    seeded = _seed_generated_set()

    resp = api_client["client"].get(
        f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/generated-test-set",
        headers=api_client["csrf_headers"](csrf),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == seeded.id
    assert body["assignment_id"] == _DEMO_ASSIGNMENT_ID
    assert body["active"] is True
    assert len(body["cases"]) == len(seeded.cases)


def test_promote_replace_sets_ai_approved_and_llm_verified(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    cases = _verified_medium_cases()
    seeded = _seed_generated_set(cases=cases)

    resp = api_client["client"].post(
        f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/generated-test-sets/{seeded.id}/promote",
        json={"case_ids": [cases[0].id, cases[1].id], "mode": "replace"},
        headers=api_client["csrf_headers"](csrf),
    )

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert [row["source"] for row in rows] == ["ai_approved", "ai_approved"]
    assert all(row["oracle"] == "llm_verified" for row in rows)
    assert all(row["oracle_validation"] is not None for row in rows)


def test_promote_invalid_case_id_rolls_back(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    cases = _verified_medium_cases()
    seeded = _seed_generated_set(cases=cases)
    main._DEMO_STORE.setdefault("assignment_test_cases", []).append(
        {
            "id": main._demo_uuid(),
            "assignment_id": _DEMO_ASSIGNMENT_ID,
            "name": "existing",
            "stdin": "",
            "expected_stdout": "1\n",
            "expected_exit_code": 0,
            "visibility": "public",
            "source": "manual",
            "files": [],
            "oracle": "teacher",
            "oracle_validation": None,
            "generated_set_id": None,
            "display_order": 1,
            "created_at": main._demo_now(),
            "updated_at": main._demo_now(),
        }
    )
    before = copy.deepcopy(main._DEMO_STORE["assignment_test_cases"])

    resp = api_client["client"].post(
        f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/generated-test-sets/{seeded.id}/promote",
        json={"case_ids": [cases[0].id, "missing-case"], "mode": "replace"},
        headers=api_client["csrf_headers"](csrf),
    )

    assert resp.status_code == 400
    assert main._DEMO_STORE["assignment_test_cases"] == before


def test_promote_append_preserves_existing(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    cases = _verified_medium_cases()
    seeded = _seed_generated_set(cases=cases)
    existing_id = main._demo_uuid()
    main._DEMO_STORE.setdefault("assignment_test_cases", []).append(
        {
            "id": existing_id,
            "assignment_id": _DEMO_ASSIGNMENT_ID,
            "name": "existing",
            "stdin": "",
            "expected_stdout": "1\n",
            "expected_exit_code": 0,
            "visibility": "public",
            "source": "manual",
            "files": [],
            "oracle": "teacher",
            "oracle_validation": None,
            "generated_set_id": None,
            "display_order": 1,
            "created_at": main._demo_now(),
            "updated_at": main._demo_now(),
        }
    )

    resp = api_client["client"].post(
        f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/generated-test-sets/{seeded.id}/promote",
        json={"case_ids": [cases[0].id], "mode": "append"},
        headers=api_client["csrf_headers"](csrf),
    )

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert any(row["id"] == existing_id for row in rows)
    assert any(row["source"] == "ai_approved" for row in rows)


def test_promote_leaves_generated_set_json_unchanged_and_deactivates(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    cases = _verified_medium_cases()
    seeded = _seed_generated_set(cases=cases)
    before = copy.deepcopy(main._DEMO_STORE["generated_test_sets"])

    resp = api_client["client"].post(
        f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/generated-test-sets/{seeded.id}/promote",
        json={"case_ids": [cases[0].id], "mode": "replace"},
        headers=api_client["csrf_headers"](csrf),
    )

    assert resp.status_code == 200
    before_row = next(row for row in before if row["id"] == seeded.id)
    after_row = next(row for row in main._DEMO_STORE["generated_test_sets"] if row["id"] == seeded.id)
    assert before_row["cases"] == after_row["cases"]
    assert after_row["active"] is False
    assert after_row["deactivated_at"] is not None
