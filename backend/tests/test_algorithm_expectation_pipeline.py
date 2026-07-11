"""Pipeline wiring for authoritative algorithm expectation resolution."""

from __future__ import annotations

import contextlib
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.algorithm_analysis.contracts import ComplexityEstimate
from backend.algorithm_expectations.cache import AlgorithmExpectationContext, compute_expectation_identity
from backend.algorithm_expectations.contracts import AlgorithmExpectation, AlgorithmExpectationResolution
from backend.algorithm_expectations.store import DemoAlgorithmExpectationStore
from backend.auth.models import AuthPrincipal
from backend.core.config import settings
from backend.testing.contracts import AssignmentDifficulty, TestSelection as PipelineTestSelection
from frontend.backend import main

_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
_STUDENT_PRINCIPAL = AuthPrincipal(
    user_id="22222222-2222-4222-8222-222222222222",
    role="student",
    session_hash="session-hash",
    csrf_hash="csrf-hash",
)
_STUDENT_PROFILE = {
    "id": "22222222-2222-4222-8222-222222222222",
    "student_no": "20240001",
    "first_name": "Demo",
    "last_name": "Student",
}
_TEACHER_PRINCIPAL = AuthPrincipal(
    user_id="11111111-1111-4111-8111-111111111111",
    role="teacher",
    session_hash="teacher-session",
    csrf_hash="teacher-csrf",
)
_SOURCE = "print(int(input()) ** 2)\n"


def _good_agent_payload() -> dict[str, Any]:
    return {
        "score": 85,
        "issues": [],
        "style_violations": [],
        "threats": [],
        "critical_count": 0,
        "high_count": 0,
        "risk_level": "safe",
        "safe": True,
        "compilation_success": True,
        "runs_successfully": True,
        "estimated_level": "mid",
        "naming_quality": "good",
        "time_complexity": "O(n)",
        "validated_claims": [],
        "total_claims_received": 0,
        "total_claims_validated": 0,
        "llm_status": "skipped_no_claims",
    }


def _good_master_payload() -> dict[str, Any]:
    return {
        "final_score": 88,
        "rubric_breakdown": [{"criterion": "c0", "label": "Correctness", "weight": 100, "score": 88, "weighted_score": 88}],
        "strengths": ["ok"],
        "weaknesses": [],
        "summary": "ok",
    }


def _context(
    *,
    assignment_id: str = _ASSIGNMENT_ID,
    title: str = "Binary Search",
    description: str = "Implement binary search. Required complexity O(log n).",
    rubric: tuple[dict, ...] | None = None,
    difficulty: AssignmentDifficulty = "medium",
) -> AlgorithmExpectationContext:
    return AlgorithmExpectationContext(
        assignment_id=assignment_id,
        title=title,
        description=description,
        rubric=rubric or ({"name": "Correctness", "max_score": 100},),
        difficulty=difficulty,
    )


def _cache_key(context: AlgorithmExpectationContext) -> str:
    provider = (settings.llm_provider or "ollama").strip().lower()
    if provider in {"nvidia_nim", "nim", "nvidia"}:
        provider, model = "nvidia_nim", settings.nvidia_nim_general_model
    else:
        provider, model = "ollama", settings.ollama_general_model
    return compute_expectation_identity(context, provider, model).cache_key


def _expectation(
    context: AlgorithmExpectationContext,
    *,
    expectation_id: str = "exp-1",
    active: bool = True,
) -> AlgorithmExpectation:
    provider = (settings.llm_provider or "ollama").strip().lower()
    if provider in {"nvidia_nim", "nim", "nvidia"}:
        provider, model = "nvidia_nim", settings.nvidia_nim_general_model
    else:
        provider, model = "ollama", settings.ollama_general_model
    return AlgorithmExpectation(
        id=expectation_id,
        assignment_id=context.assignment_id,
        cache_key=_cache_key(context),
        version=1,
        expected_complexity=ComplexityEstimate(
            expression="O(log n)",
            family="single_variable",
            rank=1,
            confidence=0.9,
            source="llm",
        ),
        expected_approach="binary search",
        algorithm_families=("binary_search",),
        confidence=0.9,
        extractor_provider=provider,
        extractor_model=model,
        verifier_provider=provider,
        verifier_model=model,
        schema_version=settings.algorithm_expectation_schema_version,
        extractor_prompt_version=settings.algorithm_expectation_extractor_prompt_version,
        verifier_prompt_version=settings.algorithm_expectation_verifier_prompt_version,
        verification_status="verified",
        active=active,
    )


def _resolution(
    context: AlgorithmExpectationContext,
    *,
    status: str = "available",
) -> AlgorithmExpectationResolution:
    expectation = _expectation(context)
    return AlgorithmExpectationResolution(
        expectation=expectation,
        status=status,  # type: ignore[arg-type]
        cache_key=expectation.cache_key,
        generation_attempts=0,
    )


def _make_demo_store() -> DemoAlgorithmExpectationStore:
    return DemoAlgorithmExpectationStore({"algorithm_expectations": []})


