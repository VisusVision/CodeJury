"""
executor.py — Pool-based Sandbox Executor

Acquires a container from the sandbox pool, executes code via POST /api/execute,
normalises the result into a standard dict, and releases the container.

Fail-closed: when the sandbox pool is not ready, or a container response is
invalid, run_in_sandbox raises SandboxUnavailableError instead of running
student code on the host. There is no automatic simulation fallback.

Returned dict fields (backward-compatible + enriched):
  stdout, stderr, exit_code, execution_time_ms, peak_memory_mb,
  compilation_success, timed_out, memory_exceeded,
  test_results, static_analysis, code_metrics, summary
"""
import logging
from typing import Any

from backend.sandbox.errors import SandboxUnavailableError
from backend.testing.contracts import FormalTestCase, RawCaseResult, TestFixture
from backend.testing.evaluation import evaluate_case
from backend.testing.fixture_policy import FixturePolicyError, validate_case_fixtures

logger = logging.getLogger("sandbox-executor")

# Language name normalisation (frontend may send different formats)
_LANG_MAP = {
    "python":  "python",
    "py":      "python",
    "cpp":     "cpp",
    "c++":     "cpp",
    "java":    "java",
}

_FALLBACK = {
    "stdout": "",
    "stderr": "",
    "exit_code": -1,
    "execution_time_ms": 0,
    "peak_memory_mb": 0.0,
    "compilation_success": False,
    "timed_out": False,
    "memory_exceeded": False,
    "test_results": [],
    "static_analysis": {},
    "code_metrics": {},
    "summary": {},
    "execution_backend": "simulation",
}

_SAFE_SANDBOX_MESSAGE = "Sandbox kullanılamıyor; Docker ve analysis worker pool durumunu kontrol edin."


def require_sandbox_pool(timeout_s: float = 15.0):
    """Block until a usable (ready/degraded) sandbox pool exists, or raise SandboxUnavailableError."""
    from backend.sandbox.pool_manager import wait_for_pool_ready

    pool = wait_for_pool_ready(timeout_s)
    if pool is None:
        raise SandboxUnavailableError(
            "pool_not_ready",
            _SAFE_SANDBOX_MESSAGE,
            detail=f"pool did not become ready within {timeout_s:.1f}s",
            retryable=True,
        )
    return pool


def _extract_report(data: object) -> tuple[dict, dict]:
    if not isinstance(data, dict):
        raise SandboxUnavailableError(
            "invalid_response",
            _SAFE_SANDBOX_MESSAGE,
            detail="response root is not an object",
            retryable=True,
        )
    report = data.get("report")
    if not isinstance(report, dict):
        raise SandboxUnavailableError(
            "invalid_response",
            _SAFE_SANDBOX_MESSAGE,
            detail="report is missing or not an object",
            retryable=True,
        )
    execution = report.get("execution")
    if not isinstance(execution, dict):
        raise SandboxUnavailableError(
            "invalid_response",
            _SAFE_SANDBOX_MESSAGE,
            detail="report.execution is missing or not an object",
            retryable=True,
        )
    if "exit_code" not in execution or "compile_success" not in execution:
        raise SandboxUnavailableError(
            "invalid_response",
            _SAFE_SANDBOX_MESSAGE,
            detail="execution contract lacks exit_code or compile_success",
            retryable=True,
        )
    return report, execution


