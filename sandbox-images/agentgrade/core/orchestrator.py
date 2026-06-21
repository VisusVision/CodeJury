"""
orchestrator.py — Sandbox Pipeline Manager

Supported languages: python, cpp, java
"""
import os, sys, time, json, hashlib, ast
from dataclasses import dataclass, field, asdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.executor import ResourceLimits, ExecutionResult
from languages.runners import get_runner, StaticAnalysisResult


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class TestCase:
    name: str
    stdin: Optional[str] = None
    expected_stdout: Optional[str] = None
    expected_exit_code: int = 0
    description: str = ""


@dataclass
class TestCaseResult:
    name: str
    passed: bool = False
    description: str = ""
    actual_stdout: str = ""
    expected_stdout: str = ""
    actual_exit_code: int = -1
    expected_exit_code: int = 0
    wall_time_ms: float = 0
    error: str = ""


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

        # Per-language memory limits
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

        exec_result = runner.run(code, extra_files=workdir_files, argv=argv)
        report.execution = exec_result.to_dict()

        # Run test cases if provided
        test_results = []
        if test_cases:
            for tc in test_cases:
                tcr = self._run_test_case(runner, code, tc)
                test_results.append(asdict(tcr))
                if tcr.passed:
                    report.tests_passed += 1
        report.tests_total = len(test_cases) if test_cases else 0
        report.test_results = test_results

        # Static analysis
        sa = runner.static_analysis(code)
        report.static_analysis = {
            "tool": sa.tool,
            "output": sa.output,
            "issues": sa.issues,
            "issue_count": len(sa.issues),
            "success": sa.success,
            "error": sa.error,
        }

        # Code metrics (Python uses AST; C++/Java use line-based analysis)
        lang = report.language
        if lang == "python":
            metrics = compute_python_metrics(code)
        else:
            metrics = compute_c_metrics(code)
        report.code_metrics = asdict(metrics)

        report.summary = self._build_summary(report, exec_result)
        return report

    def _run_test_case(self, runner, code, tc):
        result = TestCaseResult(
            name=tc.name,
            description=tc.description,
            expected_stdout=tc.expected_stdout or "",
            expected_exit_code=tc.expected_exit_code,
        )
        try:
            er = runner.run(code, stdin_data=tc.stdin)
            result.actual_stdout = er.stdout.strip()
            result.actual_exit_code = er.exit_code
            result.wall_time_ms = er.wall_time_ms

            if er.timed_out:
                result.passed = False
                result.error = "TIMEOUT"
            elif er.memory_exceeded:
                result.passed = False
                result.error = "MEMORY_EXCEEDED"
            elif er.exit_code != tc.expected_exit_code:
                result.passed = False
                result.error = f"Exit code: expected={tc.expected_exit_code}, actual={er.exit_code}"
            elif tc.expected_stdout is not None:
                exp = tc.expected_stdout.strip()
                act = er.stdout.strip()
                result.passed = (act == exp)
                if not result.passed:
                    result.error = f"Output mismatch — expected: {repr(exp[:100])}, actual: {repr(act[:100])}"
            else:
                result.passed = er.success
        except Exception as e:
            result.passed = False
            result.error = str(e)
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