def _agent_patches(captured: dict[str, Any]):
    return (
        patch.object(
            main.CodeQualityAgent,
            "analyze",
            new=AsyncMock(side_effect=lambda p: (captured.__setitem__("code_quality", p), _good_agent_payload())[1]),
        ),
        patch.object(
            main.AlgorithmAgent,
            "analyze",
            new=AsyncMock(side_effect=lambda p: (captured.__setitem__("algorithm", p), _good_agent_payload())[1]),
        ),
        patch.object(
            main.AIAuthorshipAgent,
            "analyze",
            new=AsyncMock(side_effect=lambda p: (captured.__setitem__("ai_authorship", p), _good_agent_payload())[1]),
        ),
        patch.object(
            main.SeniorityAgent,
            "analyze",
            new=AsyncMock(side_effect=lambda p: (captured.__setitem__("seniority", p), _good_agent_payload())[1]),
        ),
        patch.object(
            main.GuidelineAgent,
            "analyze",
            new=AsyncMock(side_effect=lambda p: (captured.__setitem__("guideline", p), _good_agent_payload())[1]),
        ),
        patch.object(
            main.SecurityAgent,
            "analyze",
            new=AsyncMock(side_effect=lambda p: (captured.__setitem__("security", p), _good_agent_payload())[1]),
        ),
        patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
    )


@pytest.mark.asyncio
async def test_resolve_algorithm_expectation_never_receives_source_code() -> None:
    captured_context: dict[str, Any] = {}

    with (
        patch.object(main, "_DEMO_MODE", True),
        patch.object(main, "_get_algorithm_expectation_store", new=AsyncMock(return_value=_make_demo_store())),
        patch.object(main, "_get_testing_redis_client", new=AsyncMock(return_value=MagicMock())),
        patch.object(
            main,
            "_build_assignment_test_context",
            new=AsyncMock(return_value=MagicMock(
                assignment_id=_ASSIGNMENT_ID,
                title="Binary Search",
                description="Implement binary search.",
                rubric=[{"name": "Correctness"}],
                difficulty="medium",
            )),
        ),
        patch("backend.algorithm_expectations.service.resolve_expectation", new=AsyncMock()) as resolve_mock,
    ):
        async def _side_effect(context, **kwargs):
            captured_context["ctx"] = context
            return _resolution(context)

        resolve_mock.side_effect = _side_effect
        await main._resolve_algorithm_expectation(
            _ASSIGNMENT_ID,
            "Implement binary search.",
            [{"name": "Correctness"}],
            "medium",
        )

    ctx = captured_context["ctx"]
    dumped = ctx.model_dump()
    assert "source_code" not in dumped
    assert _SOURCE.strip() not in str(dumped)


@pytest.mark.asyncio
async def test_algorithm_agent_receives_resolved_expectation_other_agents_do_not() -> None:
    context = _context()
    resolution = _resolution(context)
    captured: dict[str, Any] = {}

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()))
        stack.enter_context(patch("backend.sandbox.executor.run_in_sandbox", return_value={
            "compilation_success": True, "exit_code": 0, "stdout": "", "stderr": "",
            "test_results": [], "execution_backend": "pool",
        }))
        stack.enter_context(patch("backend.agents.task_relevance.assess_task_relevance_llm", new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []})))
        stack.enter_context(patch.object(main, "_build_resource_recommendations", new=AsyncMock(return_value=[])))
        stack.enter_context(patch.object(main, "_resolve_algorithm_expectation", new=AsyncMock(return_value=resolution)))
        stack.enter_context(patch.object(main, "_default_test_selection_provider", new=AsyncMock(return_value=PipelineTestSelection(cases=(), source="none", test_evidence_status="unavailable"))))
        for item in _agent_patches(captured):
            stack.enter_context(item)
        await main.run_analysis_pipeline(
            "submission.py",
            _SOURCE,
            assignment_id=_ASSIGNMENT_ID,
            assignment_brief="Implement binary search.",
            faculty_rubric_criteria=[{"name": "Correctness"}],
        )

    assert captured["algorithm"]["algorithm_expectation"] == resolution.expectation.model_dump()
    for agent in ("code_quality", "ai_authorship", "seniority", "guideline", "security"):
        assert "algorithm_expectation" not in captured[agent]


