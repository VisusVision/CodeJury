from __future__ import annotations

import ast
import re
from typing import Any

from backend.agents.base import BaseAgent
from backend.agents.code_utils import FunctionInfo, get_code_metrics

_COMPLEXITY_RANK = {
    "O(1)": 0,
    "O(log n)": 1,
    "O(n)": 2,
    "O(n log n)": 3,
    "O(n^2)": 5,
    "O(n^3)": 7,
    "O(2^n)": 9,
    "O(n!)": 10,
    "O(recursive)": 4,
    "O(n * recursive)": 6,
}


def _rank(value: str) -> int:
    return _COMPLEXITY_RANK.get(value, 5)


def _worst(left: str, right: str) -> str:
    return left if _rank(left) >= _rank(right) else right


def _expected_complexity_from_text(text: str) -> str:
    lowered = (text or "").lower()
    expected_match = re.search(
        r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*n\s*\)|tek gecis|tek geÃ§iÅŸ|linear|lineer)",
        lowered,
    )
    if expected_match:
        return "O(n)"
    expected_match = re.search(
        r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*n\s*log\s*n\s*\)|n\s*log\s*n)",
        lowered,
    )
    if expected_match:
        return "O(n log n)"
    expected_match = re.search(
        r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*log\s*n\s*\)|logaritmik)",
        lowered,
    )
    if expected_match:
        return "O(log n)"
    expected_match = re.search(
        r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*1\s*\)|sabit zaman|constant)",
        lowered,
    )
    if expected_match:
        return "O(1)"
    expected_match = re.search(
        r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*n\s*\^\s*2\s*\)|o\(n2\)|quadratic|karesel)",
        lowered,
    )
    if expected_match:
        return "O(n^2)"

    patterns = [
        (r"o\s*\(\s*n\s*\^\s*2\s*\)|o\(n2\)|quadratic|karesel", "O(n^2)"),
        (r"o\s*\(\s*n\s*log\s*n\s*\)|n\s*log\s*n", "O(n log n)"),
        (r"o\s*\(\s*log\s*n\s*\)|logaritmik", "O(log n)"),
        (r"o\s*\(\s*n\s*\)|tek gecis|tek geçiş|linear|lineer", "O(n)"),
        (r"o\s*\(\s*1\s*\)|sabit zaman|constant", "O(1)"),
    ]
    for pattern, value in patterns:
        if re.search(pattern, lowered):
            return value
    return ""


def _detect_data_structures(source: str) -> list[str]:
    found: set[str] = set()
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        tree = None

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                found.add("dict")
            elif isinstance(node, ast.Set):
                found.add("set")
            elif isinstance(node, ast.List):
                found.add("list")
            elif isinstance(node, ast.Call):
                call_name = ""
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr
                if call_name in {"dict", "set", "list", "tuple"}:
                    found.add(call_name)
                elif call_name in {"deque"}:
                    found.add("deque")
                elif call_name in {"heappush", "heappop", "heapify"}:
                    found.add("heap")

    lowered = source.lower()
    checks = [
        ("dict", ("dict(", ".get(", "defaultdict", "counter(")),
        ("set", ("set(", ".add(")),
        ("list", ("list(", ".append(", ".extend(")),
        ("tuple", ("tuple(",)),
        ("heap", ("heapq", "heappush", "heappop", "heapify")),
        ("deque", ("deque",)),
        ("tree", ("left", "right", "node", "root")),
    ]
    for name, tokens in checks:
        if any(token in lowered for token in tokens):
            found.add(name)
    return sorted(set(found))


def _detect_algorithms(source: str, functions: list[FunctionInfo]) -> list[str]:
    lowered = source.lower()
    found: set[str] = set()
    if "sort(" in lowered or ".sort(" in lowered or "sorted(" in lowered:
        found.add("sorting")
    if "binary_search" in lowered or "ikili_arama" in lowered:
        found.add("binary_search")
    if any(fn.uses_recursion for fn in functions):
        found.add("recursion")
    if any(name in lowered for name in ("bfs", "queue", "deque")):
        found.add("bfs")
    if any(name in lowered for name in ("dfs", "recursive", "recursion")):
        found.add("dfs/recursion")
    if re.search(r"for\s+.+:\s*\n\s+for\s+", source):
        found.add("nested_loop")
    for fn in functions:
        name = fn.name
        clean = name.lower()
        if "search" in clean or "ara" in clean:
            found.add("search")
        if "sort" in clean or "sirala" in clean:
            found.add("sorting")
        if "duplicate" in clean or "tekrar" in clean:
            found.add("duplicate_detection")
    return sorted(found) or ["general_iteration"]


def _looks_like_binary_search(source: str, functions: list[FunctionInfo]) -> bool:
    lowered = (source or "").lower()
    if not any("binary" in fn.name.lower() or "ikili" in fn.name.lower() for fn in functions):
        return False
    return (
        "while" in lowered
        and "mid" in lowered
        and re.search(r"\b(lo|low|left)\s*=\s*mid\s*\+\s*1", lowered)
        and re.search(r"\b(hi|high|right)\s*=\s*mid\s*-\s*1", lowered)
    )


class AlgorithmAgent(BaseAgent):
    name = "algorithm"
    description = "Algoritma, veri yapisi ve karmasiklik analizi"

    async def analyze(self, input_data: dict[str, Any]) -> dict[str, Any]:
        source = str(input_data.get("source_code") or "")
        language = str(input_data.get("language") or "python")
        brief = str(input_data.get("assignment_description") or "")
        metrics = get_code_metrics(source, language)

        time_complexity = "O(1)"
        for fn in metrics.functions:
            time_complexity = _worst(time_complexity, fn.complexity)
        if not metrics.functions and metrics.max_nesting_depth >= 2:
            time_complexity = "O(n^2)"
        elif not metrics.functions and metrics.max_nesting_depth == 1:
            time_complexity = "O(n)"
        if _looks_like_binary_search(source, metrics.functions):
            time_complexity = "O(log n)"

        expected = _expected_complexity_from_text(brief)
        issues: list[dict[str, Any]] = []
        gap = "unknown"
        if expected:
            if _rank(time_complexity) > _rank(expected):
                gap = "worse_than_expected"
                issues.append(
                    {
                        "type": "complexity_gap",
                        "description": f"Cozum {time_complexity}; odev beklentisi {expected} gorunuyor.",
                        "severity": "high",
                        "suggested_fix": "Tekrarlayan taramalari dict/set tabanli tek gecis yaklasimina indirin.",
                    }
                )
            elif _rank(time_complexity) < _rank(expected):
                gap = "better_than_expected"
            else:
                gap = "matches_expected"

        if metrics.max_nesting_depth >= 2:
            issues.append(
                {
                    "type": "nested_loop",
                    "description": "Ic ice dongu karmasikligi artiriyor.",
                    "severity": "medium",
                    "suggested_fix": "Lookup veya indeksleme icin uygun veri yapisi kullanin.",
                }
            )

        score = 90
        if gap == "worse_than_expected":
            score -= 35
        if metrics.max_nesting_depth >= 2:
            score -= 10
        score = max(0, min(100, score))

        return {
            "detected_algorithms": _detect_algorithms(source, metrics.functions),
            "data_structures": _detect_data_structures(source),
            "time_complexity": time_complexity,
            "space_complexity": "O(n)" if _detect_data_structures(source) else "O(1)",
            "expected_complexity": expected,
            "complexity_gap": gap,
            "issues": issues,
            "score": score,
        }
