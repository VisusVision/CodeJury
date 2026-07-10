import json
import unittest

from backend.queue.analysis_jobs import (
    AnalysisJobNotFound,
    AnalysisJobOwner,
    AnalysisJobStore,
    create_analysis_job,
    fail_analysis_job,
    get_analysis_job,
    mark_analysis_job_completed,
    mark_analysis_job_running,
    update_analysis_job_result,
)
from backend.reporting.student_projection import project_student_result


DEFAULT_OWNER = AnalysisJobOwner(
    owner_user_id="student-a",
    owner_role="student",
    student_id="student-a",
    assignment_id=None,
    assignment_owner_teacher_id=None,
)


class FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.expirations: dict[str, int] = {}
        self.values: dict[str, str] = {}

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

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.expirations[key] = ex

    async def get(self, key):
        return self.values.get(key)

    async def scan_iter(self, match):
        prefix = match.removesuffix("*") if match.endswith("*") else match
        for key in sorted(self.values):
            if key.startswith(prefix):
                yield key


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

        job = await create_analysis_job(self.store, request, owner=DEFAULT_OWNER)

        self.assertEqual(job["job_id"], "job-123")
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.redis.streams["stream:analysis_jobs"], [("1-0", {"job_id": "job-123"})])
        stored = self.redis.hashes["analysis_job:job-123"]
        self.assertEqual(json.loads(stored["request"]), request)
        self.assertEqual(stored["status"], "queued")
        self.assertEqual(self.redis.expirations["analysis_job:job-123"], 60)

    async def test_create_analysis_job_stores_owner_metadata_outside_request(self):
        owner = AnalysisJobOwner(
            owner_user_id="student-a",
            owner_role="student",
            student_id="student-a",
            assignment_id="assignment-1",
            assignment_owner_teacher_id="teacher-1",
        )
        request = {"file_name": "main.py", "assignment_id": "client-assignment"}

        await create_analysis_job(self.store, request, owner=owner)

        stored = self.redis.hashes["analysis_job:job-123"]
        self.assertEqual(stored["owner_user_id"], "student-a")
        self.assertEqual(stored["owner_role"], "student")
        self.assertEqual(stored["student_id"], "student-a")
        self.assertEqual(stored["assignment_id"], "assignment-1")
        self.assertEqual(stored["assignment_owner_teacher_id"], "teacher-1")
        self.assertEqual(json.loads(stored["request"])["assignment_id"], "client-assignment")

    async def test_owner_metadata_absent_on_legacy_job_decodes_to_none(self):
        await self.redis.hset(
            "analysis_job:legacy-job",
            {
                "job_id": "legacy-job",
                "status": "queued",
                "request": json.dumps({"file_name": "main.py"}),
                "created_at": "2026-05-05T12:00:00Z",
                "updated_at": "2026-05-05T12:00:00Z",
                "attempts": 0,
            },
        )

        job = await get_analysis_job(self.store, "legacy-job")

        self.assertIsNone(job.get("owner_user_id"))
        self.assertIsNone(job.get("owner_role"))
        self.assertIsNone(job.get("student_id"))
        self.assertIsNone(job.get("assignment_id"))
        self.assertIsNone(job.get("assignment_owner_teacher_id"))

    async def test_get_analysis_job_returns_decoded_payloads(self):
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=DEFAULT_OWNER)

        job = await get_analysis_job(self.store, "job-123")

        self.assertEqual(job["job_id"], "job-123")
        self.assertEqual(job["request"], {"file_name": "main.py"})
        self.assertNotIn("private_result", job)
        self.assertNotIn("student_result", job)

    async def test_get_analysis_job_raises_for_missing_job(self):
        with self.assertRaises(AnalysisJobNotFound):
            await get_analysis_job(self.store, "missing")

    async def test_running_and_completed_updates_preserve_result(self):
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=DEFAULT_OWNER)

        await mark_analysis_job_running(self.store, "job-123")
        await mark_analysis_job_completed(self.store, "job-123", {"totalScore": 95})
        job = await get_analysis_job(self.store, "job-123")

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["private_result"], {"totalScore": 95})
        self.assertEqual(job["student_result"], {"totalScore": 95})
        self.assertEqual(job["report_status"], "ready")
        self.assertEqual(job["attempts"], 1)
        self.assertIn("started_at", job)
        self.assertIn("finished_at", job)

    async def test_running_job_can_expose_partial_result_before_completion(self):
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=DEFAULT_OWNER)

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
        self.assertEqual(job["private_result"], {"totalScore": 72, "reportStatus": "preparing"})
        self.assertEqual(job["student_result"], {"totalScore": 72, "reportStatus": "preparing"})

    async def test_update_result_writes_both_private_and_student_projections(self):
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=DEFAULT_OWNER)
        private_result = {
            "totalScore": 80,
            "agents": [
                {
                    "id": "testing",
                    "name": "Testing",
                    "testResults": [
                        {
                            "name": "hidden1",
                            "visibility": "hidden",
                            "input": "secret input",
                            "expected": "secret expected",
                            "actual": "wrong",
                            "passed": False,
                        }
                    ],
                }
            ],
        }

        await update_analysis_job_result(self.store, "job-123", private_result)
        job = await get_analysis_job(self.store, "job-123")

        self.assertEqual(job["private_result"], private_result)
        self.assertEqual(job["student_result"], project_student_result(private_result))
        hidden_case = job["student_result"]["agents"][0]["testResults"][0]
        self.assertNotIn("input", hidden_case)
        self.assertNotIn("expected", hidden_case)
        self.assertNotIn("actual", hidden_case)

    async def test_failed_update_stores_safe_error(self):
        await create_analysis_job(self.store, {"file_name": "main.py"}, owner=DEFAULT_OWNER)

        await fail_analysis_job(self.store, "job-123", "Analiz tamamlanamadi.")
        job = await get_analysis_job(self.store, "job-123")

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "Analiz tamamlanamadi.")
        self.assertEqual(job["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
