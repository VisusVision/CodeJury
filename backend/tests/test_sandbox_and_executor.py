"""
Sandbox & Executor Testleri

Docker/gercek container gerekmez; tumu mock/fake ile calisir.

Onemli patch hedefleri (gercek import yapisina gore):
- `run_in_sandbox` icinde `from backend.sandbox.pool_manager import get_pool` yapilir,
  yani patch hedefi `backend.sandbox.pool_manager.get_pool`'dur (executor modulunde
  modul-seviyesi bir `get_pool` adi YOKTUR).
- HTTP cagrisi fonksiyon icinde `import requests` ile yapilir; bu yuzden `requests.post`
  dogrudan patch edilir.
- Pool saglik kontrolu `backend.sandbox.pool._requests` global'ini kullanir.
"""

import unittest
from unittest.mock import MagicMock, call, patch
import requests

from backend.sandbox.errors import SandboxUnavailableError
from backend.sandbox.executor import _FALLBACK, _LANG_MAP, _simulate_sandbox, run_in_sandbox
from backend.sandbox.pool import ContainerSlot, PoolState, SandboxPool


_GET_POOL = "backend.sandbox.pool_manager.get_pool"
_REQUESTS_POST = "requests.post"
_WAIT_FOR_POOL_READY = "backend.sandbox.pool_manager.wait_for_pool_ready"


# ═══════════════════════════════════════════════════════════════════════════════
# _simulate_sandbox
# ═══════════════════════════════════════════════════════════════════════════════

class SimulateSandboxTests(unittest.TestCase):
    def test_valid_python_runs(self):
        result = _simulate_sandbox("print('hello world')\n")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello world", result["stdout"])
        self.assertTrue(result["compilation_success"])
        self.assertFalse(result["timed_out"])

    def test_syntax_error_reported(self):
        result = _simulate_sandbox("def broken(\n")
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("SyntaxError", result["stderr"])
        self.assertFalse(result["compilation_success"])

    def test_runtime_error_captured(self):
        result = _simulate_sandbox("raise ValueError('boom')\n")
        self.assertNotEqual(result["exit_code"], 0)
        self.assertIn("ValueError", result["stderr"])
        self.assertTrue(result["compilation_success"])  # sozdizimi gecerli

    def test_infinite_loop_times_out(self):
        result = _simulate_sandbox("while True:\n    pass\n")
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Timeout", result["stderr"])

    def test_stdout_lines_captured(self):
        result = _simulate_sandbox("for i in range(3):\n    print(i)\n")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"].strip().splitlines(), ["0", "1", "2"])

    def test_empty_code_is_valid(self):
        result = _simulate_sandbox("")
        self.assertTrue(result["compilation_success"])
        self.assertEqual(result["exit_code"], 0)

    def test_simulation_marks_execution_backend(self):
        result = _simulate_sandbox("print('ok')\n")
        self.assertEqual(result.get("execution_backend"), "simulation")


# ═══════════════════════════════════════════════════════════════════════════════
# run_in_sandbox
# ═══════════════════════════════════════════════════════════════════════════════

    def test_formal_tests_run_with_stdin_when_pool_unavailable(self):
        result = _simulate_sandbox(
            "n=int(input())\nprint(n*n)\n",
            test_cases=[
                {"name": "square_5", "stdin": "5\n", "expected_stdout": "25\n"},
                {"name": "square_0", "stdin": "0\n", "expected_stdout": "0\n"},
            ],
        )

        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(len(result["test_results"]), 2)
        self.assertTrue(all(tc["passed"] for tc in result["test_results"]))
        self.assertEqual(result["summary"]["tests"]["passed"], 2)

    def test_formal_test_runtime_error_is_recorded_in_simulation(self):
        result = _simulate_sandbox(
            "a=int(input())\nb=int(input())\nprint(a//b)\n",
            test_cases=[
                {"name": "zero_division", "stdin": "10\n0\n", "expected_stdout": "HATA\n"},
            ],
        )

        self.assertEqual(result["exit_code"], 1)
        self.assertFalse(result["test_results"][0]["passed"])
        self.assertIn("ZeroDivisionError", result["test_results"][0]["error"])


