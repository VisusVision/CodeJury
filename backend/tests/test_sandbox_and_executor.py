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
from unittest.mock import MagicMock, patch

from backend.sandbox.executor import _FALLBACK, _LANG_MAP, _simulate_sandbox, run_in_sandbox
from backend.sandbox.pool import ContainerSlot, SandboxPool


_GET_POOL = "backend.sandbox.pool_manager.get_pool"
_REQUESTS_POST = "requests.post"


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


# ═══════════════════════════════════════════════════════════════════════════════
# run_in_sandbox
# ═══════════════════════════════════════════════════════════════════════════════

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
            "static_analysis", "code_metrics", "summary",
        }
        self.assertTrue(required.issubset(set(_FALLBACK.keys())))

    def test_pool_none_falls_back_to_simulation(self):
        with patch(_GET_POOL, return_value=None):
            result = run_in_sandbox("print('hello')\n", "python")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello", result["stdout"])

    def test_pool_not_ready_falls_back_to_simulation(self):
        pool = MagicMock()
        pool.is_ready = False
        with patch(_GET_POOL, return_value=pool):
            result = run_in_sandbox("print('hi')\n", "python")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hi", result["stdout"])

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
            patch(_REQUESTS_POST, return_value=resp) as mock_post,
        ):
            result = run_in_sandbox("print(2+3)\n", "python")

        mock_post.assert_called_once()
        url_arg = mock_post.call_args.args[0] if mock_post.call_args.args else ""
        self.assertIn("/api/execute", url_arg)
        self.assertEqual(result["stdout"], "5")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["compilation_success"])
        pool.release.assert_called_once_with(slot, ok=True)

    def test_http_error_returns_fallback_and_releases_slot(self):
        pool, slot = self._ready_pool_with_slot()
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_REQUESTS_POST, side_effect=Exception("Connection refused")),
        ):
            result = run_in_sandbox("print(1)\n", "python")

        self.assertIn("Sandbox error", result["stderr"])
        self.assertEqual(result["exit_code"], -1)
        pool.release.assert_called_once_with(slot, ok=False)

    def test_connection_error_falls_back_to_simulation_and_marks_slot_unhealthy(self):
        import requests

        pool, slot = self._ready_pool_with_slot()
        files = [{"name": "sayilar.txt", "content": "1\n2\n3\n"}]
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_REQUESTS_POST, side_effect=requests.exceptions.ConnectionError("refused")),
        ):
            result = run_in_sandbox(
                "from pathlib import Path\nprint(Path('sayilar.txt').read_text())\n",
                "python",
                files=files,
            )

        self.assertEqual(result["exit_code"], 0)
        self.assertIn("1", result["stdout"])
        self.assertTrue(result["fixtures_provided"])
        pool.release.assert_called_once_with(slot, ok=False)

    def test_acquire_timeout_returns_fallback(self):
        pool = MagicMock()
        pool.is_ready = True
        pool.acquire.side_effect = TimeoutError("All busy")
        with patch(_GET_POOL, return_value=pool):
            result = run_in_sandbox("print(1)\n", "python")

        self.assertIn("timeout", result["stderr"].lower())
        self.assertEqual(result["exit_code"], -1)
        pool.release.assert_not_called()  # slot hic alinamadi

    def test_test_cases_included_in_payload(self):
        pool, _ = self._ready_pool_with_slot()
        resp = self._ok_response({
            "execution": {}, "test_results": [], "static_analysis": {},
            "code_metrics": {}, "summary": {},
        })
        test_cases = [{"name": "tc1", "stdin": "5", "expected_stdout": "25"}]
        with (
            patch(_GET_POOL, return_value=pool),
            patch(_REQUESTS_POST, return_value=resp) as mock_post,
        ):
            run_in_sandbox("print(int(input())**2)\n", "python", test_cases=test_cases)

        payload = mock_post.call_args.kwargs["json"]
        self.assertIn(test_cases[0], payload["test_cases"])
        self.assertEqual(payload["language"], "python")

    def test_stdin_data_added_as_test_case(self):
        pool, _ = self._ready_pool_with_slot()
        resp = self._ok_response({
            "execution": {}, "test_results": [], "static_analysis": {},
            "code_metrics": {}, "summary": {},
        })
        with (
            patch(_GET_POOL, return_value=pool),
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


if __name__ == "__main__":
    unittest.main()
