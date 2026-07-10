"""Runtime diagnostics snapshots for staging health checks."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from backend.ops.runtime_diagnostics import (
    build_analysis_runtime_meta,
    get_llm_config_snapshot,
    get_local_sandbox_pool_snapshot,
)


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_llm_config_exposes_env_models(self):
        snap = get_llm_config_snapshot()
        self.assertIn("general_model", snap)
        self.assertIn("coder_model", snap)
        self.assertIn("enabled", snap)

    def test_sandbox_snapshot_defaults_to_unavailable_without_pool(self):
        snap = get_local_sandbox_pool_snapshot()
        self.assertIn("mode", snap)
        self.assertIn("pool_ready", snap)
        self.assertEqual(snap["mode"], "unavailable")

    def test_analysis_runtime_meta_includes_pipeline_and_backend(self):
        meta = build_analysis_runtime_meta(pipeline_ms=1234, sandbox_backend="pool")
        self.assertEqual(meta["pipeline_ms"], 1234)
        self.assertEqual(meta["sandbox"]["execution_backend"], "pool")
        self.assertIn("llm", meta)

    def test_try_initialize_sandbox_pool_returns_unavailable_when_pool_not_ready(self):
        from backend.ops.runtime_diagnostics import try_initialize_sandbox_pool

        # try_initialize_sandbox_pool intentionally writes SANDBOX_POOL_* env vars so
        # pool_manager.initialize_pool() picks them up; isolate that side effect here so
        # it cannot leak into other tests/scripts sharing this process's environment.
        with patch.dict(os.environ, clear=False):
            with patch("backend.sandbox.pool_manager.initialize_pool") as init_mock:
                with patch("backend.sandbox.pool_manager.get_pool", return_value=None):
                    mode = try_initialize_sandbox_pool(pool_size=1, base_port=9101, timeout_s=5.0)
        self.assertEqual(mode, "unavailable")
        init_mock.assert_called_once()

    def test_try_initialize_sandbox_pool_returns_pool_when_ready(self):
        from backend.ops.runtime_diagnostics import try_initialize_sandbox_pool

        ready_pool = MagicMock()
        ready_pool.snapshot.return_value = {
            "state": "ready",
            "pool_ready": True,
            "container_count": 2,
            "available_count": 2,
            "target_size": 2,
            "last_error_code": None,
        }
        with patch.dict(os.environ, clear=False):
            with patch("backend.sandbox.pool_manager.initialize_pool") as init_mock:
                with patch("backend.sandbox.pool_manager.get_pool", return_value=ready_pool):
                    mode = try_initialize_sandbox_pool(pool_size=2, base_port=9102, timeout_s=5.0)
        self.assertEqual(mode, "pool")
        init_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