def _normalize_single_test_case(raw: dict[str, Any], index: int) -> dict[str, Any]:
    expected = raw.get("expected_stdout", raw.get("expected", ""))
    visibility = str(raw.get("visibility") or "hidden").strip().lower()
    if visibility not in {"public", "hidden"}:
        visibility = "hidden"

    files: list[dict[str, str]] = []
    for item in raw.get("files", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        files.append({"name": name, "content": str(item.get("content", ""))})

    case_id = str(raw.get("id") or raw.get("name") or f"case-{index}").strip()
    return {
        "id": case_id,
        "name": str(raw.get("name") or f"case_{index}")[:80],
        "stdin": str(raw.get("stdin", raw.get("input", ""))),
        "expected_stdout": "" if expected is None else str(expected),
        "expected_exit_code": int(raw.get("expected_exit_code", 0) or 0),
        "visibility": visibility,
        "files": files,
        "source": str(raw.get("source") or "manual"),
        "oracle": str(raw.get("oracle") or "teacher"),
    }


def _formal_case_from_payload(raw: dict[str, Any], index: int) -> FormalTestCase:
    normalized = _normalize_single_test_case(raw, index)
    fixture_models: list[TestFixture] = []
    if normalized["files"]:
        fixture_models = validate_case_fixtures(
            [TestFixture(name=item["name"], content=item["content"]) for item in normalized["files"]]
        )
    source = normalized["source"]
    if source not in {"manual", "ai_approved", "auto_generated"}:
        source = "manual"
    oracle = normalized["oracle"]
    if oracle not in {"teacher", "llm_verified"}:
        oracle = "teacher"
    return FormalTestCase(
        id=normalized["id"],
        name=normalized["name"],
        stdin=normalized["stdin"],
        expected_stdout=normalized["expected_stdout"],
        expected_exit_code=normalized["expected_exit_code"],
        visibility=normalized["visibility"],  # type: ignore[arg-type]
        files=tuple(fixture_models),
        source=source,  # type: ignore[arg-type]
        oracle=oracle,  # type: ignore[arg-type]
    )


def _raw_case_from_report(row: dict[str, Any]) -> RawCaseResult:
    case_id = str(row.get("id") or "").strip()
    if not case_id:
        raise SandboxUnavailableError(
            "invalid_response",
            _SAFE_SANDBOX_MESSAGE,
            detail="test result is missing id",
            retryable=True,
        )
    container_passed = row.get("passed") if "passed" in row else None
    return RawCaseResult(
        id=case_id,
        actual_stdout=str(row.get("actual_stdout") or ""),
        actual_stderr=str(row.get("actual_stderr") or ""),
        actual_exit_code=int(row.get("actual_exit_code", -1)),
        timed_out=bool(row.get("timed_out")),
        memory_exceeded=bool(row.get("memory_exceeded")),
        compile_success=bool(row.get("compile_success")),
        wall_time_ms=float(row.get("wall_time_ms") or 0.0),
        peak_memory_mb=float(row.get("peak_memory_mb") or 0.0),
        container_passed=container_passed if isinstance(container_passed, bool) else None,
    )


def _evaluate_reported_tests(
    input_cases: list[dict[str, Any]],
    reported_tests: list[Any],
    *,
    require_results: bool,
) -> list[dict[str, Any]]:
    if not input_cases:
        return []
    if not reported_tests:
        if require_results:
            raise SandboxUnavailableError(
                "invalid_response",
                _SAFE_SANDBOX_MESSAGE,
                detail="formal test results are missing from container report",
                retryable=True,
            )
        return []

    formal_cases = [_formal_case_from_payload(case, index) for index, case in enumerate(input_cases, 1)]
    raw_by_id: dict[str, RawCaseResult] = {}
    for item in reported_tests:
        if not isinstance(item, dict):
            raise SandboxUnavailableError(
                "invalid_response",
                _SAFE_SANDBOX_MESSAGE,
                detail="test result row is not an object",
                retryable=True,
            )
        raw = _raw_case_from_report(item)
        if raw.id in raw_by_id:
            raise SandboxUnavailableError(
                "invalid_response",
                _SAFE_SANDBOX_MESSAGE,
                detail=f"duplicate test result id: {raw.id}",
                retryable=True,
            )
        raw_by_id[raw.id] = raw

    evaluated: list[dict[str, Any]] = []
    for formal in formal_cases:
        raw = raw_by_id.get(formal.id)
        if raw is None:
            raise SandboxUnavailableError(
                "invalid_response",
                _SAFE_SANDBOX_MESSAGE,
                detail=f"missing test result for id: {formal.id}",
                retryable=True,
            )
        evaluated.append(evaluate_case(formal, raw).model_dump())
    return evaluated


def _build_payload(
    source_code: str,
    language: str,
    stdin_data: str,
    test_cases: list | None,
    files: list | None,
    argv: list | None,
) -> dict:
    normalized_files = _normalize_workdir_files(files)
    payload_cases: list[dict[str, Any]] = []
    if stdin_data:
        payload_cases.append({
            "id": "stdin_run",
            "name": "stdin_run",
            "stdin": stdin_data,
            "expected_exit_code": 0,
            "visibility": "hidden",
            "files": [],
        })
    if test_cases:
        for index, raw in enumerate(test_cases, 1):
            if isinstance(raw, dict):
                payload_cases.append(_normalize_single_test_case(raw, index))

    any_case_files = any(case.get("files") for case in payload_cases)
    if not any_case_files and normalized_files:
        for case in payload_cases:
            case["files"] = list(normalized_files)

    api_language = _LANG_MAP.get(language.lower().strip(), language.lower().strip())
    return {
        "code": source_code,
        "language": api_language,
        "test_cases": payload_cases,
        "files": [] if payload_cases else normalized_files,
        "argv": list(argv or []),
        "fixtures_provided": bool(normalized_files) or any_case_files,
    }


def _normalize_pool_result(
    report: dict,
    execution: dict,
    fixtures_provided: bool,
    payload_cases: list[dict[str, Any]],
    *,
    formal_evaluation: bool,
) -> dict:
    reported_tests = report.get("test_results", [])
    if not isinstance(reported_tests, list):
        reported_tests = []

    if payload_cases:
        try:
            evaluated_tests = _evaluate_reported_tests(
                payload_cases,
                reported_tests,
                require_results=formal_evaluation,
            )
        except FixturePolicyError as exc:
            raise SandboxUnavailableError(
                "invalid_response",
                _SAFE_SANDBOX_MESSAGE,
                detail=str(exc),
                retryable=True,
            ) from exc
    else:
        evaluated_tests = reported_tests if isinstance(reported_tests, list) else []

    summary = dict(report.get("summary", {}) or {})
    stdout = str(execution.get("stdout") or "")
    stderr = str(execution.get("stderr") or "")
    exit_code = int(execution.get("exit_code", -1))

    if evaluated_tests:
        failed_tests = [case for case in evaluated_tests if not bool(case.get("passed"))]
        exit_code = 1 if failed_tests else 0
        if failed_tests:
            error_parts: list[str] = []
            for case in failed_tests:
                error_message = str(case.get("error_message_tr") or "").strip()
                error_type = str(case.get("error_type") or "").strip()
                actual_stderr = str(case.get("actual_stderr") or "").strip()
                if error_message:
                    error_parts.append(error_message)
                elif error_type:
                    error_parts.append(error_type)
                if actual_stderr and actual_stderr not in error_parts:
                    error_parts.append(actual_stderr)
            stderr = "\n".join(part for part in error_parts if part)
        else:
            stderr = ""
        passed = len(evaluated_tests) - len(failed_tests)
        summary["runtime_success"] = not failed_tests
        summary["tests"] = {
            "passed": passed,
            "total": len(evaluated_tests),
            "pass_rate": round((passed / max(len(evaluated_tests), 1)) * 100, 2),
        }

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "execution_time_ms": execution.get("wall_time_ms", 0),
        "peak_memory_mb": execution.get("peak_memory_mb", 0.0),
        "compilation_success": bool(execution.get("compile_success")),
        "timed_out": bool(execution.get("timed_out")),
        "memory_exceeded": bool(execution.get("memory_exceeded")),
        "test_results": evaluated_tests,
        "static_analysis": report.get("static_analysis", {}),
        "code_metrics": report.get("code_metrics", {}),
        "summary": summary,
        "fixtures_provided": fixtures_provided,
        "execution_backend": "pool",
    }