class RunInSandboxTests(unittest.TestCase):
    def _ready_pool_with_slot(self):
        pool = MagicMock()
        pool.is_ready = True
        slot = MagicMock()
        slot.url = "http://localhost:8181"
        pool.acquire.return_value = slot
        return pool, slot

    @staticmethod
    def _ok_response(report):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"report": report}
        return resp

    def test_lang_map_normalizes(self):
        self.assertEqual(_LANG_MAP.get("python"), "python")
        self.assertEqual(_LANG_MAP.get("py"), "python")
        self.assertEqual(_LANG_MAP.get("cpp"), "cpp")
        self.assertEqual(_LANG_MAP.get("c++"), "cpp")
        self.assertEqual(_LANG_MAP.get("java"), "java")

    def test_fallback_dict_has_all_fields(self):
        required = {
            "stdout", "stderr", "exit_code", "execution_time_ms", "peak_memory_mb",
            "compilation_success", "timed_out", "memory_exceeded", "test_results",
            "static_analysis", "code_metrics", "summary", "execution_backend",
        }
        self.assertTrue(required.issubset(set(_FALLBACK.keys())))

    def test_pool_none_raises_without_running_host_subprocess(self):
        with (
            patch(_GET_POOL, return_value=None),
            patch(_WAIT_FOR_POOL_READY, return_value=None),
            patch("subprocess.run") as host_run,
        ):
            with self.assertRaises(SandboxUnavailableError) as ctx:
                run_in_sandbox("print('hello')\n", "python")
        self.assertEqual(ctx.exception.code, "pool_not_ready")
        host_run.assert_not_called()

    def test_pool_not_ready_raises_without_calling_simulation(self):
        pool = MagicMock()
        pool.is_ready = False
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=None),
            patch("backend.sandbox.executor._simulate_sandbox") as simulation,
        ):
            with self.assertRaises(SandboxUnavailableError) as ctx:
                run_in_sandbox("print('hi')\n", "python")
        self.assertEqual(ctx.exception.code, "pool_not_ready")
        simulation.assert_not_called()

    def test_pool_available_sends_http_request(self):
        pool, slot = self._ready_pool_with_slot()
        resp = self._ok_response({
            "execution": {
                "stdout": "5", "stderr": "", "exit_code": 0,
                "wall_time_ms": 15, "peak_memory_mb": 10.0, "compile_success": True,
            },
            "test_results": [], "static_analysis": {}, "code_metrics": {}, "summary": {},
        })
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
            patch(_REQUESTS_POST, return_value=resp) as mock_post,
        ):
            result = run_in_sandbox("print(2+3)\n", "python")

        mock_post.assert_called_once()
        url_arg = mock_post.call_args.args[0] if mock_post.call_args.args else ""
        self.assertIn("/api/execute", url_arg)
        self.assertEqual(result["stdout"], "5")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["compilation_success"])
        self.assertEqual(result.get("execution_backend"), "pool")
        pool.release.assert_called_once_with(slot, ok=True)

    def test_invalid_response_raises_after_one_retry_and_releases_slot(self):
        pool, slot = self._ready_pool_with_slot()
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
            patch(_REQUESTS_POST, side_effect=Exception("Connection refused")),
        ):
            with self.assertRaises(SandboxUnavailableError) as ctx:
                run_in_sandbox("print(1)\n", "python")
        self.assertEqual(ctx.exception.code, "invalid_response")
        self.assertEqual(pool.acquire.call_count, 2)
        pool.release.assert_has_calls([call(slot, ok=False), call(slot, ok=False)])

    def test_connection_error_retries_once_on_new_slot_then_raises(self):
        pool, first_slot = self._ready_pool_with_slot()
        second_slot = MagicMock(url="http://127.0.0.1:8182")
        pool.acquire.side_effect = [first_slot, second_slot]
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
            patch(_REQUESTS_POST, side_effect=requests.exceptions.ConnectionError("refused")),
        ):
            with self.assertRaises(SandboxUnavailableError) as ctx:
                run_in_sandbox("print(1)\n", "python")
        self.assertEqual(ctx.exception.code, "container_unreachable")
        self.assertEqual(pool.acquire.call_count, 2)
        self.assertEqual(pool.release.call_args_list, [
            call(first_slot, ok=False),
            call(second_slot, ok=False),
        ])

    def test_invalid_container_report_raises_invalid_response(self):
        pool, slot = self._ready_pool_with_slot()
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"report": {"execution": "not-an-object"}}
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
            patch(_REQUESTS_POST, return_value=response),
        ):
            with self.assertRaises(SandboxUnavailableError) as ctx:
                run_in_sandbox("print(1)\n", "python")
        self.assertEqual(ctx.exception.code, "invalid_response")

    def test_acquire_timeout_raises_pool_exhausted(self):
        pool = MagicMock()
        pool.is_ready = True
        pool.acquire.side_effect = TimeoutError("All busy")
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
        ):
            with self.assertRaises(SandboxUnavailableError) as ctx:
                run_in_sandbox("print(1)\n", "python")
        self.assertEqual(ctx.exception.code, "pool_exhausted")
        pool.release.assert_not_called()

    def test_test_cases_included_in_payload(self):
        pool, _ = self._ready_pool_with_slot()
        resp = self._ok_response({
            "execution": {"exit_code": 0, "compile_success": True},
            "test_results": [], "static_analysis": {},
            "code_metrics": {}, "summary": {},
        })
        test_cases = [{"name": "tc1", "stdin": "5", "expected_stdout": "25"}]
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
            patch(_REQUESTS_POST, return_value=resp) as mock_post,
        ):
            run_in_sandbox("print(int(input())**2)\n", "python", test_cases=test_cases)

        payload = mock_post.call_args.kwargs["json"]
        self.assertIn(test_cases[0], payload["test_cases"])
        self.assertEqual(payload["language"], "python")

    def test_formal_test_passes_override_empty_stdin_smoke_error(self):
        pool, _ = self._ready_pool_with_slot()
        resp = self._ok_response({
            "execution": {
                "stdout": "",
                "stderr": "Traceback...\nEOFError: EOF when reading a line",
                "exit_code": 1,
                "compile_success": True,
            },
            "test_results": [
                {
                    "name": "tc1",
                    "stdin": "5\n",
                    "passed": True,
                    "actual_stdout": "25",
                    "expected_stdout": "25\n",
                    "actual_exit_code": 0,
                }
            ],
            "static_analysis": {},
            "code_metrics": {},
            "summary": {},
        })
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
            patch(_REQUESTS_POST, return_value=resp),
        ):
            result = run_in_sandbox(
                "n=int(input())\nprint(n*n)\n",
                "python",
                test_cases=[{"name": "tc1", "stdin": "5\n", "expected_stdout": "25\n"}],
            )

        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stderr"], "")

    def test_formal_test_failure_uses_case_stderr(self):
        pool, _ = self._ready_pool_with_slot()
        resp = self._ok_response({
            "execution": {
                "stdout": "",
                "stderr": "Traceback...\nEOFError: EOF when reading a line",
                "exit_code": 1,
                "compile_success": True,
            },
            "test_results": [
                {
                    "name": "zero_division",
                    "stdin": "10\n0\n",
                    "passed": False,
                    "actual_stdout": "",
                    "actual_stderr": "Traceback...\nZeroDivisionError: division by zero",
                    "expected_stdout": "HATA\n",
                    "actual_exit_code": 1,
                    "error": "Exit code: expected=0, actual=1; ZeroDivisionError: division by zero",
                }
            ],
            "static_analysis": {},
            "code_metrics": {},
            "summary": {},
        })
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
            patch(_REQUESTS_POST, return_value=resp),
        ):
            result = run_in_sandbox(
                "a=int(input())\nb=int(input())\nprint(a//b)\n",
                "python",
                test_cases=[{"name": "zero_division", "stdin": "10\n0\n", "expected_stdout": "HATA\n"}],
            )

        self.assertEqual(result["exit_code"], 1)
        self.assertIn("ZeroDivisionError", result["stderr"])

    def test_stdin_data_added_as_test_case(self):
        pool, _ = self._ready_pool_with_slot()
        resp = self._ok_response({
            "execution": {"exit_code": 0, "compile_success": True}, "test_results": [], "static_analysis": {},
            "code_metrics": {}, "summary": {},
        })
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_WAIT_FOR_POOL_READY, return_value=pool),
            patch(_REQUESTS_POST, return_value=resp) as mock_post,
        ):
            run_in_sandbox("print(input())\n", "python", stdin_data="merhaba")

        payload = mock_post.call_args.kwargs["json"]
        self.assertTrue(any(tc.get("stdin") == "merhaba" for tc in payload["test_cases"]))


