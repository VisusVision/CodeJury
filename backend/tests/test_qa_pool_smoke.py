"""TDD tests for qa_pool_smoke CLI."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]


def _load_pool_smoke_module():
    path = ROOT / "scripts" / "qa_pool_smoke.py"
    spec = importlib.util.spec_from_file_location("qa_pool_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load pool smoke script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["qa_pool_smoke"] = module
    spec.loader.exec_module(module)
    return module


class QaPoolSmokeTests(unittest.TestCase):
    def test_run_pool_smoke_passes_when_pool_execute_succeeds(self):
        smoke = _load_pool_smoke_module()
        shutdown_mock = MagicMock()

        with (
            patch("backend.ops.runtime_diagnostics.try_initialize_sandbox_pool", return_value="pool"),
            patch(
                "backend.sandbox.executor.run_in_sandbox",
                return_value={"stdout": "pool-smoke-ok\n", "execution_backend": "pool"},
            ),
            patch("backend.sandbox.pool_manager.shutdown_pool", shutdown_mock),
        ):
            code = smoke.run_pool_smoke(pool_size=2, base_port=9200, timeout_s=30.0)

        self.assertEqual(code, 0)
        shutdown_mock.assert_called_once()

    def test_run_pool_smoke_fails_when_pool_unavailable(self):
        smoke = _load_pool_smoke_module()
        shutdown_mock = MagicMock()

        with (
            patch("backend.ops.runtime_diagnostics.try_initialize_sandbox_pool", return_value="unavailable"),
            patch("backend.sandbox.executor.run_in_sandbox") as run_mock,
            patch("backend.sandbox.pool_manager.shutdown_pool", shutdown_mock),
        ):
            code = smoke.run_pool_smoke()

        self.assertEqual(code, 1)
        run_mock.assert_not_called()
        shutdown_mock.assert_called_once()

    def test_run_pool_smoke_fails_when_execution_backend_not_pool(self):
        smoke = _load_pool_smoke_module()

        with (
            patch("backend.ops.runtime_diagnostics.try_initialize_sandbox_pool", return_value="pool"),
            patch(
                "backend.sandbox.executor.run_in_sandbox",
                return_value={"stdout": "pool-smoke-ok\n", "execution_backend": "simulation"},
            ),
            patch("backend.sandbox.pool_manager.shutdown_pool"),
        ):
            code = smoke.run_pool_smoke()

        self.assertEqual(code, 1)

    def test_main_reads_pool_size_and_port_from_env_vars(self):
        smoke = _load_pool_smoke_module()
        run_mock = MagicMock(return_value=0)

        with (
            patch.dict("os.environ", {
                "SANDBOX_POOL_SIZE": "5",
                "SANDBOX_POOL_BASE_PORT": "8381",
                "SANDBOX_POOL_TIMEOUT": "45.0",
            }, clear=False),
            patch.object(smoke, "run_pool_smoke", run_mock),
        ):
            code = smoke.main()

        self.assertEqual(code, 0)
        run_mock.assert_called_once_with(pool_size=5, base_port=8381, timeout_s=45.0)


if __name__ == "__main__":
    unittest.main()