@pytest.mark.asyncio
async def test_assignment_less_returns_unknown_without_expectation_store() -> None:
    store = AsyncMock(side_effect=AssertionError("must not touch expectation store"))

    result = await main._resolve_algorithm_expectation(None, "", [], None)
    assert result.status == "unknown"
    assert result.expectation is None

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(main, "_get_algorithm_expectation_store", new=store))
        stack.enter_context(patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()))
        stack.enter_context(patch("backend.sandbox.executor.run_in_sandbox", return_value={
            "compilation_success": True, "exit_code": 0, "stdout": "", "stderr": "",
            "test_results": [], "execution_backend": "pool",
        }))
        stack.enter_context(patch("backend.agents.task_relevance.assess_task_relevance_llm", new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []})))
        stack.enter_context(patch.object(main, "_build_resource_recommendations", new=AsyncMock(return_value=[])))
        stack.enter_context(patch.object(main, "_default_test_selection_provider", new=AsyncMock(return_value=PipelineTestSelection(cases=(), source="none", test_evidence_status="unavailable"))))
        for item in _agent_patches({}):
            stack.enter_context(item)
        await main.run_analysis_pipeline("submission.py", _SOURCE, assignment_id=None)

    store.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_expectation_db_unavailable_returns_unknown_fail_soft() -> None:
    from fastapi import HTTPException

    with patch.object(main, "_DEMO_MODE", False):
        with patch.object(
            main,
            "_build_assignment_test_context",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=500,
                    detail="Veritabani baglantisi hazir degil",
                )
            ),
        ):
            result = await main._resolve_algorithm_expectation(
                _ASSIGNMENT_ID,
                "Implement binary search.",
                [{"name": "Correctness"}],
                "medium",
            )

    assert result.status == "unknown"
    assert result.expectation is None


@pytest.mark.asyncio
async def test_difficulty_mutation_deactivates_cached_expectation() -> None:
    context = _context(difficulty="easy")
    store = _make_demo_store()
    expectation = _expectation(context)
    store._container["algorithm_expectations"].append({
        "id": expectation.id,
        "assignment_id": expectation.assignment_id,
        "cache_key": expectation.cache_key,
        "version": 1,
        "complexity": expectation.expected_complexity.model_dump(),
        "expected_approach": expectation.expected_approach,
        "algorithm_families": list(expectation.algorithm_families),
        "confidence": expectation.confidence,
        "extractor_provider": expectation.extractor_provider,
        "extractor_model": expectation.extractor_model,
        "verifier_provider": expectation.verifier_provider,
        "verifier_model": expectation.verifier_model,
        "schema_version": expectation.schema_version,
        "extractor_prompt_version": expectation.extractor_prompt_version,
        "verifier_prompt_version": expectation.verifier_prompt_version,
        "assignment_hash": "",
        "rubric_hash": "",
        "verification_status": "verified",
        "verification_reason": "",
        "active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "deactivated_at": None,
    })
    original_assignments = list(main._DEMO_STORE.get("assignments", []))
    main._DEMO_STORE["assignments"] = [{
        "id": _ASSIGNMENT_ID,
        "name": "Binary Search",
        "description": context.description,
        "created_by": _TEACHER_PRINCIPAL.user_id,
        "difficulty": "easy",
        "difficulty_source": "teacher",
        "course_id": "44444444-4444-4444-8444-444444444444",
    }]

    try:
        with patch.object(main, "_DEMO_MODE", True):
            with patch.object(main, "_get_algorithm_expectation_store", new=AsyncMock(return_value=store)):
                await main.update_assignment_difficulty(
                    _ASSIGNMENT_ID,
                    main.AssignmentDifficultyUpdateRequest(difficulty="hard"),
                    principal=_TEACHER_PRINCIPAL,
                )

        row = store._container["algorithm_expectations"][0]
        assert row["active"] is False
        assert row["deactivated_at"] is not None

        mutated = _context(difficulty="hard")
        assert _cache_key(mutated) != expectation.cache_key
    finally:
        main._DEMO_STORE["assignments"] = original_assignments


class AnalysisEnqueueExpectationTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_ignores_client_algorithm_expectation_in_queue(self):
        req = main.AnalysisRequest(
            file_name="main.py",
            file_content=_SOURCE,
            assignment_id=_ASSIGNMENT_ID,
            report_language="tr",
            algorithm_expectation={
                "expected_approach": "client_injected",
                "expected_complexity": {"expression": "O(1)", "family": "constant", "rank": 0, "confidence": 1.0, "source": "llm"},
            },
        )
        store = MagicMock(redis=object())

        with (
            patch.object(main, "_DEMO_MODE", True),
            patch.object(main, "_resolve_student_profile", new=AsyncMock(return_value=_STUDENT_PROFILE)),
            patch.object(main, "_student_can_access_assignment", new=AsyncMock(return_value=True)),
            patch.object(main, "_fetch_assignment_brief_for_pipeline", new=AsyncMock(return_value="Assignment brief")),
            patch.object(main, "_fetch_faculty_rubric_criteria_for_pipeline", new=AsyncMock(return_value=[{"name": "Correctness"}])),
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=store), create=True),
            patch.object(main, "get_worker_readiness", new=AsyncMock(return_value={
                "status": "ok", "analysis_ready": True,
                "worker_count": 1, "ready_worker_count": 1,
                "sandbox": {"mode": "pool", "pool_ready": True, "container_count": 2, "available_count": 2, "target_size": 2},
            })),
            patch.object(main, "create_analysis_job", new=AsyncMock(return_value={"job_id": "job-123", "status": "queued"}), create=True) as create_job,
        ):
            response = await main.analyze_code(req, _STUDENT_PRINCIPAL)

        self.assertEqual(response, {"job_id": "job-123", "status": "queued"})
        queued_request = create_job.await_args.args[1]
        self.assertNotIn("algorithm_expectation", queued_request)