# ═══════════════════════════════════════════════════════════════════════════════
# SandboxPool / ContainerSlot
# ═══════════════════════════════════════════════════════════════════════════════

class SandboxPoolTests(unittest.TestCase):
    def _make_pool(self, pool_size=3):
        return SandboxPool(image="test-image", pool_size=pool_size, base_port=19000)

    def _make_slot(self, port=19000):
        return ContainerSlot(container=MagicMock(), url=f"http://localhost:{port}", port=port)

    def test_container_slot_dataclass(self):
        slot = ContainerSlot(container="fake", url="http://localhost:8181", port=8181)
        self.assertEqual(slot.url, "http://localhost:8181")
        self.assertEqual(slot.port, 8181)

    def test_acquire_raises_when_not_initialized(self):
        with self.assertRaises(RuntimeError):
            self._make_pool().acquire()

    def test_acquire_returns_available_slot(self):
        pool = self._make_pool()
        slot = self._make_slot()
        pool._slots.append(slot)
        pool._available.put(slot)
        pool._initialized = True
        self.assertIs(pool.acquire(), slot)

    def test_acquire_times_out_when_busy(self):
        pool = self._make_pool()
        pool._slots.append(self._make_slot())
        pool._initialized = True
        pool.acquire_timeout = 0.1
        with self.assertRaises(TimeoutError):
            pool.acquire()

    def test_release_returns_healthy_slot_to_queue(self):
        pool = self._make_pool()
        slot = self._make_slot()
        pool._slots.append(slot)
        pool._initialized = True
        with patch.object(pool, "_is_healthy", return_value=True):
            pool.release(slot, ok=True)
        self.assertEqual(pool.available_count, 1)

    def test_is_ready_requires_initialized_and_slots(self):
        pool = self._make_pool()
        self.assertFalse(pool.is_ready)
        pool._initialized = True
        self.assertFalse(pool.is_ready)  # slot yok
        pool._slots.append(self._make_slot())
        self.assertTrue(pool.is_ready)

    def test_available_count_tracks_queue(self):
        pool = self._make_pool()
        self.assertEqual(pool.available_count, 0)
        pool._available.put(self._make_slot())
        self.assertEqual(pool.available_count, 1)

    def test_shutdown_clears_slots(self):
        pool = self._make_pool()
        for i in range(3):
            slot = self._make_slot(19000 + i)
            pool._slots.append(slot)
            pool._available.put(slot)
        pool._initialized = True
        pool.shutdown()
        self.assertEqual(len(pool._slots), 0)
        self.assertEqual(pool.available_count, 0)

    def test_initialize_without_docker_disables_gracefully(self):
        pool = self._make_pool()
        with patch("backend.sandbox.pool._docker", None):
            pool.initialize()
        self.assertFalse(pool.is_ready)

    def test_health_check_false_on_error(self):
        pool = self._make_pool()
        with patch("backend.sandbox.pool._requests") as mock_requests:
            mock_requests.get.side_effect = Exception("refused")
            self.assertFalse(pool._is_healthy(self._make_slot()))

    def test_health_check_true_on_200(self):
        pool = self._make_pool()
        resp = MagicMock()
        resp.status_code = 200
        with patch("backend.sandbox.pool._requests") as mock_requests:
            mock_requests.get.return_value = resp
            self.assertTrue(pool._is_healthy(self._make_slot()))


