"""Phase 4A unified release orchestrator: compose existing QA gates."""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SECRET_LINE_PATTERN = re.compile(
    r"(?i)(password|cookie|csrf|authorization|hidden|expected_stdout|stdin|"
    r"expected|source|prompt|raw[\s_-]?payload|private_result|student_result|"
    r"bearer|credential|secret|token)",
)

_DIAGNOSTIC_LINE_LIMIT = 20


class ServiceStateError(RuntimeError):
    """Raised when the docker compose service-state probe fails."""


@dataclass(frozen=True, slots=True)
class ReleaseCommand:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: int


def resolve_npm() -> str:
    if platform.system() == "Windows":
        return "npm.cmd"
    return "npm"


def build_release_commands(browser_evidence: Path | None) -> tuple[ReleaseCommand, ...]:
    python = sys.executable
    npm = resolve_npm()
    commands = (
        ReleaseCommand(
            "backend_full",
            (python, "-m", "pytest", "-q", "backend/tests", "--tb=short"),
            900,
        ),
        ReleaseCommand(
            "frontend_full",
            (npm, "--prefix", "frontend", "test", "--", "--run"),
            300,
        ),
        ReleaseCommand(
            "frontend_build",
            (npm, "--prefix", "frontend", "run", "build"),
            300,
        ),
        ReleaseCommand(
            "compileall",
            (python, "-m", "compileall", "-q", "backend", "frontend/backend", "scripts"),
            180,
        ),
        ReleaseCommand("pool_smoke", (python, "scripts/qa_pool_smoke.py"), 300),
        ReleaseCommand(
            "phase2b_cache",
            (python, "scripts/qa_phase2b_cache_smoke.py", "--manage-services"),
            300,
        ),
        ReleaseCommand(
            "phase2b_case_isolation",
            (python, "scripts/qa_phase2b_case_isolation.py", "--manage-services"),
            300,
        ),
        ReleaseCommand(
            "phase2b_e2e",
            (python, "scripts/qa_phase2b_e2e.py", "--manage-services"),
            600,
        ),
        ReleaseCommand(
            "phase3_expectation",
            (python, "scripts/qa_phase3_algorithm_expectation.py", "--manage-services"),
            600,
        ),
    )
    if browser_evidence is None:
        return commands
    return commands + (
        ReleaseCommand(
            "phase4a_run_audit",
            (
                python,
                "scripts/qa_phase4a_run_audit.py",
                "--evidence",
                str(browser_evidence),
                "--cleanup",
            ),
            300,
        ),
    )


def capture_service_state() -> set[str]:
    result = subprocess.run(
        ["docker", "compose", "ps", "--services", "--filter", "status=running"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ServiceStateError("docker compose ps probe failed")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def verify_service_state(initial: set[str], current: set[str] | None = None) -> bool:
    observed = capture_service_state() if current is None else current
    return observed == initial


def sanitize_diagnostic(text: str) -> str:
    sanitized_lines: list[str] = []
    for line in text.splitlines():
        if _SECRET_LINE_PATTERN.search(line):
            sanitized_lines.append("[redacted]")
        else:
            sanitized_lines.append(line)
    return "\n".join(sanitized_lines)


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    parts = [result.stdout or "", result.stderr or ""]
    return "\n".join(part for part in parts if part)


def _print_failure(spec: ReleaseCommand, *, exit_code: int, output: str, timed_out: bool) -> None:
    print(f"{spec.name}=FAIL", flush=True)
    print(f"exit_code={exit_code}", flush=True)
    if timed_out:
        print(f"timeout_seconds={spec.timeout_seconds}", flush=True)
        print("reason=command timed out", flush=True)
    diagnostic = sanitize_diagnostic(output)
    tail = "\n".join(diagnostic.splitlines()[-_DIAGNOSTIC_LINE_LIMIT:])
    if tail.strip():
        print("diagnostic:", flush=True)
        print(_console_safe(tail), flush=True)


def _run_command(spec: ReleaseCommand) -> tuple[int, str, bool]:
    try:
        completed = subprocess.run(
            list(spec.argv),
            cwd=ROOT,
            timeout=spec.timeout_seconds,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = ""
        if exc.stdout:
            output += exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace")
        if exc.stderr:
            output += exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", "replace")
        return 1, output, True

    return completed.returncode, _combined_output(completed), False


def _fail_service_state_probe() -> int:
    print("RELEASE=FAIL", flush=True)
    print("reason=service_state_probe_failed", flush=True)
    return 1


def run_release(
    *,
    browser_evidence: Path | None,
    system_only: bool = False,
) -> int:
    if not system_only and browser_evidence is None:
        print("RELEASE=FAIL", flush=True)
        print("reason=browser evidence required in final release mode", flush=True)
        return 1

    evidence_for_build: Path | None = None
    if not system_only:
        evidence_for_build = browser_evidence
        if evidence_for_build is None or not evidence_for_build.is_file():
            print("RELEASE=FAIL", flush=True)
            print("reason=browser evidence file missing", flush=True)
            return 1

    try:
        initial_services = capture_service_state()
    except ServiceStateError:
        return _fail_service_state_probe()

    commands = build_release_commands(evidence_for_build)

    for spec in commands:
        exit_code, output, timed_out = _run_command(spec)
        try:
            service_ok = verify_service_state(initial_services)
        except ServiceStateError:
            return _fail_service_state_probe()

        command_failed = exit_code != 0 or timed_out
        if command_failed:
            _print_failure(spec, exit_code=exit_code, output=output, timed_out=timed_out)
        if not service_ok:
            if not command_failed:
                print(f"{spec.name}=FAIL", flush=True)
            print("reason=service_state_mismatch", flush=True)
            return 1
        if command_failed:
            return 1
        print(f"{spec.name}=PASS", flush=True)

    try:
        if not verify_service_state(initial_services):
            print("RELEASE=FAIL", flush=True)
            print("reason=service_state_mismatch", flush=True)
            return 1
    except ServiceStateError:
        return _fail_service_state_probe()

    print("RELEASE=PASS", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Phase 4A unified release orchestrator.")
    parser.add_argument(
        "--manage-services",
        action="store_true",
        help="Accepted for release workflow compatibility; child QA scripts manage services.",
    )
    parser.add_argument(
        "--browser-evidence",
        default=None,
        help="Path to browser-evidence.json for the final audit gate",
    )
    parser.add_argument(
        "--system-only",
        action="store_true",
        help="Run all gates except the browser audit",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    del args.manage_services

    browser_evidence = Path(args.browser_evidence) if args.browser_evidence else None
    return run_release(browser_evidence=browser_evidence, system_only=args.system_only)


if __name__ == "__main__":
    raise SystemExit(main())
