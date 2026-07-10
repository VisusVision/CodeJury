import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.auth.dependencies import require_student
from backend.auth.models import AuthPrincipal
from backend.queue.analysis_jobs import (
    AnalysisJobOwner,
    AnalysisJobStore,
    create_analysis_job,
    get_analysis_job,
    update_analysis_job_result,
)
from backend.tests.test_analysis_jobs import FakeRedis
from frontend.backend import main


_DEMO_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
_DEMO_STUDENT_ID = "22222222-2222-4222-8222-222222222222"
_DEMO_TEACHER_ID = "11111111-1111-4111-8111-111111111111"
_OTHER_STUDENT_ID = "33333333-3333-4333-8333-333333333333"
_OTHER_TEACHER_ID = "44444444-4444-4444-8444-444444444444"

STUDENT_PROFILE = {
    "id": _DEMO_STUDENT_ID,
    "student_no": "20240001",
    "first_name": "Demo",
    "last_name": "Student",
}

HIDDEN_TEST_PRIVATE_RESULT = {
    "totalScore": 70,
    "agents": [
        {
            "id": "testing",
            "name": "Testing",
            "testResults": [
                {
                    "name": "hidden1",
                    "visibility": "hidden",
                    "input": "secret input value",
                    "expected": "secret expected value",
                    "actual": "wrong output",
                    "passed": False,
                }
            ],
        }
    ],
}


def _student_principal(user_id: str = _DEMO_STUDENT_ID) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        role="student",
        session_hash="session-hash",
        csrf_hash="csrf-hash",
    )


def _teacher_principal(user_id: str = _DEMO_TEACHER_ID) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        role="teacher",
        session_hash="session-hash",
        csrf_hash="csrf-hash",
    )


class AnalysisJobAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = FakeRedis()
        self.store = AnalysisJobStore(
            self.redis,
            stream_name="stream:analysis_jobs",
            job_ttl_seconds=60,
            id_factory=lambda: "job-auth-1",
            clock=lambda: "2026-05-05T12:00:00Z",
        )

    def test_enqueue_requires_student_role(self):
        signature = inspect.signature(main.analyze_code)
        self.assertIn("principal", signature.parameters)
        principal_param = signature.parameters["principal"]
        self.assertIsNotNone(principal_param.default)
        self.assertEqual(principal_param.default.dependency, require_student)

    async def test_spoofed_student_no_in_request_is_ignored(self):
        req = main.AnalysisRequest(
            file_name="main.py",
            file_content="print('ok')",
            student_no="SPOOFED-999",
        )
        principal = _student_principal()
        store = MagicMock(redis=object())
        captured_request: dict = {}

        async def capture_create(_store, request, *, owner):
            captured_request.update(request)
            return {"job_id": "job-123", "status": "queued"}

        with (
            patch.object(main, "_resolve_student_profile", new=AsyncMock(return_value=STUDENT_PROFILE)),
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=store)),
            patch.object(main, "get_worker_readiness", new=AsyncMock(return_value={
                "status": "ok", "analysis_ready": True,
                "worker_count": 1, "ready_worker_count": 1,
                "sandbox": {"mode": "pool", "pool_ready": True, "container_count": 2, "available_count": 2, "target_size": 2},
            })),
            patch.object(main, "_fetch_assignment_brief_for_pipeline", new=AsyncMock(return_value="")),
            patch.object(main, "_fetch_faculty_rubric_criteria_for_pipeline", new=AsyncMock(return_value=[])),
            patch.object(main, "create_analysis_job", new=AsyncMock(side_effect=capture_create)),
        ):
            await main._enqueue_analysis_request(req, principal)

        self.assertEqual(captured_request["student_no"], "20240001")

    async def test_owner_student_reads_own_job_gets_student_result(self):
        owner = AnalysisJobOwner(
            owner_user_id=_DEMO_STUDENT_ID,
            owner_role="student",
            student_id=_DEMO_STUDENT_ID,
            assignment_id=_DEMO_ASSIGNMENT_ID,
            assignment_owner_teacher_id=_DEMO_TEACHER_ID,
        )
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=owner)
        await update_analysis_job_result(self.store, "job-auth-1", HIDDEN_TEST_PRIVATE_RESULT)

        stored_job = await get_analysis_job(self.store, "job-auth-1")
        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=self.store)),
            patch.object(main, "get_analysis_job", new=AsyncMock(return_value=stored_job)),
        ):
            response = await main.get_analysis_job_status("job-auth-1", _student_principal())

        self.assertEqual(response["result"], stored_job["student_result"])
        hidden_case = response["result"]["agents"][0]["testResults"][0]
        self.assertNotIn("input", hidden_case)

    async def test_cross_student_read_returns_404(self):
        owner = AnalysisJobOwner(
            owner_user_id=_DEMO_STUDENT_ID,
            owner_role="student",
            student_id=_DEMO_STUDENT_ID,
            assignment_id=None,
            assignment_owner_teacher_id=None,
        )
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=owner)
        await update_analysis_job_result(self.store, "job-auth-1", {"totalScore": 90})
        stored_job = await get_analysis_job(self.store, "job-auth-1")

        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=self.store)),
            patch.object(main, "get_analysis_job", new=AsyncMock(return_value=stored_job)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await main.get_analysis_job_status("job-auth-1", _student_principal(_OTHER_STUDENT_ID))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_assignment_owner_teacher_reads_private_result(self):
        owner = AnalysisJobOwner(
            owner_user_id=_DEMO_STUDENT_ID,
            owner_role="student",
            student_id=_DEMO_STUDENT_ID,
            assignment_id=_DEMO_ASSIGNMENT_ID,
            assignment_owner_teacher_id=_DEMO_TEACHER_ID,
        )
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=owner)
        await update_analysis_job_result(self.store, "job-auth-1", HIDDEN_TEST_PRIVATE_RESULT)
        stored_job = await get_analysis_job(self.store, "job-auth-1")

        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=self.store)),
            patch.object(main, "get_analysis_job", new=AsyncMock(return_value=stored_job)),
        ):
            response = await main.get_analysis_job_status("job-auth-1", _teacher_principal())

        self.assertEqual(response["result"], stored_job["private_result"])
        hidden_case = response["result"]["agents"][0]["testResults"][0]
        self.assertEqual(hidden_case["input"], "secret input value")

    async def test_other_teacher_reads_404(self):
        owner = AnalysisJobOwner(
            owner_user_id=_DEMO_STUDENT_ID,
            owner_role="student",
            student_id=_DEMO_STUDENT_ID,
            assignment_id=_DEMO_ASSIGNMENT_ID,
            assignment_owner_teacher_id=_DEMO_TEACHER_ID,
        )
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=owner)
        await update_analysis_job_result(self.store, "job-auth-1", {"totalScore": 90})
        stored_job = await get_analysis_job(self.store, "job-auth-1")

        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=self.store)),
            patch.object(main, "get_analysis_job", new=AsyncMock(return_value=stored_job)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await main.get_analysis_job_status("job-auth-1", _teacher_principal(_OTHER_TEACHER_ID))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_assignmentless_job_is_hidden_from_all_teachers(self):
        owner = AnalysisJobOwner(
            owner_user_id=_DEMO_STUDENT_ID,
            owner_role="student",
            student_id=_DEMO_STUDENT_ID,
            assignment_id=None,
            assignment_owner_teacher_id=None,
        )
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=owner)
        await update_analysis_job_result(self.store, "job-auth-1", {"totalScore": 90})
        stored_job = await get_analysis_job(self.store, "job-auth-1")

        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=self.store)),
            patch.object(main, "get_analysis_job", new=AsyncMock(return_value=stored_job)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await main.get_analysis_job_status("job-auth-1", _teacher_principal())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_legacy_job_without_owner_metadata_is_fail_closed_for_everyone(self):
        await self.redis.hset(
            "analysis_job:legacy-job",
            {
                "job_id": "legacy-job",
                "status": "completed",
                "request": '{"file_name":"main.py"}',
                "created_at": "2026-05-05T12:00:00Z",
                "updated_at": "2026-05-05T12:00:00Z",
                "attempts": 1,
                "private_result": '{"totalScore": 90}',
                "student_result": '{"totalScore": 90}',
            },
        )
        stored_job = await get_analysis_job(self.store, "legacy-job")

        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=self.store)),
            patch.object(main, "get_analysis_job", new=AsyncMock(return_value=stored_job)),
        ):
            with self.assertRaises(HTTPException) as student_ctx:
                await main.get_analysis_job_status("legacy-job", _student_principal())
            with self.assertRaises(HTTPException) as teacher_ctx:
                await main.get_analysis_job_status("legacy-job", _teacher_principal())

        self.assertEqual(student_ctx.exception.status_code, 404)
        self.assertEqual(teacher_ctx.exception.status_code, 404)

    async def test_preparing_progress_result_is_also_redacted_for_student(self):
        owner = AnalysisJobOwner(
            owner_user_id=_DEMO_STUDENT_ID,
            owner_role="student",
            student_id=_DEMO_STUDENT_ID,
            assignment_id=_DEMO_ASSIGNMENT_ID,
            assignment_owner_teacher_id=_DEMO_TEACHER_ID,
        )
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=owner)
        await update_analysis_job_result(
            self.store,
            "job-auth-1",
            HIDDEN_TEST_PRIVATE_RESULT,
            report_status="preparing",
        )
        stored_job = await get_analysis_job(self.store, "job-auth-1")

        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=self.store)),
            patch.object(main, "get_analysis_job", new=AsyncMock(return_value=stored_job)),
        ):
            student_response = await main.get_analysis_job_status("job-auth-1", _student_principal())
            teacher_response = await main.get_analysis_job_status("job-auth-1", _teacher_principal())

        student_hidden = student_response["result"]["agents"][0]["testResults"][0]
        teacher_hidden = teacher_response["result"]["agents"][0]["testResults"][0]
        self.assertNotIn("input", student_hidden)
        self.assertEqual(teacher_hidden["input"], "secret input value")
        self.assertEqual(student_response["report_status"], "preparing")


if __name__ == "__main__":
    unittest.main()