def run_in_sandbox(
    source_code: str,
    language: str,
    stdin_data: str = "",
    test_cases: list | None = None,
    files: list | None = None,
    argv: list | None = None,
) -> dict:
    """
    Execute code through the sandbox pool.

    Fail-closed: raises SandboxUnavailableError when the pool is not ready,
    a container is unreachable, or a container's response is malformed.
    Never runs student code via a host subprocess and never calls
    _simulate_sandbox.

    Args:
        source_code : Source code to execute
        language    : 'python', 'cpp', 'c++', or 'java'
        stdin_data  : Data to pass as stdin
        test_cases  : [{"name": str, "stdin": str, "expected_stdout": str}, ...]
        files       : [{"name": str, "content": str}, ...] written into workdir before run
        argv        : Optional CLI args passed after the solution script

    Returns:
        Enriched sandbox result dict (execution_backend is always "pool" on success).
    """
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise SandboxUnavailableError(
            "dependency_missing",
            _SAFE_SANDBOX_MESSAGE,
            detail="requests package is missing",
            retryable=False,
        ) from exc

    pool = require_sandbox_pool(15.0)
    payload = _build_payload(source_code, language, stdin_data, test_cases, files, argv)
    last_error: SandboxUnavailableError | None = None

    for attempt in range(2):
        slot = None
        release_ok = True
        try:
            slot = pool.acquire()
            print(f"[executor] Sandbox -> {slot.url} (lang={payload['language']})", flush=True)
            response = requests.post(f"{slot.url}/api/execute", json=payload, timeout=120.0)
            response.raise_for_status()
            report, execution = _extract_report(response.json())
            return _normalize_pool_result(
                report,
                execution,
                bool(payload["fixtures_provided"]),
                payload["test_cases"],
                formal_evaluation=bool(test_cases),
            )
        except TimeoutError as exc:
            release_ok = False
            raise SandboxUnavailableError(
                "pool_exhausted",
                _SAFE_SANDBOX_MESSAGE,
                detail=str(exc),
                retryable=True,
            ) from exc
        except requests.exceptions.RequestException as exc:
            release_ok = False
            last_error = SandboxUnavailableError(
                "container_unreachable",
                _SAFE_SANDBOX_MESSAGE,
                detail=str(exc),
                retryable=True,
            )
        except SandboxUnavailableError as exc:
            release_ok = False
            last_error = exc
        except Exception as exc:
            release_ok = False
            last_error = SandboxUnavailableError(
                "invalid_response",
                _SAFE_SANDBOX_MESSAGE,
                detail=f"{type(exc).__name__}: {exc}",
                retryable=True,
            )
        finally:
            if slot is not None:
                pool.release(slot, ok=release_ok)

        if last_error is None or not last_error.retryable or attempt == 1:
            break

    assert last_error is not None
    raise last_error


