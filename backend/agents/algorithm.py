from __future__ import annotations

import ast
import json
import re
from typing import Any

from backend.agents.base import BaseAgent, LLMInferenceError, build_llm_user_suffix, format_assignment_context_for_prompt
from backend.agents.code_utils import FunctionInfo, get_code_metrics
from backend.agents.json_output_schema import ALGORITHM_OUTPUT_SCHEMA, normalize_agent_severity

_ALGORITHM_SYSTEM_PROMPT = """
You are an algorithm analysis agent for programming assignments.
Return only JSON. Evaluate the submitted code's algorithmic approach, named algorithms,
data structures, Big-O complexity, and whether it is more complex than the assignment expects.
Be concrete and code-grounded. Do not over-credit inefficient code.
"""

_ALGORITHM_REQUIRED_KEYS = [
    "detected_algorithms",
    "data_structures",
    "time_complexity",
    "space_complexity",
    "expected_complexity",
    "complexity_gap",
    "algorithm_analysis",
    "data_structure_analysis",
    "issues",
    "score",
]

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


def _safe_str_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out or list(fallback)


def _merge_str_lists(*lists: list[str], fallback: list[str] | None = None, limit: int = 8) -> list[str]:
    merged: list[str] = []
    for values in lists:
        for item in values:
            text = str(item or "").strip()
            if text and text not in merged:
                merged.append(text)
            if len(merged) >= limit:
                return merged
    return merged or list(fallback or [])


_COMPLEXITY_GAP_VALUES = frozenset(
    {"unknown", "worse_than_expected", "matches_expected", "better_than_expected"}
)


def _normalize_complexity_gap(value: Any) -> str:
    gap = str(value or "").strip()
    if gap in _COMPLEXITY_GAP_VALUES:
        return gap
    return "unknown"


def _complexity_gap(actual: str, expected: str) -> str:
    if not expected:
        return "unknown"
    if _rank(actual) > _rank(expected):
        return "worse_than_expected"
    if _rank(actual) < _rank(expected):
        return "better_than_expected"
    return "matches_expected"


