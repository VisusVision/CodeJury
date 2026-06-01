import unittest
from unittest.mock import patch

from backend.queue.analysis_jobs import AnalysisJobStore, create_analysis_job, get_analysis_job
from backend.agents.base import LLMInferenceError
from backend.workers import analysis_worker
from backend.tests.test_analysis_jobs import FakeRedis
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
        self.assertEqual(calls[0]["file_name"], "main.py")
        self.assertEqual(calls[0]["assignment_brief"], "Write a Python program.")

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


if __name__ == "__main__":
    unittest.main()
