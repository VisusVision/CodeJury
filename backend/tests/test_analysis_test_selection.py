"""Worker-side authoritative test selection for the analysis pipeline."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from backend.algorithm_expectations.contracts import AlgorithmExpectationResolution
from backend.auth.models import AuthPrincipal
from backend.queue.analysis_jobs import AnalysisJobOwner, AnalysisJobStore, create_analysis_job, get_analysis_job
from backend.sandbox.errors import SandboxUnavailableError
from backend.testing.contracts import FormalTestCase, TestSelection as PipelineTestSelection
from backend.tests.test_analysis_jobs import DEFAULT_OWNER, FakeRedis
from backend.workers.analysis_worker import process_analysis_job
from frontend.backend import main


STUDENT_PRINCIPAL = AuthPrincipal(
    user_id="22222222-2222-4222-8222-222222222222",
    role="student",
    session_hash="session-hash",
    csrf_hash="csrf-hash",
)

STUDENT_PROFILE = {
    "id": "22222222-2222-4222-8222-222222222222",
    "student_no": "20240001",
    "first_name": "Demo",
    "last_name": "Student",
}

_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"


def _unknown_expectation_resolution() -> AlgorithmExpectationResolution:
    return AlgorithmExpectationResolution(
        expectation=None,
        status="unknown",
        cache_key="",
        generation_attempts=0,
    )


def _patch_unknown_expectation():
    return patch.object(
        main,
        "_resolve_algorithm_expectation",
        new=AsyncMock(return_value=_unknown_expectation_resolution()),
    )


def _faculty_case(case_id: str = "faculty-case-id") -> FormalTestCase:
    return FormalTestCase(
        id=case_id,
        name="faculty square",
        stdin="2\n",
        expected_stdout="4\n",
        visibility="hidden",
        source="manual",
        oracle="teacher",
    )


def _fake_client_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "client_fake_pass",
            "stdin": "99\n",
            "expected_stdout": "wrong-but-client-says-pass\n",
        }
    ]


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
        "rubric_breakdown": [
            {"criterion": "c0", "label": "Correctness", "weight": 100, "score": 88, "weighted_score": 88},
        ],
        "strengths": ["ok"],
        "weaknesses": [],
        "summary": "ok",
    }


def _make_selection(
    *,
    cases: tuple[FormalTestCase, ...] = (),
    source: str = "none",
    test_set_id: str | None = None,
    cache_key: str | None = None,
    cache_version: int | None = None,
    test_evidence_status: str = "unavailable",
) -> PipelineTestSelection:
    return PipelineTestSelection(
        cases=cases,
        source=source,  # type: ignore[arg-type]
        test_set_id=test_set_id,
        cache_key=cache_key,
        cache_version=cache_version,
        test_evidence_status=test_evidence_status,  # type: ignore[arg-type]
    )


class AnalysisEnqueueSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_ignores_client_test_cases_and_omits_them_from_queue(self):
        req = main.AnalysisRequest(
            file_name="main.py",
            file_content="print(int(input()) ** 2)\n",
            assignment_id="assignment-1",
            report_language="tr",
            test_cases=_fake_client_cases(),
        )
        store = MagicMock(redis=object())
        expected_owner = AnalysisJobOwner(
            owner_user_id=STUDENT_PRINCIPAL.user_id,
            owner_role="student",
            student_id=STUDENT_PRINCIPAL.user_id,
            assignment_id="assignment-1",
            assignment_owner_teacher_id=None,
        )

        with (
            patch.object(main, "_DEMO_MODE", True),
            patch.object(main, "_resolve_student_profile", new=AsyncMock(return_value=STUDENT_PROFILE)),
            patch.object(main, "_student_can_access_assignment", new=AsyncMock(return_value=True)),
            patch.object(main, "_fetch_assignment_brief_for_pipeline", new=AsyncMock(return_value="Assignment brief")),
            patch.object(main, "_fetch_faculty_rubric_criteria_for_pipeline", new=AsyncMock(return_value=[{"name": "Correctness"}])),
            patch.object(main, "_fetch_assignment_test_cases_for_pipeline", new=AsyncMock()) as fetch_cases,
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=store), create=True),
            patch.object(main, "get_worker_readiness", new=AsyncMock(return_value={
                "status": "ok", "analysis_ready": True,
                "worker_count": 1, "ready_worker_count": 1,
                "sandbox": {"mode": "pool", "pool_ready": True, "container_count": 2, "available_count": 2, "target_size": 2},
            })),
            patch.object(main, "create_analysis_job", new=AsyncMock(return_value={"job_id": "job-123", "status": "queued"}), create=True) as create_job,
        ):
            response = await main.analyze_code(req, STUDENT_PRINCIPAL)

        self.assertEqual(response, {"job_id": "job-123", "status": "queued"})
        fetch_cases.assert_not_awaited()
        queued_request = create_job.await_args.args[1]
        self.assertNotIn("test_cases", queued_request)
        create_job.assert_awaited_once_with(store, queued_request, owner=expected_owner)


class AnalysisWorkerSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = FakeRedis()
        self.store = AnalysisJobStore(
            self.redis,
            stream_name="stream:analysis_jobs",
            id_factory=lambda: "job-123",
            clock=lambda: "2026-05-05T12:00:00Z",
        )

    async def test_worker_uses_faculty_case_and_ignores_stale_queue_test_cases(self):
        await create_analysis_job(
            self.store,
            {
                "file_name": "main.py",
                "file_content": "print(int(input()) ** 2)\n",
                "assignment_id": _ASSIGNMENT_ID,
                "assignment_brief": "Square a number",
                "faculty_rubric_criteria": [{"name": "Correctness"}],
                "test_cases": _fake_client_cases(),
                "report_language": "tr",
            },
            owner=DEFAULT_OWNER,
        )
        captured: dict[str, Any] = {}

        async def provider(**kwargs):
            return _make_selection(cases=(_faculty_case(),), source="faculty", test_evidence_status="available")

        def _spy_run_in_sandbox(source_code, language, files=None, test_cases=None, **kwargs):
            captured["sandbox_test_cases"] = test_cases
            return {
                "compilation_success": True, "exit_code": 0, "stdout": "5\n", "stderr": "",
                "test_results": [], "execution_backend": "pool",
            }

        with (
            patch.dict("os.environ", {"ANALYSIS_WORKER_RELOAD": "0"}, clear=False),
            patch.object(main, "_default_test_selection_provider", new=provider),
            patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()),
            patch("backend.sandbox.executor.run_in_sandbox", side_effect=_spy_run_in_sandbox),
            patch("backend.agents.task_relevance.assess_task_relevance_llm", new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []})),
            patch.object(main, "_build_resource_recommendations", new=AsyncMock(return_value=[])),
            _patch_unknown_expectation(),
            patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.AlgorithmAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.AIAuthorshipAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
        ):
            await process_analysis_job(self.store, "job-123")

        self.assertEqual(captured["sandbox_test_cases"][0]["id"], "faculty-case-id")
        job = await get_analysis_job(self.store, "job-123")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["private_result"]["testSource"], "faculty")

    async def test_worker_loads_fresh_faculty_case_after_enqueue(self):
        faculty_state: list[tuple[FormalTestCase, ...]] = [()]

        async def provider(**kwargs):
            return _make_selection(
                cases=faculty_state[0],
                source="faculty" if faculty_state[0] else "none",
                test_evidence_status="available" if faculty_state[0] else "unavailable",
            )

        await create_analysis_job(
            self.store,
            {
                "file_name": "main.py",
                "file_content": "print(int(input()) ** 2)\n",
                "assignment_id": _ASSIGNMENT_ID,
                "assignment_brief": "Square a number",
                "report_language": "tr",
            },
            owner=DEFAULT_OWNER,
        )
        faculty_state[0] = (_faculty_case("fresh-faculty"),)
        captured: dict[str, Any] = {}

        def _spy_run_in_sandbox(source_code, language, files=None, test_cases=None, **kwargs):
            captured["sandbox_test_cases"] = test_cases
            return {
                "compilation_success": True, "exit_code": 0, "stdout": "5\n", "stderr": "",
                "test_results": [], "execution_backend": "pool",
            }

        with (
            patch.dict("os.environ", {"ANALYSIS_WORKER_RELOAD": "0"}, clear=False),
            patch.object(main, "_default_test_selection_provider", new=provider),
            patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()),
            patch("backend.sandbox.executor.run_in_sandbox", side_effect=_spy_run_in_sandbox),
            patch("backend.agents.task_relevance.assess_task_relevance_llm", new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []})),
            patch.object(main, "_build_resource_recommendations", new=AsyncMock(return_value=[])),
            _patch_unknown_expectation(),
            patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.AlgorithmAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.AIAuthorshipAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
            patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
        ):
            await process_analysis_job(self.store, "job-123")

        self.assertEqual(captured["sandbox_test_cases"][0]["id"], "fresh-faculty")


@pytest.mark.asyncio
async def test_python_without_faculty_invokes_selector_generation() -> None:
    generated = _make_selection(
        cases=(_faculty_case("generated-1"),),
        source="auto_generated",
        test_set_id="set-1",
        cache_key="cache-hash",
        cache_version=1,
        test_evidence_status="available",
    )
    provider = AsyncMock(return_value=generated)

    with (
        patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()),
        patch("backend.sandbox.executor.run_in_sandbox", return_value={
            "compilation_success": True, "exit_code": 0, "stdout": "", "stderr": "",
            "test_results": [], "execution_backend": "pool",
        }),
        patch("backend.agents.task_relevance.assess_task_relevance_llm", new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []})),
        patch.object(main, "_build_resource_recommendations", new=AsyncMock(return_value=[])),
        _patch_unknown_expectation(),
        patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.AlgorithmAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
    ):
        result = await main.run_analysis_pipeline(
            "submission.py",
            "print(int(input()) ** 2)\n",
            assignment_id=_ASSIGNMENT_ID,
            assignment_brief="Square a number",
            test_selection_provider=provider,
        )

    provider.assert_awaited_once()
    assert result["testSource"] == "auto_generated"
    assert result["testSetId"] == "set-1"
    assert result["testSetHash"] == "cache-hash"
    assert result["cacheVersion"] == 1
    assert result["testEvidenceStatus"] == "available"


@pytest.mark.parametrize("file_name", ["submission.cpp", "Main.java"])
@pytest.mark.asyncio
async def test_non_python_without_faculty_returns_unavailable_without_generation(file_name: str) -> None:
    provider = AsyncMock(return_value=_make_selection())

    with (
        patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()),
        patch("backend.sandbox.executor.run_in_sandbox", return_value={
            "compilation_success": True, "exit_code": 0, "stdout": "", "stderr": "",
            "test_results": [], "execution_backend": "pool",
        }) as sandbox,
        patch("backend.agents.task_relevance.assess_task_relevance_llm", new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []})),
        patch.object(main, "_build_resource_recommendations", new=AsyncMock(return_value=[])),
        _patch_unknown_expectation(),
        patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.AlgorithmAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
    ):
        result = await main.run_analysis_pipeline(
            file_name,
            "int main() { return 0; }\n",
            assignment_id=_ASSIGNMENT_ID,
            assignment_brief="C++ assignment",
            test_selection_provider=provider,
        )

    provider.assert_awaited_once()
    sandbox.assert_called_once()
    assert sandbox.call_args.kwargs.get("test_cases") == []
    assert result["testSource"] == "none"
    assert result["testEvidenceStatus"] == "unavailable"


@pytest.mark.asyncio
async def test_assignment_less_job_returns_unavailable_without_selection_store_access() -> None:
    default_provider = AsyncMock(side_effect=AssertionError("must not call default provider"))
    store = AsyncMock(side_effect=AssertionError("must not touch generated set store"))

    with (
        patch.object(main, "_default_test_selection_provider", new=default_provider),
        patch.object(main, "_get_generated_test_set_store", new=store),
        patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()),
        patch("backend.sandbox.executor.run_in_sandbox", return_value={
            "compilation_success": True, "exit_code": 0, "stdout": "", "stderr": "",
            "test_results": [], "execution_backend": "pool",
        }) as sandbox,
        patch("backend.agents.task_relevance.assess_task_relevance_llm", new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []})),
        patch.object(main, "_build_resource_recommendations", new=AsyncMock(return_value=[])),
        _patch_unknown_expectation(),
        patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.AlgorithmAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.AIAuthorshipAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.TestAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
    ):
        result = await main.run_analysis_pipeline(
            "submission.py",
            "print('ok')\n",
            assignment_id=None,
        )

    default_provider.assert_not_awaited()
    store.assert_not_awaited()
    sandbox.assert_called_once()
    assert sandbox.call_args.kwargs.get("test_cases") == []
    assert result["testSource"] == "none"
    assert result["testEvidenceStatus"] == "unavailable"


@pytest.mark.asyncio
async def test_generator_exception_fail_soft_continues_with_unavailable_evidence() -> None:
    captured: dict[str, Any] = {}

    async def _spy_test_agent(self, payload):
        captured["expected_output"] = payload.get("expected_output")
        return _good_agent_payload()

    provider = AsyncMock(return_value=_make_selection())

    with (
        patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()),
        patch("backend.sandbox.executor.run_in_sandbox", return_value={
            "compilation_success": True, "exit_code": 0, "stdout": "", "stderr": "",
            "test_results": [], "execution_backend": "pool",
        }),
        patch("backend.agents.task_relevance.assess_task_relevance_llm", new=AsyncMock(return_value={"factor": 0.9, "llm_off_topic": False, "reasons": []})),
        patch.object(main, "_build_resource_recommendations", new=AsyncMock(return_value=[])),
        _patch_unknown_expectation(),
        patch.object(main.CodeQualityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.AlgorithmAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.SeniorityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.GuidelineAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.SecurityAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.TestAgent, "analyze", new=_spy_test_agent),
        patch.object(main.EvidenceAgent, "analyze", new=AsyncMock(return_value=_good_agent_payload())),
        patch.object(main.MasterEvaluatorAgent, "analyze", new=AsyncMock(return_value=_good_master_payload())),
    ):
        result = await main.run_analysis_pipeline(
            "submission.py",
            "print('ok')\n",
            assignment_id=_ASSIGNMENT_ID,
            test_selection_provider=provider,
        )

    assert captured["expected_output"] == []
    assert result["testEvidenceStatus"] == "unavailable"


@pytest.mark.asyncio
async def test_selection_repository_corruption_fails_job_with_safe_error() -> None:
    redis = FakeRedis()
    store = AnalysisJobStore(
        redis,
        stream_name="stream:analysis_jobs",
        id_factory=lambda: "job-123",
        clock=lambda: "2026-05-05T12:00:00Z",
    )
    await create_analysis_job(
        store,
        {
            "file_name": "main.py",
            "file_content": "print('ok')",
            "assignment_id": _ASSIGNMENT_ID,
            "report_language": "tr",
        },
        owner=DEFAULT_OWNER,
    )

    async def provider(**kwargs):
        raise asyncpg.PostgresError("corrupt generated set row")

    with (
        patch.dict("os.environ", {"ANALYSIS_WORKER_RELOAD": "0"}, clear=False),
        patch.object(main, "_default_test_selection_provider", new=provider),
        patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=MagicMock()),
        patch("backend.workers.analysis_worker.logger.exception"),
    ):
        await process_analysis_job(store, "job-123")

    job = await get_analysis_job(store, "job-123")
    assert job["status"] == "failed"
    assert job["error"] == "Analiz tamamlanamadi. Lutfen tekrar deneyin."


@pytest.mark.asyncio
async def test_sandbox_unavailable_fails_job_closed() -> None:
    redis = FakeRedis()
    store = AnalysisJobStore(
        redis,
        stream_name="stream:analysis_jobs",
        id_factory=lambda: "job-123",
        clock=lambda: "2026-05-05T12:00:00Z",
    )
    await create_analysis_job(
        store,
        {"file_name": "main.py", "file_content": "print(1)", "assignment_id": _ASSIGNMENT_ID},
        owner=DEFAULT_OWNER,
    )

    async def pipeline(**kwargs):
        raise SandboxUnavailableError("pool_not_ready", "Sandbox kullanılamıyor", detail="down", retryable=True)

    job = await process_analysis_job(store, "job-123", pipeline=pipeline)
    assert job["status"] == "failed"
    assert "Sandbox" in job["error"]


if __name__ == "__main__":
    unittest.main()