def _normalize_workdir_files(files: list | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not files:
        return out
    for item in files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        content = item.get("content")
        if not name or content is None:
            continue
        out.append({"name": name, "content": str(content)})
    return out


# ── Fallback: simple simulation when Docker is unavailable ────────────────────

def _simulate_sandbox(
    source_code: str,
    *,
    stdin_data: str = "",
    test_cases: list | None = None,
    files: list | None = None,
    argv: list | None = None,
) -> dict:
    """
    Fallback used when the pool is unavailable.
    Runs code directly without isolation (development only).
    """
    import ast as _ast
    import subprocess
    import sys
    import os
    import tempfile
    from pathlib import Path

    result = {**_FALLBACK}

    try:
        _ast.parse(source_code)
        result["compilation_success"] = True
    except SyntaxError as e:
        result["stderr"] = f"SyntaxError: {e.msg} (line {e.lineno})"
        result["exit_code"] = 1
        return result

    try:
        with tempfile.TemporaryDirectory(prefix="agentgrade-sim-") as tmp:
            tmp_path = Path(tmp)
            for item in _normalize_workdir_files(files):
                fixture_path = tmp_path / item["name"]
                fixture_path.parent.mkdir(parents=True, exist_ok=True)
                fixture_path.write_text(item["content"], encoding="utf-8")
            script_path = tmp_path / "submission.py"
            script_path.write_text(source_code, encoding="utf-8")
            command = [sys.executable, str(script_path), *list(argv or [])]

            def run_once(stdin_text: str):
                return subprocess.run(
                    command,
                    input=stdin_text,
                    capture_output=True, text=True, timeout=10,
                    cwd=str(tmp_path) or os.path.dirname(__file__) or ".",
                )

            tc_list = []
            if stdin_data:
                tc_list.append({"name": "stdin_run", "stdin": stdin_data})
            if test_cases:
                tc_list.extend(test_cases)

            if tc_list:
                reported_tests = []
                failed_tests = []
                for index, raw_case in enumerate(tc_list, 1):
                    case = raw_case if isinstance(raw_case, dict) else {}
                    name = str(case.get("name") or f"case_{index}")
                    stdin_text = str(case.get("stdin", case.get("input", "")) or "")
                    expected_stdout = case.get("expected_stdout", case.get("expected"))
                    expected_exit_code = int(case.get("expected_exit_code", 0) or 0)
                    item = {
                        "name": name,
                        "stdin": stdin_text,
                        "expected_stdout": "" if expected_stdout is None else str(expected_stdout),
                    }
                    try:
                        proc = run_once(stdin_text)
                        actual_stdout = proc.stdout.strip()
                        actual_stderr = proc.stderr.strip()
                        item.update({
                            "actual_stdout": actual_stdout,
                            "actual_stderr": actual_stderr,
                            "actual_exit_code": proc.returncode,
                        })
                        if proc.returncode != expected_exit_code:
                            err_tail = actual_stderr.splitlines()[-1] if actual_stderr else ""
                            item["passed"] = False
                            item["error"] = (
                                f"Exit code: expected={expected_exit_code}, actual={proc.returncode}"
                                + (f"; {err_tail[:200]}" if err_tail else "")
                            )
                        elif expected_stdout is not None:
                            expected = str(expected_stdout).strip()
                            item["passed"] = actual_stdout == expected
                            if not item["passed"]:
                                item["error"] = (
                                    f"Output mismatch - expected: {expected[:100]!r}, "
                                    f"actual: {actual_stdout[:100]!r}"
                                )
                        else:
                            item["passed"] = proc.returncode == 0
                    except subprocess.TimeoutExpired:
                        item.update({
                            "passed": False,
                            "actual_stdout": "",
                            "actual_stderr": "TimeoutError: code did not finish within 10 seconds",
                            "actual_exit_code": 1,
                            "error": "TIMEOUT",
                        })
                    reported_tests.append(item)
                    if not item.get("passed"):
                        failed_tests.append(item)

                passed = len(reported_tests) - len(failed_tests)
                total = len(reported_tests)
                result["test_results"] = reported_tests
                result["stdout"] = "\n".join(
                    str(item.get("actual_stdout") or "") for item in reported_tests
                ).strip()
                result["stderr"] = "\n".join(
                    str(item.get("error") or item.get("actual_stderr") or "")
                    for item in failed_tests
                    if item.get("error") or item.get("actual_stderr")
                )
                result["exit_code"] = 1 if failed_tests else 0
                result["summary"] = {
                    "runtime_success": not failed_tests,
                    "tests": {
                        "passed": passed,
                        "total": total,
                        "pass_rate": round((passed / max(total, 1)) * 100, 2),
                    },
                }
            else:
                proc = run_once(stdin_data)
                result["stdout"]    = proc.stdout
                result["stderr"]    = proc.stderr
                result["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        result["stderr"]    = "TimeoutError: code did not finish within 10 seconds"
        result["exit_code"] = 1
        result["timed_out"] = True
    except Exception as e:
        result["stderr"]    = str(e)
        result["exit_code"] = 1

    result["fixtures_provided"] = bool(_normalize_workdir_files(files))
    result["execution_backend"] = "simulation"
    return result
