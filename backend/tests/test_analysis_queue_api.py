import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from frontend.backend import main
from backend.queue.analysis_jobs import AnalysisJobNotFound


class AnalysisQueueApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_code_enqueues_job_and_returns_job_id(self):
        req = main.AnalysisRequest(
            file_name="main.py",
            file_content="print('ok')",
            assignment_id="assignment-1",
            report_language="tr",
        )
        store = MagicMock(redis=object())

        with (
            patch.object(main, "_fetch_assignment_brief_for_pipeline", new=AsyncMock(return_value="Assignment brief")),
            patch.object(main, "_fetch_faculty_rubric_criteria_for_pipeline", new=AsyncMock(return_value=[{"name": "Correctness"}])),
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=store), create=True),
            patch.object(main, "get_worker_readiness", new=AsyncMock(return_value={
                "status": "ok", "analysis_ready": True,
                "worker_count": 1, "ready_worker_count": 1,
                "sandbox": {"mode": "pool", "pool_ready": True, "container_count": 2, "available_count": 2, "target_size": 2},
            })),
            patch.object(main, "create_analysis_job", new=AsyncMock(return_value={"job_id": "job-123", "status": "queued"}), create=True) as create_job,
            patch.object(main, "run_analysis_pipeline", new=AsyncMock(side_effect=AssertionError("pipeline should run in worker"))),
        ):
            response = await main.analyze_code(req)

        self.assertEqual(response, {"job_id": "job-123", "status": "queued"})
        create_job.assert_awaited_once_with(
            store,
            {
                "file_name": "main.py",
                "file_content": "print('ok')",
                "assignment_id": "assignment-1",
                "assignment_brief": "Assignment brief",
                "faculty_rubric_criteria": [{"name": "Correctness"}],
                "test_cases": [],
                "report_language": "tr",
                "student_no": "",
            },
        )

    async def test_analyze_rejects_before_queue_when_no_worker_pool_is_ready(self):
        req = main.AnalysisRequest(file_name="main.py", file_content="print(1)")
        store = MagicMock(redis=object())
        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=store)),
            patch.object(main, "get_worker_readiness", new=AsyncMock(return_value={
                "status": "degraded", "analysis_ready": False,
                "worker_count": 0, "ready_worker_count": 0,
                "sandbox": {"mode": "unavailable", "pool_ready": False, "container_count": 0, "available_count": 0},
            })),
            patch.object(main, "create_analysis_job", new=AsyncMock()) as create_job,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await main.analyze_code(req)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("Sandbox", str(ctx.exception.detail))
        create_job.assert_not_awaited()

    async def test_get_analysis_job_status_returns_job_without_internal_request_payload(self):
        store = object()
        stored_job = {
            "job_id": "job-123",
            "status": "completed",
            "request": {"file_content": "secret"},
            "result": {"totalScore": 88},
        }

        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=store), create=True),
            patch.object(main, "get_analysis_job", new=AsyncMock(return_value=stored_job), create=True),
        ):
            response = await main.get_analysis_job_status("job-123")

        self.assertEqual(response, {"job_id": "job-123", "status": "completed", "result": {"totalScore": 88}})

    async def test_get_analysis_job_status_returns_404_for_missing_job(self):
        with (
            patch.object(main, "_get_analysis_job_store", new=AsyncMock(return_value=object()), create=True),
            patch.object(main, "get_analysis_job", new=AsyncMock(side_effect=AnalysisJobNotFound("missing")), create=True),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await main.get_analysis_job_status("missing")

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
