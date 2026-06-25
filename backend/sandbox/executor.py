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
        return _simulate_sandbox(source_code, files=normalized_files, argv=argv)

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

        return {
            # Legacy fields (backward-compatible)
            "stdout":              exec_i.get("stdout", ""),
            "stderr":              exec_i.get("stderr", ""),
            "exit_code":           exec_i.get("exit_code", -1),
            "execution_time_ms":   exec_i.get("wall_time_ms", 0),
            "peak_memory_mb":      exec_i.get("peak_memory_mb", 0.0),
            "compilation_success": exec_i.get("compile_success", False),
            # Enriched fields (used by agents)
            "timed_out":           exec_i.get("timed_out", False),
            "memory_exceeded":     exec_i.get("memory_exceeded", False),
            "test_results":        report.get("test_results", []),
            "static_analysis":     report.get("static_analysis", {}),
            "code_metrics":        report.get("code_metrics", {}),
            "summary":             report.get("summary", {}),
            "fixtures_provided":   bool(normalized_files),
        }

    except TimeoutError as e:
        logger.error(f"[executor] Pool timeout: {e}")
        release_ok = False
        return {**_FALLBACK, "stderr": f"Sandbox timeout: {e}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"[executor] Container request failed, falling back to simulation: {e}")
        release_ok = False
        simulated = _simulate_sandbox(source_code, files=normalized_files, argv=argv)
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
            proc = subprocess.run(
                command,
                capture_output=True, text=True, timeout=10,
                cwd=str(tmp_path) or os.path.dirname(__file__) or ".",
            )
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
    return result
