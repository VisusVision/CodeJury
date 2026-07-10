import json
import unittest

from backend.ops.worker_readiness import (
    get_worker_readiness,
    heartbeat_key,
    publish_worker_heartbeat,
)


class FakeHeartbeatRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.expirations[key] = ex

    async def get(self, key):
        return self.values.get(key)

    async def scan_iter(self, match):
        prefix = match.removesuffix("*")
        for key in sorted(self.values):
            if key.startswith(prefix):
                yield key


class WorkerReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_heartbeat_is_not_ready(self):
        snapshot = await get_worker_readiness(FakeHeartbeatRedis())
        self.assertFalse(snapshot["analysis_ready"])
        self.assertEqual(snapshot["sandbox"]["mode"], "unavailable")

    async def test_ready_and_degraded_workers_are_aggregated(self):
        redis = FakeHeartbeatRedis()
        await publish_worker_heartbeat(redis, {
            "worker_id": "a", "status": "ready", "pool_ready": True,
            "container_count": 3, "available_count": 2, "target_size": 3,
            "last_error_code": None, "updated_at": "now", "analysis_engine": "2.1",
        })
        await publish_worker_heartbeat(redis, {
            "worker_id": "b", "status": "degraded", "pool_ready": True,
            "container_count": 1, "available_count": 0, "target_size": 3,
            "last_error_code": "partial_capacity", "updated_at": "now", "analysis_engine": "2.1",
        })
        snapshot = await get_worker_readiness(redis)
        self.assertTrue(snapshot["analysis_ready"])
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["worker_count"], 2)
        self.assertEqual(snapshot["ready_worker_count"], 2)
        self.assertEqual(snapshot["sandbox"]["container_count"], 4)
        self.assertEqual(redis.expirations[heartbeat_key("a")], 15)

    async def test_unavailable_worker_does_not_make_analysis_ready(self):
        redis = FakeHeartbeatRedis()
        await publish_worker_heartbeat(redis, {
            "worker_id": "a", "status": "unavailable", "pool_ready": False,
            "container_count": 0, "available_count": 0, "target_size": 3,
            "last_error_code": "docker_unavailable", "updated_at": "now", "analysis_engine": "2.1",
        })
        snapshot = await get_worker_readiness(redis)
        self.assertFalse(snapshot["analysis_ready"])
        self.assertEqual(snapshot["ready_worker_count"], 0)
