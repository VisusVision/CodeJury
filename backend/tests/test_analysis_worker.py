import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.base import LLMInferenceError
from backend.queue.analysis_jobs import AnalysisJobStore, create_analysis_job, get_analysis_job
from backend.tests.test_analysis_jobs import FakeRedis
from backend.workers import analysis_worker
from backend.workers.analysis_worker import process_analysis_job


class AnalysisWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = FakeRedis()
        self.store = AnalysisJobStore(
            self.redis,
            stream_name="stream:analysis_jobs",
            id_factory=lambda: "job-123",
            clock=lambda: "2026-05-05T12:00:00Z",
        )

    async def test_process_analysis_job_marks_completed_with_pipeline_result(self):
        await create_analysis_job(
            self.store,
            {
                "file_name": "main.py",
                "file_content": "print('ok')",
                "assignment_brief": "Write a Python program.",
                "faculty_rubric_criteria": [{"name": "Correctness", "max_score": 100}],
                "report_language": "tr",
            },
        )
        calls = []

        async def pipeline(**kwargs):
            calls.append(kwargs)
            return {"totalScore": 91}

        await process_analysis_job(self.store, "job-123", pipeline=pipeline)

        job = await get_analysis_job(self.store, "job-123")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"], {"totalScore": 91})
        self.assertEqual(job["report_status"], "ready")
        self.assertEqual(calls[0]["file_name"], "main.py")
        self.assertEqual(calls[0]["assignment_brief"], "Write a Python program.")

    async def test_process_analysis_job_publishes_partial_result_before_completion(self):
        await create_analysis_job(
            self.store,
            {
                "file_name": "main.py",
                "file_content": "print('ok')",
                "report_language": "tr",
            },
        )

        async def pipeline(**kwargs):
            progress_callback = kwargs["progress_callback"]
            await progress_callback({"totalScore": 61, "reportStatus": "preparing"})
            preview_job = await get_analysis_job(self.store, "job-123")
            self.assertEqual(preview_job["status"], "running")
            self.assertEqual(preview_job["report_status"], "preparing")
            self.assertEqual(preview_job["result"]["totalScore"], 61)
            return {"totalScore": 84, "reportStatus": "ready"}

        job = await process_analysis_job(self.store, "job-123", pipeline=pipeline)

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["report_status"], "ready")
        self.assertEqual(job["result"]["totalScore"], 84)

    async def test_process_analysis_job_marks_failed_when_pipeline_raises(self):
        await create_analysis_job(self.store, {"file_name": "main.py", "file_content": "bad"})

        async def pipeline(**kwargs):
            raise RuntimeError("boom")

        with patch.object(analysis_worker.logger, "exception"):
            await process_analysis_job(self.store, "job-123", pipeline=pipeline)

        job = await get_analysis_job(self.store, "job-123")
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "Analiz tamamlanamadi. Lutfen tekrar deneyin.")

    async def test_process_analysis_job_returns_actionable_message_when_llm_unavailable(self):
        await create_analysis_job(self.store, {"file_name": "main.py", "file_content": "print('ok')"})

        async def pipeline(**kwargs):
            raise LLMInferenceError("[code_quality] Ollama is disabled (ollama_enabled=false); LLM is required.")

        with patch.object(analysis_worker.logger, "exception"):
            await process_analysis_job(self.store, "job-123", pipeline=pipeline)

        job = await get_analysis_job(self.store, "job-123")
        self.assertEqual(job["status"], "failed")
        self.assertIn("Ollama", job["error"])
        self.assertIn("AI", job["error"])

    async def test_default_pipeline_reloads_modules_when_enabled(self):
        with patch.dict("os.environ", {"ANALYSIS_WORKER_RELOAD": "1"}, clear=False):
            with patch("backend.workers.analysis_worker._reload_pipeline_modules") as reload_mock:
                with patch(
                    "frontend.backend.main.run_analysis_pipeline",
                    new=AsyncMock(return_value={"totalScore": 88}),
                ) as pipeline_mock:
                    result = await analysis_worker._default_pipeline(file_name="main.py")

        reload_mock.assert_called_once()
        pipeline_mock.assert_awaited_once()
        self.assertEqual(result["totalScore"], 88)

    async def test_default_pipeline_skips_reload_when_disabled(self):
        with patch.dict("os.environ", {"ANALYSIS_WORKER_RELOAD": "0"}, clear=False):
            with patch("backend.workers.analysis_worker._reload_pipeline_modules") as reload_mock:
                with patch(
                    "frontend.backend.main.run_analysis_pipeline",
                    new=AsyncMock(return_value={"totalScore": 77}),
                ):
                    await analysis_worker._default_pipeline(file_name="main.py")

        reload_mock.assert_not_called()

    async def test_process_analysis_job_marks_failed_when_pipeline_times_out(self):
        await create_analysis_job(self.store, {"file_name": "main.py", "file_content": "slow"})

        async def pipeline(**kwargs):
            await asyncio.sleep(0.2)
            return {"totalScore": 50}

        with patch.object(analysis_worker.settings, "analysis_pipeline_timeout_seconds", 0):
            with patch.object(analysis_worker.logger, "exception"):
                await process_analysis_job(self.store, "job-123", pipeline=pipeline)

        job = await get_analysis_job(self.store, "job-123")
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], analysis_worker.PIPELINE_TIMEOUT_ERROR)

    async def test_worker_sandbox_pool_initializes_when_enabled(self):
        with patch.dict("os.environ", {"ANALYSIS_WORKER_SANDBOX_POOL": "1"}, clear=False):
            with patch("backend.sandbox.pool_manager.initialize_pool") as initialize_mock:
                started = analysis_worker.initialize_worker_sandbox_pool()

        self.assertTrue(started)
        initialize_mock.assert_called_once()

    async def test_worker_sandbox_pool_skips_when_disabled(self):
        with patch.dict("os.environ", {"ANALYSIS_WORKER_SANDBOX_POOL": "0"}, clear=False):
            with patch("backend.sandbox.pool_manager.initialize_pool") as initialize_mock:
                started = analysis_worker.initialize_worker_sandbox_pool()

        self.assertFalse(started)
        initialize_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
