"""Per-case sandbox fixtures, raw result contract, and backend authority."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import ctypes
import pytest

SANDBOX_ROOT = Path(__file__).resolve().parents[2] / "sandbox-images" / "agentgrade"
if str(SANDBOX_ROOT) not in sys.path:
    sys.path.insert(0, str(SANDBOX_ROOT))

if "resource" not in sys.modules:
    sys.modules["resource"] = types.ModuleType("resource")
if "psutil" not in sys.modules:
    _psutil = types.ModuleType("psutil")

    def _noop_process(*_args, **_kwargs):
        proc = MagicMock()
        proc.memory_info.return_value = MagicMock(rss=0)
        proc.children.return_value = []
        proc.is_running.return_value = True
        return proc

    _psutil.Process = _noop_process
    _psutil.NoSuchProcess = Exception
    _psutil.AccessDenied = Exception
    sys.modules["psutil"] = _psutil

ctypes.CDLL = MagicMock(return_value=MagicMock())

from core.orchestrator import (  # noqa: E402
    FixturePolicyError,
    SandboxOrchestrator,
    TestCase as SandboxTestCase,
    parse_execute_test_case,
    validate_fixture_names,
    write_case_fixtures_safely,
)


@dataclass
class _RecordingCall:
    stdin_data: str | None
    extra_files: list[dict[str, str]]
    argv: list | None = None


class RecordingRunner:
    LANGUAGE = "python"

    def __init__(self) -> None:
        self.calls: list[_RecordingCall] = []
        self.executor = MagicMock()

    def run(self, code, stdin_data=None, extra_files=None, argv=None):
        self.calls.append(
            _RecordingCall(
                stdin_data=stdin_data,
                extra_files=list(extra_files or []),
                argv=list(argv or []),
            )
        )
        result = MagicMock()
        result.stdout = ""
        result.stderr = ""
        result.exit_code = 0
        result.wall_time_ms = 1.0
        result.peak_memory_mb = 0.5
        result.timed_out = False
        result.memory_exceeded = False
        result.compile_success = True
        result.success = True
        return result

    def static_analysis(self, code):
        return MagicMock(
            tool="test",
            output="",
            issues=[],
            success=True,
            error="",
        )


class ParseExecuteTestCaseTests(unittest.TestCase):
    def test_parses_id_visibility_expected_exit_code_and_files(self):
        parsed = parse_execute_test_case(
            {
                "id": "case-a",
                "name": "read csv",
                "stdin": "",
                "expected_stdout": "ok\n",
                "expected_exit_code": 0,
                "visibility": "public",
                "files": [{"name": "data.csv", "content": "1,2\n"}],
            },
            index=1,
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.id, "case-a")
        self.assertEqual(parsed.visibility, "public")
        self.assertEqual(parsed.expected_exit_code, 0)
        self.assertEqual(parsed.files, [{"name": "data.csv", "content": "1,2\n"}])

    def test_rejects_invalid_file_entries_without_promoting_to_global_files(self):
        parsed = parse_execute_test_case(
            {
                "id": "case-b",
                "name": "mixed files",
                "files": ["bad", {"name": "ok.txt", "content": "x"}],
            },
            index=2,
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.files, [{"name": "ok.txt", "content": "x"}])

    def test_generates_stable_id_when_missing(self):
        parsed = parse_execute_test_case({"name": "square"}, index=3)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.id, "case-3")


@pytest.mark.parametrize(
    "name",
    [
        "../secret.txt",
        "..\\secret.txt",
        "/tmp/a.txt",
        "solution.py",
        "a.exe",
        "data\x00evil.txt",
    ],
)
def test_validate_fixture_names_rejects_unsafe_paths(name: str) -> None:
    with pytest.raises(FixturePolicyError):
        validate_fixture_names([{"name": name, "content": "x"}])


@pytest.mark.skipif(sys.platform == "win32", reason="symlink privilege requirements differ on Windows")
def test_write_case_fixtures_rejects_symlink_parent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        link_parent = workdir / "data"
        link_parent.symlink_to("/tmp", target_is_directory=True)
        with pytest.raises(FixturePolicyError):
            write_case_fixtures_safely(
                str(workdir),
                [{"name": "data/input.csv", "content": "a,b\n"}],
            )


class PerCaseIsolationTests(unittest.TestCase):
    def test_each_case_receives_only_its_fixture_list(self):
        runner = RecordingRunner()
        orchestrator = SandboxOrchestrator()
        cases = [
            SandboxTestCase(
                id="case-1",
                name="first",
                files=[{"name": "a.txt", "content": "one"}],
            ),
            SandboxTestCase(
                id="case-2",
                name="second",
                files=[{"name": "b.txt", "content": "two"}],
            ),
        ]

        with patch("core.orchestrator.get_runner", return_value=runner):
            report = orchestrator.run_submission(
                code="print('ok')\n",
                language="python",
                test_cases=cases,
            )

        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(runner.calls[1].extra_files, [{"name": "a.txt", "content": "one"}])
        self.assertEqual(runner.calls[2].extra_files, [{"name": "b.txt", "content": "two"}])
        self.assertEqual(len(report.test_results), 2)
        self.assertEqual(report.test_results[0]["id"], "case-1")
        self.assertEqual(report.test_results[1]["id"], "case-2")
        self.assertNotIn("passed", report.test_results[0])


if __name__ == "__main__":
    unittest.main()
