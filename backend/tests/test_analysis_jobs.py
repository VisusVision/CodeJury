import json
import unittest

from backend.queue.analysis_jobs import (
    AnalysisJobNotFound,
    AnalysisJobStore,
    create_analysis_job,
    fail_analysis_job,
    get_analysis_job,
    mark_analysis_job_completed,
    mark_analysis_job_running,
    update_analysis_job_result,
)


class FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.expirations: dict[str, int] = {}

    async def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def expire(self, key, seconds):
        self.expirations[key] = seconds

    async def xadd(self, stream, fields):
        entries = self.streams.setdefault(stream, [])
        message_id = f"{len(entries) + 1}-0"
        entries.append((message_id, dict(fields)))
        return message_id


class AnalysisJobStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = FakeRedis()
        self.store = AnalysisJobStore(
            self.redis,
            stream_name="stream:analysis_jobs",
            job_ttl_seconds=60,
            id_factory=lambda: "job-123",
            clock=lambda: "2026-05-05T12:00:00Z",
        )

    async def test_create_analysis_job_stores_payload_and_publishes_stream_message(self):
        request = {"file_name": "main.py", "file_content": "print('ok')"}

        job = await create_analysis_job(self.store, request)

        self.assertEqual(job["job_id"], "job-123")
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.redis.streams["stream:analysis_jobs"], [("1-0", {"job_id": "job-123"})])
        stored = self.redis.hashes["analysis_job:job-123"]
        self.assertEqual(json.loads(stored["request"]), request)
        self.assertEqual(stored["status"], "queued")
        self.assertEqual(self.redis.expirations["analysis_job:job-123"], 60)

    async def test_get_analysis_job_returns_decoded_payloads(self):
        await create_analysis_job(self.store, {"file_name": "main.py"})

        job = await get_analysis_job(self.store, "job-123")

        self.assertEqual(job["job_id"], "job-123")
        self.assertEqual(job["request"], {"file_name": "main.py"})
        self.assertNotIn("result", job)

    async def test_get_analysis_job_raises_for_missing_job(self):
        with self.assertRaises(AnalysisJobNotFound):
            await get_analysis_job(self.store, "missing")

    async def test_running_and_completed_updates_preserve_result(self):
        await create_analysis_job(self.store, {"file_name": "main.py"})

        await mark_analysis_job_running(self.store, "job-123")
        await mark_analysis_job_completed(self.store, "job-123", {"totalScore": 95})
        job = await get_analysis_job(self.store, "job-123")

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"], {"totalScore": 95})
        self.assertEqual(job["report_status"], "ready")
        self.assertEqual(job["attempts"], 1)
        self.assertIn("started_at", job)
        self.assertIn("finished_at", job)

    async def test_running_job_can_expose_partial_result_before_completion(self):
        await create_analysis_job(self.store, {"file_name": "main.py"})

        await mark_analysis_job_running(self.store, "job-123")
        await update_analysis_job_result(
            self.store,
            "job-123",
            {"totalScore": 72, "reportStatus": "preparing"},
            report_status="preparing",
        )
        job = await get_analysis_job(self.store, "job-123")

        self.assertEqual(job["status"], "running")
        self.assertEqual(job["report_status"], "preparing")
        self.assertEqual(job["result"], {"totalScore": 72, "reportStatus": "preparing"})

    async def test_failed_update_stores_safe_error(self):
        await create_analysis_job(self.store, {"file_name": "main.py"})

        await fail_analysis_job(self.store, "job-123", "Analiz tamamlanamadi.")
        job = await get_analysis_job(self.store, "job-123")

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "Analiz tamamlanamadi.")
        self.assertEqual(job["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
