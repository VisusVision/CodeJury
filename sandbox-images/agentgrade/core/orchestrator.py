"""
orchestrator.py — Sandbox Pipeline Manager

Supported languages: python, cpp, java
"""
import os, sys, time, json, hashlib, ast
from dataclasses import dataclass, field, asdict
from pathlib import Path, PurePosixPath
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.executor import ResourceLimits, ExecutionResult
from languages.runners import get_runner, StaticAnalysisResult


ALLOWED_SUFFIXES = frozenset({".txt", ".csv", ".tsv", ".json"})
MAX_FILES_PER_CASE = 10
MAX_FILE_BYTES = 64 * 1024
MAX_CASE_BYTES = 256 * 1024


class FixturePolicyError(ValueError):
    pass


def validate_fixture_names(files: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(files) > MAX_FILES_PER_CASE:
        raise FixturePolicyError(
            f"case has {len(files)} fixture files; maximum is {MAX_FILES_PER_CASE}"
        )

    total_bytes = 0
    validated: list[dict[str, str]] = []
    for item in files:
        name = str(item.get("name", "")).strip()
        content = item.get("content")
        if not name or content is None:
            raise FixturePolicyError("fixture requires a non-empty name and content")

        if "\\" in name or "\x00" in name:
            raise FixturePolicyError(f"invalid fixture name: {name!r}")

        path = PurePosixPath(name)
        if path.is_absolute():
            raise FixturePolicyError(f"absolute fixture path not allowed: {name!r}")
        if ".." in path.parts:
            raise FixturePolicyError(f"path traversal not allowed: {name!r}")

        suffix = path.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise FixturePolicyError(
                f"disallowed fixture suffix {suffix!r} for {name!r}"
            )

        file_bytes = len(str(content).encode("utf-8"))
        if file_bytes > MAX_FILE_BYTES:
            raise FixturePolicyError(
                f"fixture {name!r} exceeds per-file byte limit ({file_bytes} > {MAX_FILE_BYTES})"
            )

        total_bytes += file_bytes
        if total_bytes > MAX_CASE_BYTES:
            raise FixturePolicyError(
                f"case fixtures exceed total byte limit ({total_bytes} > {MAX_CASE_BYTES})"
            )

        validated.append({"name": name, "content": str(content)})

    return validated


def write_case_fixtures_safely(workdir: str, files: list[dict[str, str]]) -> None:
    validated = validate_fixture_names(files)
    root = Path(workdir).resolve(strict=False)

    for item in validated:
        destination = (root / PurePosixPath(item["name"])).resolve(strict=False)
        if destination != root and root not in destination.parents:
            raise FixturePolicyError(f"fixture escapes workdir: {item['name']!r}")

        parent = destination.parent
        if parent != root:
            parent.mkdir(parents=True, exist_ok=True)
            current = parent
            while current != root:
                if current.is_symlink():
                    raise FixturePolicyError(
                        f"fixture parent is a symlink: {item['name']!r}"
                    )
                current = current.parent

        if destination.exists() and destination.is_symlink():
            raise FixturePolicyError(f"fixture destination is a symlink: {item['name']!r}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "x" if not destination.exists() else "w", encoding="utf-8") as handle:
            handle.write(item["content"])


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class TestCase:
    id: str
    name: str
    stdin: Optional[str] = None
    expected_stdout: Optional[str] = None
    expected_exit_code: int = 0
    visibility: str = "hidden"
    files: list[dict[str, str]] = field(default_factory=list)
    description: str = ""


def parse_execute_test_case(raw: dict, *, index: int) -> TestCase | None:
    if not isinstance(raw, dict):
        return None
    try:
        files: list[dict[str, str]] = []
        for item in raw.get("files", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            files.append({"name": name, "content": str(item.get("content", ""))})

        visibility = str(raw.get("visibility") or "hidden").strip().lower()
        if visibility not in {"public", "hidden"}:
            visibility = "hidden"

        case_id = str(raw.get("id") or "").strip() or f"case-{index}"
        return TestCase(
            id=case_id,
            name=str(raw.get("name") or f"test_{index}")[:80],
            stdin=raw.get("stdin"),
            expected_stdout=raw.get("expected_stdout"),
            expected_exit_code=int(raw.get("expected_exit_code", 0)),
            visibility=visibility,
            files=files,
            description=str(raw.get("description", "")),
        )
    except Exception:
        return None


@dataclass
class TestCaseResult:
    id: str
    name: str
    actual_stdout: str = ""
    actual_stderr: str = ""
    actual_exit_code: int = -1
    timed_out: bool = False
    memory_exceeded: bool = False
    compile_success: bool = False
    wall_time_ms: float = 0.0
    peak_memory_mb: float = 0.0


@dataclass
class CodeMetrics:
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    function_count: int = 0
    class_count: int = 0
    max_function_length: int = 0
    cyclomatic_complexity: int = 0
    avg_line_length: float = 0
    max_line_length: int = 0
    has_docstrings: bool = False
    has_type_hints: bool = False


# ── Metric Calculators ────────────────────────────────────────────────────────

def compute_python_metrics(code):
    m = CodeMetrics()
    lines = code.splitlines()
    m.total_lines = len(lines)

    for line in lines:
        s = line.strip()
        if not s:
            m.blank_lines += 1
        elif s.startswith("#") or '"""' in s or "'''" in s:
            m.comment_lines += 1
        else:
            m.code_lines += 1

    m.max_line_length = max((len(l) for l in lines), default=0)
    m.avg_line_length = round(sum(len(l) for l in lines) / max(len(lines), 1), 1)

    try:
        tree = ast.parse(code)
        fn_lengths = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m.function_count += 1
                fn_len = getattr(node, "end_lineno", 0) - getattr(node, "lineno", 0)
                fn_lengths.append(fn_len)
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    m.has_docstrings = True
                if node.returns or any(a.annotation for a in node.args.args):
                    m.has_type_hints = True
            elif isinstance(node, ast.ClassDef):
                m.class_count += 1
            elif isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With)):
                m.cyclomatic_complexity += 1
        m.max_function_length = max(fn_lengths, default=0)
    except Exception:
        pass

    return m


def compute_c_metrics(code):
    """Line-based metric computation for C/C++ and Java."""
    m = CodeMetrics()
    lines = code.splitlines()
    m.total_lines = len(lines)
    in_block_comment = False

    for line in lines:
        s = line.strip()
        if not s:
            m.blank_lines += 1
        elif s.startswith("//") or in_block_comment:
            m.comment_lines += 1
        elif "/*" in s:
            m.comment_lines += 1
            in_block_comment = True
        else:
            m.code_lines += 1
        if "*/" in s:
            in_block_comment = False

        for keyword in ("if ", "for ", "while ", "case ", "catch "):
            if keyword in s:
                m.cyclomatic_complexity += 1

    m.max_line_length = max((len(l) for l in lines), default=0)
    m.avg_line_length = round(sum(len(l) for l in lines) / max(len(lines), 1), 1)
    return m


# ── Report Data Model ─────────────────────────────────────────────────────────

@dataclass
class SandboxReport:
    submission_id: str = ""
    language: str = ""
    code_hash: str = ""
    timestamp: float = field(default_factory=time.time)
    execution: dict = field(default_factory=dict)
    test_results: list = field(default_factory=list)
    tests_passed: int = 0
    tests_total: int = 0
    static_analysis: dict = field(default_factory=dict)
    code_metrics: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def to_dict(self): return asdict(self)
    def to_json(self, indent=2): return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ── Main Orchestrator ─────────────────────────────────────────────────────────

class SandboxOrchestrator:
    def __init__(self, limits=None):
        self.limits = limits or ResourceLimits()

    def run_submission(self, code, language, test_cases=None, submission_id=None, workdir_files=None, argv=None):
        report = SandboxReport()
        report.language = language.lower()
        report.code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        report.submission_id = submission_id or f"sub_{report.code_hash}_{int(time.time())}"
        report.timestamp = time.time()

        MEMORY_BY_LANGUAGE = {
            "python": 512,
            "cpp":    128,
            "java":   256,
        }
        dynamic_limits = ResourceLimits(
            cpu_time_sec=self.limits.cpu_time_sec,
            wall_time_sec=self.limits.wall_time_sec,
            memory_mb=MEMORY_BY_LANGUAGE.get(language.lower(), self.limits.memory_mb),
            disk_mb=self.limits.disk_mb,
            max_processes=self.limits.max_processes,
            max_open_files=self.limits.max_open_files,
        )

        try:
            runner = get_runner(language, dynamic_limits)
        except ValueError as e:
            report.summary = {"error": str(e), "runnable": False}
            return report

        fallback_files = list(workdir_files or [])
        if test_cases:
            any_case_files = any(tc.files for tc in test_cases)
            if not any_case_files and fallback_files:
                copied = validate_fixture_names(fallback_files)
                for tc in test_cases:
                    tc.files = list(copied)
            exec_result = runner.run(code, argv=argv)
        else:
            exec_result = runner.run(code, extra_files=fallback_files or None, argv=argv)
        report.execution = exec_result.to_dict()

        test_results = []
        if test_cases:
            for tc in test_cases:
                tcr = self._run_test_case(runner, code, tc, argv=argv)
                test_results.append(asdict(tcr))
        report.tests_total = len(test_cases) if test_cases else 0
        report.tests_passed = 0
        report.test_results = test_results

        sa = runner.static_analysis(code)
        report.static_analysis = {
            "tool": sa.tool,
            "output": sa.output,
            "issues": sa.issues,
            "issue_count": len(sa.issues),
            "success": sa.success,
            "error": sa.error,
        }

        lang = report.language
        if lang == "python":
            metrics = compute_python_metrics(code)
        else:
            metrics = compute_c_metrics(code)
        report.code_metrics = asdict(metrics)

        report.summary = self._build_summary(report, exec_result)
        return report

    def _run_test_case(self, runner, code, tc, argv=None):
        result = TestCaseResult(
            id=tc.id,
            name=tc.name,
        )
        extra_files: list[dict[str, str]] = []
        try:
            if tc.files:
                extra_files = validate_fixture_names(tc.files)
            er = runner.run(
                code,
                stdin_data=tc.stdin,
                extra_files=extra_files or None,
                argv=argv,
            )
            result.actual_stdout = er.stdout
            result.actual_stderr = er.stderr
            result.actual_exit_code = er.exit_code
            result.wall_time_ms = er.wall_time_ms
            result.peak_memory_mb = getattr(er, "peak_memory_mb", 0.0)
            result.timed_out = bool(er.timed_out)
            result.memory_exceeded = bool(er.memory_exceeded)
            result.compile_success = bool(getattr(er, "compile_success", True))
        except FixturePolicyError as exc:
            result.actual_stderr = str(exc)
            result.actual_exit_code = 1
            result.compile_success = False
        except Exception as e:
            result.actual_stderr = str(e)
            result.actual_exit_code = 1
            result.compile_success = False
        return result

    def _build_summary(self, report, exec_result):
        severity = {"error": 0, "warning": 0, "info": 0, "security": 0}
        for issue in report.static_analysis.get("issues", []):
            code = issue.get("code", "")
            if code.startswith("E") or code == "ERROR":
                severity["error"] += 1
            elif code.startswith("S"):
                severity["security"] += 1
            elif code.startswith("W") or code == "WARNING":
                severity["warning"] += 1
            else:
                severity["info"] += 1

        return {
            "runnable": exec_result.compile_success and not exec_result.timed_out,
            "compile_success": exec_result.compile_success,
            "runtime_success": exec_result.success,
            "timed_out": exec_result.timed_out,
            "memory_exceeded": exec_result.memory_exceeded,
            "performance": {
                "wall_time_ms": round(exec_result.wall_time_ms, 2),
                "cpu_time_ms": round(exec_result.cpu_time_ms, 2),
                "peak_memory_mb": round(exec_result.peak_memory_mb, 2),
            },
            "tests": {
                "passed": report.tests_passed,
                "total": report.tests_total,
                "pass_rate": round(
                    report.tests_passed / report.tests_total * 100, 1
                ) if report.tests_total > 0 else None,
            },
            "code_quality_signals": {
                "total_lines": report.code_metrics.get("total_lines", 0),
                "cyclomatic_complexity": report.code_metrics.get("cyclomatic_complexity", 0),
                "function_count": report.code_metrics.get("function_count", 0),
                "max_function_length": report.code_metrics.get("max_function_length", 0),
                "has_docstrings": report.code_metrics.get("has_docstrings", False),
                "has_type_hints": report.code_metrics.get("has_type_hints", False),
                "comment_ratio": round(
                    report.code_metrics.get("comment_lines", 0) /
                    max(report.code_metrics.get("total_lines", 1), 1) * 100, 1
                ),
            },
            "static_analysis": {
                "total_issues": report.static_analysis.get("issue_count", 0),
                "by_severity": severity,
            },
        }
