"""TDD tests for Phase 4A unified release orchestrator CLI."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_COMMAND_NAMES = (
    "backend_full",
    "frontend_full",
    "frontend_build",
    "compileall",
    "pool_smoke",
    "phase2b_cache",
    "phase2b_case_isolation",
    "phase2b_e2e",
    "phase3_expectation",
    "phase4a_run_audit",
)


def _load_release_module():
    path = ROOT / "scripts" / "qa_phase4a_release.py"
    spec = importlib.util.spec_from_file_location("qa_phase4a_release", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load release script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["qa_phase4a_release"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release_module():
    return _load_release_module()


def test_release_command_inventory_is_complete(release_module) -> None:
    names = [
        spec.name
        for spec in release_module.build_release_commands(browser_evidence=Path("evidence.json"))
    ]
    assert names == list(EXPECTED_COMMAND_NAMES)


def test_system_only_omits_browser_audit(release_module) -> None:
    names = [spec.name for spec in release_module.build_release_commands(browser_evidence=None)]
    assert names == list(EXPECTED_COMMAND_NAMES[:-1])
    assert "phase4a_run_audit" not in names


def test_missing_browser_evidence_fails_in_final_mode(release_module, capsys) -> None:
    with patch.object(release_module.subprocess, "run") as run_mock:
        code = release_module.run_release(browser_evidence=None, system_only=False)

    assert code == 1
    run_mock.assert_not_called()
    captured = capsys.readouterr()
    assert "RELEASE=FAIL" in captured.out
    assert "browser evidence" in captured.out.lower()


def test_fail_fast_stops_after_first_failure(release_module, capsys) -> None:
    evidence = Path("evidence.json")
    run_mock = MagicMock(
        return_value=MagicMock(returncode=1, stdout="backend failed\n", stderr="")
    )

    with (
        patch.object(release_module, "capture_service_state", return_value=set()),
        patch.object(release_module, "verify_service_state", return_value=True),
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", run_mock),
    ):
        code = release_module.run_release(browser_evidence=evidence, system_only=False)

    assert code == 1
    assert run_mock.call_count == 1
    captured = capsys.readouterr()
    assert "backend_full=FAIL" in captured.out
    assert "frontend_full=PASS" not in captured.out


def test_timeout_marks_command_failed(release_module, capsys) -> None:
    evidence = Path("evidence.json")
    run_mock = MagicMock(
        side_effect=release_module.subprocess.TimeoutExpired(cmd="pytest", timeout=900)
    )

    with (
        patch.object(release_module, "capture_service_state", return_value=set()),
        patch.object(release_module, "verify_service_state", return_value=True),
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", run_mock),
    ):
        code = release_module.run_release(browser_evidence=evidence, system_only=False)

    assert code == 1
    captured = capsys.readouterr()
    assert "backend_full=FAIL" in captured.out
    assert "timeout" in captured.out.lower()


def test_secret_bearing_child_stdout_sanitized(release_module, capsys) -> None:
    evidence = Path("evidence.json")
    secret_stdout = "\n".join(
        [
            "password=super-secret",
            "cookie=session-token",
            "csrf=abc123",
            "authorization: Bearer token",
            "hidden test payload",
            "expected_stdout=leak",
            "stdin data",
            "source_code leak",
            "prompt injection",
            "raw payload dump",
        ]
    )
    run_mock = MagicMock(
        side_effect=[
            MagicMock(returncode=1, stdout=secret_stdout, stderr=""),
        ]
    )

    with (
        patch.object(release_module, "capture_service_state", return_value=set()),
        patch.object(release_module, "verify_service_state", return_value=True),
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", run_mock),
    ):
        code = release_module.run_release(browser_evidence=evidence, system_only=False)

    assert code == 1
    captured = capsys.readouterr()
    assert "super-secret" not in captured.out
    assert "session-token" not in captured.out
    assert "abc123" not in captured.out
    assert "Bearer token" not in captured.out
    assert "backend_full=FAIL" in captured.out


def test_success_output_is_pass_only(release_module, capsys) -> None:
    evidence = Path("evidence.json")
    commands = release_module.build_release_commands(browser_evidence=evidence)

    def _run_side_effect(argv, **kwargs):
        del kwargs
        name = _argv_to_name(release_module, argv)
        if name == "backend_full":
            return MagicMock(returncode=0, stdout="password=hidden\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch.object(release_module, "capture_service_state", return_value=set()),
        patch.object(release_module, "verify_service_state", return_value=True),
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", side_effect=_run_side_effect),
    ):
        code = release_module.run_release(browser_evidence=evidence, system_only=False)

    assert code == 0
    captured = capsys.readouterr()
    assert "password=hidden" not in captured.out
    for spec in commands:
        assert f"{spec.name}=PASS" in captured.out


def test_windows_npm_resolution(release_module) -> None:
    with patch.object(release_module.platform, "system", return_value="Windows"):
        assert release_module.resolve_npm() == "npm.cmd"


def test_unix_npm_resolution(release_module) -> None:
    with patch.object(release_module.platform, "system", return_value="Linux"):
        assert release_module.resolve_npm() == "npm"


def test_build_release_commands_use_sys_executable_and_npm(release_module) -> None:
    with (
        patch.object(release_module, "resolve_npm", return_value="npm.cmd"),
        patch.object(release_module.sys, "executable", r"C:\Python\python.exe"),
    ):
        specs = release_module.build_release_commands(browser_evidence=Path("evidence.json"))

    backend = next(spec for spec in specs if spec.name == "backend_full")
    frontend = next(spec for spec in specs if spec.name == "frontend_full")
    audit = next(spec for spec in specs if spec.name == "phase4a_run_audit")

    assert backend.argv[0] == r"C:\Python\python.exe"
    assert frontend.argv[0] == "npm.cmd"
    evidence_index = audit.argv.index("--evidence")
    assert audit.argv[evidence_index + 1] == "evidence.json"
    assert "--cleanup" in audit.argv


def test_docker_probe_failure_fails_release_closed(release_module, capsys) -> None:
    def _run_side_effect(argv, **kwargs):
        del kwargs
        if list(argv)[:3] == ["docker", "compose", "ps"]:
            return MagicMock(returncode=1, stdout="", stderr="docker unavailable")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", side_effect=_run_side_effect),
    ):
        code = release_module.run_release(
            browser_evidence=Path("evidence.json"),
            system_only=False,
        )

    assert code == 1
    captured = capsys.readouterr()
    assert "RELEASE=FAIL" in captured.out
    assert "RELEASE=PASS" not in captured.out


def test_missing_browser_evidence_file_fails_without_subprocess(release_module, capsys) -> None:
    with (
        patch.object(Path, "is_file", return_value=False),
        patch.object(release_module.subprocess, "run") as run_mock,
    ):
        code = release_module.run_release(
            browser_evidence=Path("missing.json"),
            system_only=False,
        )

    assert code == 1
    run_mock.assert_not_called()
    captured = capsys.readouterr()
    assert "RELEASE=FAIL" in captured.out
    assert "browser evidence file missing" in captured.out.lower()


def test_command_failure_diagnostic_preserved_on_service_state_mismatch(
    release_module, capsys
) -> None:
    evidence = Path("evidence.json")
    run_mock = MagicMock(
        return_value=MagicMock(returncode=1, stdout="safe diagnostic line\n", stderr="")
    )

    with (
        patch.object(release_module, "capture_service_state", return_value={"redis"}),
        patch.object(release_module, "verify_service_state", return_value=False),
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", run_mock),
    ):
        code = release_module.run_release(browser_evidence=evidence, system_only=False)

    assert code == 1
    captured = capsys.readouterr()
    assert "backend_full=FAIL" in captured.out
    assert "exit_code=1" in captured.out
    assert "safe diagnostic line" in captured.out
    assert "service_state_mismatch" in captured.out.lower()


def test_secret_bearing_child_stderr_sanitized(release_module, capsys) -> None:
    evidence = Path("evidence.json")
    run_mock = MagicMock(
        side_effect=[
            MagicMock(returncode=1, stdout="", stderr="password=leaked-secret\n"),
        ]
    )

    with (
        patch.object(release_module, "capture_service_state", return_value=set()),
        patch.object(release_module, "verify_service_state", return_value=True),
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", run_mock),
    ):
        code = release_module.run_release(browser_evidence=evidence, system_only=False)

    assert code == 1
    captured = capsys.readouterr()
    assert "leaked-secret" not in captured.out
    assert "[redacted]" in captured.out


def test_failure_diagnostic_capped_at_twenty_lines(release_module, capsys) -> None:
    evidence = Path("evidence.json")
    long_stdout = "\n".join(f"line-{index}" for index in range(30))
    run_mock = MagicMock(
        side_effect=[
            MagicMock(returncode=1, stdout=long_stdout, stderr=""),
        ]
    )

    with (
        patch.object(release_module, "capture_service_state", return_value=set()),
        patch.object(release_module, "verify_service_state", return_value=True),
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", run_mock),
    ):
        code = release_module.run_release(browser_evidence=evidence, system_only=False)

    assert code == 1
    captured = capsys.readouterr()
    assert "line-29" in captured.out
    assert "line-9" not in captured.out


def test_service_state_mismatch_fails_release(release_module, capsys) -> None:
    evidence = Path("evidence.json")
    run_mock = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))

    with (
        patch.object(release_module, "capture_service_state", return_value={"redis"}),
        patch.object(release_module, "verify_service_state", return_value=False),
        patch.object(Path, "is_file", return_value=True),
        patch.object(release_module.subprocess, "run", run_mock),
    ):
        code = release_module.run_release(browser_evidence=evidence, system_only=False)

    assert code == 1
    captured = capsys.readouterr()
    assert "service_state_mismatch" in captured.out.lower()


def test_system_only_main_skips_browser_audit(release_module, capsys) -> None:
    run_mock = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))

    with (
        patch.object(release_module, "capture_service_state", return_value=set()),
        patch.object(release_module, "verify_service_state", return_value=True),
        patch.object(release_module.subprocess, "run", run_mock),
    ):
        code = release_module.main(["--system-only"])

    assert code == 0
    captured = capsys.readouterr()
    assert "phase4a_run_audit=PASS" not in captured.out
    assert run_mock.call_count == 9


def _argv_to_name(release_module, argv: list[str]) -> str:
    argv_tuple = tuple(argv)
    for spec in release_module.build_release_commands(browser_evidence=Path("evidence.json")):
        if spec.argv == argv_tuple:
            return spec.name
    raise AssertionError(f"unknown argv: {argv}")