def test_pool_snapshot_reports_unavailable_before_initialization():
    pool = SandboxPool(image="test-image", pool_size=3, base_port=19000, owner_id="worker-a")
    assert pool.snapshot() == {
        "state": "unavailable",
        "pool_ready": False,
        "container_count": 0,
        "available_count": 0,
        "target_size": 3,
        "last_error_code": None,
    }


def test_pool_snapshot_reports_degraded_with_partial_capacity():
    pool = SandboxPool(image="test-image", pool_size=3, base_port=19000, owner_id="worker-a")
    pool._slots.append(ContainerSlot(container=MagicMock(), url="http://localhost:19000", port=19000))
    pool._available.put(pool._slots[0])
    pool._state = PoolState.DEGRADED
    assert pool.wait_until_ready(0.01) is True
    assert pool.snapshot()["state"] == "degraded"
    assert pool.snapshot()["pool_ready"] is True


def test_pool_wait_returns_false_after_terminal_unavailable():
    pool = SandboxPool(image="test-image", pool_size=1, base_port=19000, owner_id="worker-a")
    pool._set_state(PoolState.UNAVAILABLE, error_code="docker_unavailable")
    assert pool.wait_until_ready(0.01) is False
    assert pool.snapshot()["last_error_code"] == "docker_unavailable"


def test_cleanup_only_removes_current_owner_containers():
    pool = SandboxPool(image="test-image", pool_size=1, base_port=19000, owner_id="worker-a")
    pool._client = MagicMock()
    pool._client.containers.list.return_value = []
    pool._cleanup_existing()
    pool._client.containers.list.assert_called_once_with(
        all=True,
        filters={"label": "agentgrade.pool_owner=worker-a"},
    )


