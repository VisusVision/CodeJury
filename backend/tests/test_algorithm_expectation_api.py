"""Task 10: owner-read algorithm expectation API authorization tests."""

from __future__ import annotations

import copy
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.algorithm_analysis.contracts import ComplexityEstimate
from backend.algorithm_expectations.contracts import AlgorithmExpectation
from backend.auth.dependencies import CSRF_HEADER, get_auth_session_store
from backend.auth.sessions import SessionStore
from backend.tests.test_generated_test_api import _FakeSessionRedis, _DEMO_ASSIGNMENT_ID
from frontend.backend import main

_DEMO_TEACHER_EMAIL = "demo@agentgrade.local"
_DEMO_TEACHER_PASSWORD = "demo123"
_DEMO_STUDENT_NO = "20240001"
_DEMO_STUDENT_PASSWORD = "demo123"
_EXPECTATION_PATH = f"/api/assignments/{_DEMO_ASSIGNMENT_ID}/algorithm-expectation"


def _complexity() -> ComplexityEstimate:
    return ComplexityEstimate(
        expression="O(n log n)",
        family="single_variable",
        rank=3,
        confidence=0.92,
        source="verified_expectation",
    )


def _expectation(
    *,
    expectation_id: str = "exp-task10",
    cache_key: str = "a" * 64,
    active: bool = True,
) -> AlgorithmExpectation:
    return AlgorithmExpectation(
        id=expectation_id,
        assignment_id=_DEMO_ASSIGNMENT_ID,
        cache_key=cache_key,
        version=2,
        expected_complexity=_complexity(),
        expected_approach="sort then scan",
        algorithm_families=("sorting", "two_pointer"),
        confidence=0.92,
        extractor_provider="ollama",
        extractor_model="qwen2.5:7b",
        verifier_provider="ollama",
        verifier_model="qwen2.5:7b",
        schema_version="algorithm-expectation-v1",
        extractor_prompt_version="algorithm-extractor-v1",
        verifier_prompt_version="algorithm-verifier-v1",
        verification_status="verified",
        verification_reason="SENTINEL_VERIFIER_REASON_TASK10",
        active=active,
        created_at="2026-07-11T00:00:00+00:00",
    )


def _seed_expectation(expectation: AlgorithmExpectation | None = None) -> AlgorithmExpectation:
    resolved = expectation or _expectation()
    row = {
        "id": resolved.id,
        "assignment_id": resolved.assignment_id,
        "cache_key": resolved.cache_key,
        "version": resolved.version,
        "complexity": {
            "expression": resolved.expected_complexity.expression,
            "family": resolved.expected_complexity.family,
            "rank": resolved.expected_complexity.rank,
            "confidence": resolved.expected_complexity.confidence,
            "source": resolved.expected_complexity.source,
        },
        "expected_approach": resolved.expected_approach,
        "algorithm_families": list(resolved.algorithm_families),
        "confidence": resolved.confidence,
        "extractor_provider": resolved.extractor_provider,
        "extractor_model": resolved.extractor_model,
        "verifier_provider": resolved.verifier_provider,
        "verifier_model": resolved.verifier_model,
        "schema_version": resolved.schema_version,
        "extractor_prompt_version": resolved.extractor_prompt_version,
        "verifier_prompt_version": resolved.verifier_prompt_version,
        "verification_status": resolved.verification_status,
        "verification_reason": resolved.verification_reason,
        "active": resolved.active,
        "created_at": resolved.created_at,
        "deactivated_at": None,
    }
    main._DEMO_STORE.setdefault("algorithm_expectations", []).append(row)
    return resolved


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


def test_algorithm_expectation_route_has_no_mutation_methods():
    mutation_methods = {"POST", "PUT", "PATCH", "DELETE"}
    matching = [
        route
        for route in main.app.routes
        if hasattr(route, "path")
        and "algorithm-expectation" in route.path
        and getattr(route, "methods", set()) & mutation_methods
    ]
    assert matching == []


def test_algorithm_expectation_read_rejects_anonymous(api_client):
    api_client["reset_store"]()
    resp = api_client["client"].get(_EXPECTATION_PATH)
    assert resp.status_code == 401


def test_algorithm_expectation_read_rejects_student(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_student"]()
    resp = api_client["client"].get(
        _EXPECTATION_PATH,
        headers=api_client["csrf_headers"](csrf),
    )
    assert resp.status_code == 403


def test_algorithm_expectation_read_returns_404_when_missing(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    resp = api_client["client"].get(
        _EXPECTATION_PATH,
        headers=api_client["csrf_headers"](csrf),
    )
    assert resp.status_code == 404


def test_algorithm_expectation_read_returns_active_expectation_with_provenance(api_client):
    api_client["reset_store"]()
    csrf = api_client["login_teacher"]()
    seeded = _seed_expectation()

    resp = api_client["client"].get(
        _EXPECTATION_PATH,
        headers=api_client["csrf_headers"](csrf),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == seeded.id
    assert body["assignmentId"] == _DEMO_ASSIGNMENT_ID
    assert body["cacheKey"] == seeded.cache_key
    assert body["version"] == seeded.version
    assert body["expectedComplexity"] == "O(n log n)"
    assert body["expectedApproach"] == seeded.expected_approach
    assert body["algorithmFamilies"] == ["sorting", "two_pointer"]
    assert body["confidence"] == seeded.confidence
    assert body["verificationStatus"] == "verified"
    assert body["verificationReason"] == seeded.verification_reason
    assert body["extractorProvider"] == seeded.extractor_provider
    assert body["extractorModel"] == seeded.extractor_model
    assert body["verifierProvider"] == seeded.verifier_provider
    assert body["verifierModel"] == seeded.verifier_model
    assert body["extractorPromptVersion"] == seeded.extractor_prompt_version
    assert body["verifierPromptVersion"] == seeded.verifier_prompt_version


def test_algorithm_expectation_read_cross_owner_returns_404(api_client):
    api_client["reset_store"]()
    _seed_expectation()

    register = api_client["client"].post(
        "/api/teacher/register",
        json={
            "first_name": "Other",
            "last_name": "Teacher",
            "email": "othert10@test.local",
            "password": "parola123",
        },
    )
    assert register.status_code == 200
    login = api_client["client"].post(
        "/api/teacher/login",
        json={"email": "othert10@test.local", "password": "parola123"},
    )
    assert login.status_code == 200
    csrf = api_client["client"].cookies.get("agentgrade_csrf")

    resp = api_client["client"].get(
        _EXPECTATION_PATH,
        headers=api_client["csrf_headers"](csrf),
    )
    assert resp.status_code == 404
