"""TDD tests for qa_soak_consistency --pool CLI wiring."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]


def _load_soak_module():
    path = ROOT / "scripts" / "qa_soak_consistency.py"
    spec = importlib.util.spec_from_file_location("qa_soak_consistency", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load soak script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["qa_soak_consistency"] = module
    spec.loader.exec_module(module)
    return module


class QaSoakPoolCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_passes_pool_sandbox_mode_when_pool_flag_set(self):
        soak = _load_soak_module()
        summary = soak.SoakSummary(
            started_at="t0",
            ended_at="t1",
            duration_min=0.0,
            total_runs=0,
            passed_runs=0,
            failed_runs=0,
            error_runs=0,
            sandbox_mode="pool",
        )
        shutdown_mock = MagicMock()
        run_mock = AsyncMock(return_value=summary)

        argv = ["qa_soak_consistency.py", "--pool", "--minutes", "0", "--pool-size", "2", "--pool-base-port", "9201"]
        with (
            patch.object(sys, "argv", argv),
            patch.object(soak, "_init_sandbox_pool", return_value="pool") as init_mock,
            patch.object(soak, "run_soak", run_mock),
            patch("backend.sandbox.pool_manager.shutdown_pool", shutdown_mock),
        ):
            code = await soak.main()

        self.assertEqual(code, 0)
        init_mock.assert_called_once_with(pool_size=2, base_port=9201, timeout_s=30.0)
        run_mock.assert_awaited_once_with(0, sandbox_mode="pool")
        shutdown_mock.assert_called_once()

    async def test_main_keeps_simulation_mode_without_pool_flag(self):
        soak = _load_soak_module()
        summary = soak.SoakSummary(
            started_at="t0",
            ended_at="t1",
            duration_min=0.0,
            total_runs=0,
            passed_runs=0,
            failed_runs=0,
            error_runs=0,
            sandbox_mode="simulation",
        )
        run_mock = AsyncMock(return_value=summary)

        with (
            patch.object(sys, "argv", ["qa_soak_consistency.py", "--minutes", "0"]),
            patch.object(soak, "_init_sandbox_pool") as init_mock,
            patch.object(soak, "run_soak", run_mock),
            patch("backend.sandbox.pool_manager.shutdown_pool") as shutdown_mock,
        ):
            code = await soak.main()

        self.assertEqual(code, 0)
        init_mock.assert_not_called()
        run_mock.assert_awaited_once_with(0, sandbox_mode="simulation")
        shutdown_mock.assert_not_called()

    async def test_main_runs_simulation_when_pool_init_unavailable(self):
        soak = _load_soak_module()
        summary = soak.SoakSummary(
            started_at="t0",
            ended_at="t1",
            duration_min=0.0,
            total_runs=0,
            passed_runs=0,
            failed_runs=0,
            error_runs=0,
            sandbox_mode="simulation",
        )
        shutdown_mock = MagicMock()
        run_mock = AsyncMock(return_value=summary)

        with (
            patch.object(sys, "argv", ["qa_soak_consistency.py", "--pool", "--minutes", "0"]),
            patch.object(soak, "_init_sandbox_pool", return_value="simulation"),
            patch.object(soak, "run_soak", run_mock),
            patch("backend.sandbox.pool_manager.shutdown_pool", shutdown_mock),
        ):
            code = await soak.main()

        self.assertEqual(code, 0)
        run_mock.assert_awaited_once_with(0, sandbox_mode="simulation")
        shutdown_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