def _normalize_algorithm_issues(issues: Any) -> list[dict[str, Any]]:
    if not isinstance(issues, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw in issues:
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description") or raw.get("message") or "").strip()
        suggested_fix = str(raw.get("suggested_fix") or raw.get("suggestion") or "").strip()
        if not description:
            continue
        issue = {
            "type": str(raw.get("type") or "algorithm_observation").strip() or "algorithm_observation",
            "description": description[:300],
            "severity": normalize_agent_severity(raw.get("severity")),
            "suggested_fix": suggested_fix[:300] or "Algoritma secimini ve karmasiklik hedefini odev beklentisine gore iyilestirin.",
        }
        line = raw.get("line")
        if isinstance(line, int) and line > 0:
            issue["line"] = line
        normalized.append(issue)
        if len(normalized) >= 8:
            break
    return normalized


def _dedupe_algorithm_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    for issue in issues:
        issue_type = str(issue.get("type") or "algorithm_observation").strip()
        line = issue.get("line")
        if issue_type in {"complexity_gap", "nested_loop"}:
            key = (issue_type, line if isinstance(line, int) else None)
        else:
            description = str(issue.get("description") or "").strip().lower()
            key = (issue_type, description[:120])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _build_programmatic_algorithm_result(source: str, language: str, brief: str) -> dict[str, Any]:
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

    data_structures = _detect_data_structures(source)
    expected = _expected_complexity_from_text(brief)
    gap = _complexity_gap(time_complexity, expected)
    issues: list[dict[str, Any]] = []
    if gap == "worse_than_expected":
        issues.append(
            {
                "type": "complexity_gap",
                "description": f"Cozum {time_complexity}; odev beklentisi {expected} gorunuyor.",
                "severity": "high",
                "suggested_fix": "Tekrarlayan taramalari dict/set tabanli tek gecis yaklasimina indirin.",
            }
        )

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

    detected_algorithms = _detect_algorithms(source, metrics.functions)
    return {
        "detected_algorithms": detected_algorithms,
        "data_structures": data_structures,
        "time_complexity": time_complexity,
        "space_complexity": "O(n)" if data_structures else "O(1)",
        "expected_complexity": expected,
        "complexity_gap": gap,
        "algorithm_analysis": (
            f"Tespit edilen yaklasim: {', '.join(detected_algorithms)}. "
            f"Programatik karmasiklik tahmini {time_complexity}."
        ),
        "data_structure_analysis": (
            f"Kullanilan veri yapilari: {', '.join(data_structures)}."
            if data_structures
            else "Belirgin ek veri yapisi kullanimi tespit edilmedi."
        ),
        "issues": issues,
        "score": score,
    }


def _merge_algorithm_results(programmatic: dict[str, Any], llm_result: dict[str, Any]) -> dict[str, Any]:
    actual = str(programmatic.get("time_complexity") or "O(1)")
    expected = str(programmatic.get("expected_complexity") or "")
    llm_expected = str(llm_result.get("expected_complexity") or "").strip()
    if not expected and llm_expected in _COMPLEXITY_RANK:
        expected = llm_expected
    gap = _complexity_gap(actual, expected)

    issues = _normalize_algorithm_issues(llm_result.get("issues"))
    programmatic_issues = _normalize_algorithm_issues(programmatic.get("issues"))
    if gap == "worse_than_expected" and not any(i.get("type") == "complexity_gap" for i in programmatic_issues):
        programmatic_issues.insert(
            0,
            {
                "type": "complexity_gap",
                "description": f"Cozum {actual}; odev beklentisi {expected} gorunuyor.",
                "severity": "high",
                "suggested_fix": "Algoritmayi beklenen karmasiklik sinirina indirin.",
            },
        )

    score = int(programmatic.get("score") or 0)
    if gap == "worse_than_expected":
        score = min(score, 55)

    merged = dict(llm_result)
    merged.update(
        {
            "detected_algorithms": _merge_str_lists(
                _safe_str_list(programmatic.get("detected_algorithms"), []),
                _safe_str_list(llm_result.get("detected_algorithms"), []),
                fallback=["general_iteration"],
            ),
            "data_structures": _merge_str_lists(
                _safe_str_list(programmatic.get("data_structures"), []),
                _safe_str_list(llm_result.get("data_structures"), []),
                fallback=[],
            ),
            "time_complexity": actual,
            "space_complexity": str(programmatic.get("space_complexity") or "O(1)"),
            "expected_complexity": expected,
            "complexity_gap": gap,
            "algorithm_analysis": str(
                llm_result.get("algorithm_analysis") or programmatic.get("algorithm_analysis") or ""
            ).strip(),
            "data_structure_analysis": str(
                llm_result.get("data_structure_analysis") or programmatic.get("data_structure_analysis") or ""
            ).strip(),
            "issues": _dedupe_algorithm_issues(programmatic_issues + issues)[:10],
            "score": score,
        }
    )
    return merged


def _apply_task_relevance_cap(result: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
    """Topic mismatch is graded by task relevance, not algorithm complexity alone."""
    task = input_data.get("task_alignment")
    if not isinstance(task, dict):
        return result

    off_topic = bool(task.get("llm_off_topic"))
    reasons = task.get("reasons") if isinstance(task.get("reasons"), list) else []
    try:
        capability = float(task.get("capability_match", 1.0) or 1.0)
    except (TypeError, ValueError):
        capability = 1.0
    try:
        factor = float(task.get("factor", 1.0) or 1.0)
    except (TypeError, ValueError):
        factor = 1.0

    hard_off = (
        off_topic
        or "deterministic_capability_mismatch" in reasons
        or "cross_domain_mismatch" in reasons
        or capability <= 0.24
    )
    capped = dict(result)
    score = int(capped.get("score") or 0)
    if hard_off:
        capped["score"] = min(score, 12)
        capped["complexity_gap"] = "unknown"
        issues = _normalize_algorithm_issues(capped.get("issues"))
        if not any(str(item.get("type")) == "task_mismatch" for item in issues):
            issues.insert(
                0,
                {
                    "type": "task_mismatch",
                    "description": "Kod odevin istedigi algoritma/gorev ile uyusmuyor; karmasiklik analizi ikincil.",
                    "severity": "high",
                    "suggested_fix": "Odev aciklamasindaki temel problemi dogrudan uygulayin.",
                },
            )
        capped["issues"] = issues[:10]
        return capped

    if factor < 0.45 or capability < 0.45:
        capped["score"] = min(score, 40)
    return capped


class AlgorithmAgent(BaseAgent):
    name = "algorithm"
    description = "Algoritma, veri yapisi ve karmasiklik analizi"

    def _pre_schema_normalize(self, result: dict, output_json_schema: dict | None) -> dict:
        if not isinstance(result, dict):
            return result
        normalized = dict(result)
        normalized["complexity_gap"] = _normalize_complexity_gap(normalized.get("complexity_gap"))
        normalized["issues"] = _normalize_algorithm_issues(normalized.get("issues"))
        normalized["detected_algorithms"] = _safe_str_list(
            normalized.get("detected_algorithms"),
            ["general_iteration"],
        )
        normalized["data_structures"] = _safe_str_list(
            normalized.get("data_structures"),
            [],
        )
        return normalized

    async def analyze(self, input_data: dict[str, Any]) -> dict[str, Any]:
        source = str(input_data.get("source_code") or "")
        language = str(input_data.get("language") or "python")
        brief = str(input_data.get("assignment_description") or "")
        programmatic = _build_programmatic_algorithm_result(source, language, brief)
        user_prompt = (
            "Analyze this submission's algorithmic behavior.\n"
            f"{format_assignment_context_for_prompt(brief)}\n"
            f"Language: {language}\n"
            f"Programmatic baseline (canonical guardrails): {json.dumps(programmatic, ensure_ascii=False)}\n"
            "Source code:\n"
            f"{source[:12000]}\n\n"
            "Return JSON with detected_algorithms, data_structures, time_complexity, space_complexity, "
            "expected_complexity, complexity_gap, algorithm_analysis, data_structure_analysis, issues, score. "
            "If code is more complex than expected, include a complexity_gap issue.\n"
            f"{build_llm_user_suffix(report_language=str(input_data.get('report_language') or 'tr'))}"
        )
        try:
            llm_result = await self._call_llm(
                system_prompt=_ALGORITHM_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                required_keys=_ALGORITHM_REQUIRED_KEYS,
                output_json_schema=ALGORITHM_OUTPUT_SCHEMA,
            )
        except LLMInferenceError as exc:
            return self._with_contract_metadata(
                _apply_task_relevance_cap({**programmatic, "llm_error": str(exc)[:300]}, input_data),
                llm_status="fallback",
                guardrail_flags=["llm_inference_fallback"],
            )

        return _apply_task_relevance_cap(_merge_algorithm_results(programmatic, llm_result), input_data)
