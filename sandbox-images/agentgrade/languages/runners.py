"""
runners.py — Language Runners

Supported languages: Python, C++, Java
"""
import os, ast, subprocess, sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.executor import SandboxExecutor, IsolatedWorkdir, ResourceLimits, ExecutionResult


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class StaticAnalysisResult:
    tool: str = ""
    output: str = ""
    issues: list = field(default_factory=list)
    success: bool = True
    error: str = ""


# ── Helper ────────────────────────────────────────────────────────────────────

def _loop_depth(node, current=1):
    max_depth = current
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.For, ast.While)):
            depth = _loop_depth(child, current + 1)
            if depth > max_depth:
                max_depth = depth
    return max_depth


# ── Python Runner ─────────────────────────────────────────────────────────────

class PythonRunner:
    LANGUAGE = "python"

    def __init__(self, limits=None):
        self.limits = limits or ResourceLimits()
        self.executor = SandboxExecutor(self.limits)

    def run(self, code, stdin_data=None):
        with IsolatedWorkdir("py_") as workdir:
            with open(os.path.join(workdir, "solution.py"), "w") as f:
                f.write(code)
            return self.executor.run(
                ["python3", "-u", "solution.py"],
                workdir,
                stdin_data=stdin_data,
                language="python"
            )

    def static_analysis(self, code):
        result = StaticAnalysisResult(tool="python-ast")
        issues = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            result.success = False
            result.error = f"SyntaxError: {e.msg} (line {e.lineno})"
            result.issues.append({
                "line": e.lineno or 0,
                "col": e.offset or 0,
                "code": "E999",
                "message": f"SyntaxError: {e.msg}"
            })
            return result

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in ("eval", "exec", "__import__"):
                    issues.append({
                        "line": getattr(node, "lineno", 0),
                        "col": getattr(node, "col_offset", 0),
                        "code": "S001",
                        "message": f"Security warning: use of '{func.id}()' detected"
                    })

            if isinstance(node, (ast.For, ast.While)):
                depth = _loop_depth(node)
                if depth >= 3:
                    issues.append({
                        "line": getattr(node, "lineno", 0),
                        "col": 0,
                        "code": "C001",
                        "message": f"{depth}-level nested loop — potential complexity risk"
                    })

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_len = getattr(node, "end_lineno", 0) - getattr(node, "lineno", 0)
                if fn_len > 50:
                    issues.append({
                        "line": getattr(node, "lineno", 0),
                        "col": 0,
                        "code": "C002",
                        "message": f"'{node.name}' is {fn_len} lines long (max 50)"
                    })
                has_doc = (
                    node.body and
                    isinstance(node.body[0], ast.Expr) and
                    isinstance(node.body[0].value, ast.Constant) and
                    isinstance(node.body[0].value.value, str)
                )
                if not has_doc and fn_len > 5:
                    issues.append({
                        "line": getattr(node, "lineno", 0),
                        "col": 0,
                        "code": "D001",
                        "message": f"'{node.name}' is missing a docstring"
                    })

        result.issues = issues
        result.output = f"{len(issues)} potential issue(s) found"
        return result


# ── C++ Runner ────────────────────────────────────────────────────────────────

class CppRunner:
    LANGUAGE = "cpp"

    def __init__(self, limits=None):
        self.limits = limits or ResourceLimits()
        self.executor = SandboxExecutor(self.limits)

    def run(self, code, stdin_data=None):
        with IsolatedWorkdir("cpp_") as workdir:
            with open(os.path.join(workdir, "solution.cpp"), "w") as f:
                f.write(code)
            return self.executor.run_with_compile(
                compile_cmd=[
                    "g++", "-Wall", "-Wextra", "-O2", "-std=c++17",
                    "-fstack-protector-strong",
                    "solution.cpp", "-o", "solution"
                ],
                run_cmd=["./solution"],
                workdir=workdir,
                stdin_data=stdin_data,
                language="cpp"
            )

    def static_analysis(self, code):
        result = StaticAnalysisResult(tool="g++-wall")
        with IsolatedWorkdir("cpp_sa_") as workdir:
            with open(os.path.join(workdir, "solution.cpp"), "w") as f:
                f.write(code)
            try:
                proc = subprocess.run(
                    ["g++", "-Wall", "-Wextra", "-fsyntax-only", "-std=c++17", "solution.cpp"],
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                result.output = proc.stderr
                result.success = (proc.returncode == 0)
                for line in proc.stderr.splitlines():
                    if ": warning:" in line or ": error:" in line:
                        parts = line.split(":")
                        try:
                            lineno = int(parts[1]) if len(parts) > 1 else 0
                            col    = int(parts[2]) if len(parts) > 2 else 0
                            msg    = ":".join(parts[4:]).strip() if len(parts) > 4 else line
                            result.issues.append({
                                "line": lineno, "col": col,
                                "code": "WARNING" if "warning" in line else "ERROR",
                                "message": msg
                            })
                        except Exception:
                            pass
            except Exception as e:
                result.error = str(e)
                result.success = False
        return result


# ── Java Runner ───────────────────────────────────────────────────────────────

class JavaRunner:
    LANGUAGE = "java"

    def __init__(self, limits=None):
        self.limits = limits or ResourceLimits()
        self.executor = SandboxExecutor(self.limits)

    def run(self, code, stdin_data=None):
        with IsolatedWorkdir("java_") as workdir:
            with open(os.path.join(workdir, "Main.java"), "w") as f:
                f.write(code)
            return self.executor.run_with_compile(
                compile_cmd=["javac", "Main.java"],
                run_cmd=["java", "-cp", ".", "Main"],
                workdir=workdir,
                stdin_data=stdin_data,
                language="java"
            )

    def static_analysis(self, code):
        """Run static analysis using javac -Xlint:all."""
        result = StaticAnalysisResult(tool="javac-xlint")
        with IsolatedWorkdir("java_sa_") as workdir:
            with open(os.path.join(workdir, "Main.java"), "w") as f:
                f.write(code)
            try:
                proc = subprocess.run(
                    ["javac", "-Xlint:all", "Main.java"],
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                result.output = proc.stderr
                result.success = (proc.returncode == 0)
                for line in proc.stderr.splitlines():
                    if ": warning:" in line or ": error:" in line:
                        parts = line.split(":")
                        try:
                            lineno = int(parts[1]) if len(parts) > 1 else 0
                            msg    = ":".join(parts[2:]).strip() if len(parts) > 2 else line
                            result.issues.append({
                                "line": lineno, "col": 0,
                                "code": "WARNING" if "warning" in line else "ERROR",
                                "message": msg
                            })
                        except Exception:
                            pass
            except Exception as e:
                result.error = str(e)
                result.success = False
        return result


# ── Language Registry ─────────────────────────────────────────────────────────

SUPPORTED_LANGUAGES = {
    "python": PythonRunner,
    "py":     PythonRunner,
    "cpp":    CppRunner,
    "c++":    CppRunner,
    "java":   JavaRunner,
}


def get_runner(language, limits=None):
    cls = SUPPORTED_LANGUAGES.get(language.lower().strip())
    if not cls:
        raise ValueError(
            f"Unsupported language: '{language}'. "
            f"Supported: {list(SUPPORTED_LANGUAGES.keys())}"
        )
    return cls(limits)