def test_create_slot_removes_leaked_container_when_health_check_fails():
    pool = SandboxPool(image="test-image", pool_size=1, base_port=19000, owner_id="worker-a")
    pool._client = MagicMock()
    container = MagicMock()
    pool._client.containers.run.return_value = container
    with patch.object(pool, "_wait_healthy", side_effect=RuntimeError("health check timeout")):
        try:
            pool._create_slot(19000)
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass
    container.stop.assert_called_once()
    container.remove.assert_called_once_with(force=True)


def test_replace_slot_marks_pool_degraded_when_recreate_fails():
    pool = SandboxPool(image="test-image", pool_size=2, base_port=19000, owner_id="worker-a")
    slot_a = ContainerSlot(container=MagicMock(), url="http://localhost:19000", port=19000)
    slot_b = ContainerSlot(container=MagicMock(), url="http://localhost:19001", port=19001)
    pool._slots.extend([slot_a, slot_b])
    pool._available.put(slot_a)
    pool._available.put(slot_b)
    pool._set_state(PoolState.READY)

    with patch.object(pool, "_create_slot", side_effect=RuntimeError("docker down")):
        pool._replace_slot(slot_a)

    snapshot = pool.snapshot()
    assert snapshot["container_count"] == 1
    assert snapshot["state"] == "degraded"
    assert snapshot["pool_ready"] is True


def test_replace_slot_marks_pool_unavailable_when_last_slot_fails():
    pool = SandboxPool(image="test-image", pool_size=1, base_port=19000, owner_id="worker-a")
    slot_a = ContainerSlot(container=MagicMock(), url="http://localhost:19000", port=19000)
    pool._slots.append(slot_a)
    pool._set_state(PoolState.READY)

    with patch.object(pool, "_create_slot", side_effect=RuntimeError("docker down")):
        pool._replace_slot(slot_a)

    snapshot = pool.snapshot()
    assert snapshot["container_count"] == 0
    assert snapshot["state"] == "unavailable"
    assert snapshot["pool_ready"] is False


def test_replace_slot_succeeds_and_stays_ready():
    pool = SandboxPool(image="test-image", pool_size=1, base_port=19000, owner_id="worker-a")
    slot_a = ContainerSlot(container=MagicMock(), url="http://localhost:19000", port=19000)
    pool._slots.append(slot_a)
    pool._set_state(PoolState.READY)
    new_slot = ContainerSlot(container=MagicMock(), url="http://localhost:19000", port=19000)

    with patch.object(pool, "_create_slot", return_value=new_slot):
        pool._replace_slot(slot_a)

    snapshot = pool.snapshot()
    assert snapshot["container_count"] == 1
    assert snapshot["state"] == "ready"
    assert snapshot["pool_ready"] is True


def test_replace_slot_discards_new_container_when_shutdown_races_ahead():
    pool = SandboxPool(image="test-image", pool_size=1, base_port=19000, owner_id="worker-a")
    slot_a = ContainerSlot(container=MagicMock(), url="http://localhost:19000", port=19000)
    pool._slots.append(slot_a)
    pool._set_state(PoolState.READY)

    new_container = MagicMock()
    new_slot = ContainerSlot(container=new_container, url="http://localhost:19000", port=19000)

    def fake_create_slot(port):
        # Simulate shutdown() completing concurrently while _create_slot() is in flight.
        pool._slots.clear()
        pool._set_state(PoolState.STOPPING)
        return new_slot

    with patch.object(pool, "_create_slot", side_effect=fake_create_slot):
        pool._replace_slot(slot_a)

    new_container.stop.assert_called_once()
    new_container.remove.assert_called_once_with(force=True)
    assert pool._available.qsize() == 0
    assert len(pool._slots) == 0


def test_replace_slot_discards_new_container_when_state_already_stopping():
    pool = SandboxPool(image="test-image", pool_size=1, base_port=19000, owner_id="worker-a")
    slot_a = ContainerSlot(container=MagicMock(), url="http://localhost:19000", port=19000)
    pool._slots.append(slot_a)
    pool._set_state(PoolState.STOPPING)

    new_container = MagicMock()
    new_slot = ContainerSlot(container=new_container, url="http://localhost:19000", port=19000)

    with patch.object(pool, "_create_slot", return_value=new_slot):
        pool._replace_slot(slot_a)

    new_container.stop.assert_called_once()
    new_container.remove.assert_called_once_with(force=True)
    assert pool._available.qsize() == 0


if __name__ == "__main__":
    unittest.main()
