"""
executor.py — Pool-based Sandbox Executor

Acquires a container from the sandbox pool, executes code via POST /api/execute,
normalises the result into a standard dict, and releases the container.

Returned dict fields (backward-compatible + enriched):
  stdout, stderr, exit_code, execution_time_ms, peak_memory_mb,
  compilation_success, timed_out, memory_exceeded,
  test_results, static_analysis, code_metrics, summary
"""
import logging

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

    Args:
        source_code : Source code to execute
        language    : 'python', 'cpp', 'c++', or 'java'
        stdin_data  : Data to pass as stdin
        test_cases  : [{"name": str, "stdin": str, "expected_stdout": str}, ...]
        files       : [{"name": str, "content": str}, ...] written into workdir before run
        argv        : Optional CLI args passed after the solution script

    Returns:
        Enriched sandbox result dict
    """
    try:
        import requests
    except ModuleNotFoundError:
        return {**_FALLBACK, "stderr": "'requests' package missing (pip install requests)"}

    from backend.sandbox.pool_manager import get_pool

    normalized_files = _normalize_workdir_files(files)

    pool = get_pool()
    if pool is None or not pool.is_ready:
        print("[executor] Pool hazir degil, simulasyon modu kullaniliyor", flush=True)
        return _simulate_sandbox(
            source_code,
            stdin_data=stdin_data,
            test_cases=test_cases,
            files=normalized_files,
            argv=argv,
        )

    api_lang = _LANG_MAP.get(language.lower().strip(), language.lower().strip())

    # Build test case list
    tc_list = []
    if stdin_data:
        tc_list.append({"name": "stdin_run", "stdin": stdin_data})
    if test_cases:
        tc_list.extend(test_cases)

    payload = {
        "code":       source_code,
        "language":   api_lang,
        "test_cases": tc_list,
        "files":      normalized_files,
        "argv":       list(argv or []),
        "fixtures_provided": bool(normalized_files),
    }

    slot = None
    release_ok = True
    try:
        slot = pool.acquire()
        print(f"[executor] Sandbox -> {slot.url} (lang={api_lang})", flush=True)
        resp = requests.post(
            f"{slot.url}/api/execute",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        data   = resp.json()
        report = data.get("report", {})
        exec_i = report.get("execution", {})
        reported_tests = report.get("test_results", [])
        summary = dict(report.get("summary", {}) or {})
        stdout = exec_i.get("stdout", "")
        stderr = exec_i.get("stderr", "")
        exit_code = exec_i.get("exit_code", -1)
        if tc_list and reported_tests:
            failed_tests = [tc for tc in reported_tests if not tc.get("passed")]
            if failed_tests:
                exit_code = 1
                stderr_parts = []
                for tc in failed_tests:
                    err = str(tc.get("error") or "").strip()
                    actual_stderr = str(tc.get("actual_stderr") or "").strip()
                    if err:
                        stderr_parts.append(err)
                    if actual_stderr and actual_stderr not in err:
                        stderr_parts.append(actual_stderr)
                stderr = "\n".join(part for part in stderr_parts if part)
            else:
                exit_code = 0
                stderr = ""
            summary["runtime_success"] = not failed_tests
            summary.setdefault("tests", {})
            if isinstance(summary["tests"], dict):
                summary["tests"]["passed"] = len(reported_tests) - len(failed_tests)
                summary["tests"]["total"] = len(reported_tests)
                summary["tests"]["pass_rate"] = round(
                    ((len(reported_tests) - len(failed_tests)) / max(len(reported_tests), 1)) * 100,
                    2,
                )

        return {
            # Legacy fields (backward-compatible)
            "stdout":              stdout,
            "stderr":              stderr,
            "exit_code":           exit_code,
            "execution_time_ms":   exec_i.get("wall_time_ms", 0),
            "peak_memory_mb":      exec_i.get("peak_memory_mb", 0.0),
            "compilation_success": exec_i.get("compile_success", False),
            # Enriched fields (used by agents)
            "timed_out":           exec_i.get("timed_out", False),
            "memory_exceeded":     exec_i.get("memory_exceeded", False),
            "test_results":        reported_tests,
            "static_analysis":     report.get("static_analysis", {}),
            "code_metrics":        report.get("code_metrics", {}),
            "summary":             summary,
            "fixtures_provided":   bool(normalized_files),
            "execution_backend":   "pool",
        }

    except TimeoutError as e:
        logger.error(f"[executor] Pool timeout: {e}")
        release_ok = False
        return {**_FALLBACK, "stderr": f"Sandbox timeout: {e}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"[executor] Container request failed, falling back to simulation: {e}")
        release_ok = False
        simulated = _simulate_sandbox(
            source_code,
            stdin_data=stdin_data,
            test_cases=test_cases,
            files=normalized_files,
            argv=argv,
        )
        simulated["stderr"] = (
            simulated.get("stderr", "")
            + ("\n" if simulated.get("stderr") else "")
            + f"Sandbox container unavailable; simulation fallback used: {e}"
        )
        return simulated
    except Exception as e:
        logger.error(f"[executor] Error: {e}")
        release_ok = False
        return {**_FALLBACK, "stderr": f"Sandbox error: {e}"}
    finally:
        if slot is not None:
            pool.release(slot, ok=release_ok)


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
