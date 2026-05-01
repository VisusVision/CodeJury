"""
Code Quality & Complexity Agent -- tam LLM: kalite ve karmasiklik yorumu Ollama ile.

AST metrikleri yalnizca prompt ipucu; bulgular ve skor LLM ciktisindan gelir (LLM zorunlu).

Girdi:  {"source_code": str, "language": str}
Cikti:  CodeQualityOutput dict
"""

import json

from backend.agents.base import BaseAgent, build_llm_user_suffix, format_assignment_context_for_prompt
from backend.agents.json_output_schema import CODE_QUALITY_OUTPUT_SCHEMA
from backend.agents.code_utils import get_code_metrics, strip_comments

_COMPLEXITY_RANK = {
    "O(1)": 0, "O(log n)": 1, "O(n)": 2, "O(n log n)": 3,
    "O(n^2)": 5, "O(n^2 log n)": 6, "O(n^3)": 7,
    "O(2^n)": 9, "O(n!)": 10, "O(recursive)": 4,
    "O(n * recursive)": 6,
}


def _complexity_rank(c: str) -> int:
    return _COMPLEXITY_RANK.get(c, 5)


def _worst_of(a: str, b: str) -> str:
    return a if _complexity_rank(a) >= _complexity_rank(b) else b


_KNOWN_ALGORITHMS: dict[str, int] = {
    "bubble_sort": 5, "kabarcik_siralama": 5, "kabarcik_sirala": 5,
    "selection_sort": 5, "secim_siralama": 5, "secim_sirala": 5,
    "insertion_sort": 5, "ekleme_siralama": 5, "ekleme_sirala": 5,
    "sirala": 5, "siralama": 5, "sort": 5, "sort_list": 5,
    "my_sort": 5, "custom_sort": 5,
    "merge_sort": 3, "birlestirme_siralama": 3,
    "quick_sort": 3, "hizli_siralama": 3,
    "heap_sort": 3,
    "binary_search": 1, "ikili_arama": 1,
    "linear_search": 2, "lineer_arama": 2, "dogrusal_arama": 2,
    "ara": 2, "arama": 2, "search": 2, "bul": 2,
    "inorder": 4, "preorder": 4, "postorder": 4, "levelorder": 4,
    "inorder_traversal": 4, "preorder_traversal": 4, "postorder_traversal": 4,
    "ekle": 4, "insert": 4, "sil": 4, "delete": 4, "remove": 4,
    "yukseklik": 4, "height": 4, "depth": 4, "derinlik": 4,
    "dugum_sayisi": 4, "node_count": 4, "size": 4, "boyut": 4,
    "minimum": 2, "maksimum": 2, "min_val": 2, "max_val": 2,
    "seviye_gezintisi": 4, "level_order": 4, "bfs": 4, "dfs": 4,
    "dengeli_mi": 4, "is_balanced": 4, "is_bst": 4,
    "mirror": 4, "ayna": 4, "invert": 4,
    "traverse": 4, "reverse": 4, "ters_cevir": 4,
    "fibonacci": 2, "factorial": 2, "faktoriyel": 2,
    "permutations": 10, "permutasyon": 10,
    "combinations": 10, "kombinasyon": 10,
    "power": 4, "us": 4, "gcd": 2, "ebob": 2,
    "hanoi": 4, "tower_of_hanoi": 4,
}

_RECURSIVE_KEYWORDS = frozenset({
    "recursive", "rec", "helper", "yardimci",
    "inorder", "preorder", "postorder", "levelorder",
    "traverse", "traversal", "gezinti", "gezintisi",
    "dugum", "node", "agac", "tree", "bst", "ikili", "kok", "root",
    "sol", "sag", "left", "right",
    "ekle", "insert", "sil", "delete",
    "ara", "arama", "search", "bul", "find",
    "yukseklik", "height", "depth", "derinlik",
    "sayisi", "count", "size", "boyut",
    "dengeli", "balanced", "mirror", "ayna", "invert",
    "visit",
})

_RECURSION_EXPECTED_COMPLEXITY = frozenset({"O(recursive)", "O(n * recursive)"})

_SYSTEM_PROMPT = """\
You are an expert code quality and complexity analyst. The entire assessment must follow from
your own reading of the code. The static hints in the user message are non-binding;
final Big-O, issue list, narratives, and score must reflect independent judgment.

Required focus areas (each MUST be reflected somewhere in your output):
- Algorithm choice: is the chosen algorithm appropriate for the task and input size?
- Data structures: are list/dict/set/heap/tree picks justified vs. alternatives?
- Big-O: time AND space complexity, expressed in proper Big-O notation.
- Redundant or nested loops, repeated work that could be memoized.
- Unoptimized lookups (linear scan where a dict/set lookup would be O(1)).
- Architectural mistakes that can cause memory growth or leaks (unbounded global
  caches, lists that accumulate without reset, holding references to closed
  resources, recursive calls without depth control, etc.).
- Mention any of these concerns explicitly inside "issues" or in the analysis
  fields when present. If genuinely none apply, say so in the analysis text.

Rules:
- Score must be an integer from 0 to 100.
- Each item in "issues": {"type": str, "description": str, "severity": "low"|"medium"|"high"|"critical", "suggested_fix": str, "line": int (optional)}
- Prefer the canonical "type" labels when applicable (use them verbatim):
  high_complexity, redundant_loop, unoptimized_lookup, memory_leak,
  unbounded_recursion, magic_number, long_function, dead_code,
  premature_optimization, copy_in_loop, n_plus_one, expected_complexity.
- If none of the canonical labels fit, use a short snake_case label of your own.
- Do not heavily penalize standard algorithms (sorting, tree traversals, etc.) for expected recursion or O(n^2) where appropriate.
- If an ASSIGNMENT BRIEF block requires a specific deliverable (e.g. factorial, Fibonacci) and the
  source clearly implements a different domain (e.g. library management, unrelated OOP app),
  the score must be very low (roughly 0–30). Explain this as **task / brief mismatch** in
  algorithm_analysis — do **not** frame it as generic Big-O failure unless complexity is genuinely
  the main problem for the stated task.
- "time_complexity" and "space_complexity" must use Big-O notation.

Reply with ONLY this JSON shape, no other text:
{
  "time_complexity": "O(...)",
  "space_complexity": "O(...)",
  "algorithm_analysis": "...",
  "data_structure_analysis": "...",
  "issues": [...],
  "score": 0-100
}
"""


def _is_known_recursive(fn_name: str) -> bool:
    clean = fn_name.lstrip("_")
    if clean in _KNOWN_ALGORITHMS:
        return True
    parts = clean.lower().split("_")
    return bool(set(parts) & _RECURSIVE_KEYWORDS)


class CodeQualityAgent(BaseAgent):
    name = "code_quality"
    description = "Kod kalitesi ve karmasiklik analizi"

    async def analyze(self, input_data: dict) -> dict:
        source_code = input_data["source_code"]
        language = input_data.get("language", "python")
        report_language = input_data.get("report_language") or "tr"

        # --- Programatik on-analiz ---
        programmatic = self._programmatic_analysis(source_code, language)

        # --- LLM zenginlestirme ---
        truncated = self._truncate_code(source_code)
        summary = {
            "static_time_guess": programmatic["time_complexity"],
            "static_space_guess": programmatic["space_complexity"],
            "static_issue_count": len(programmatic["issues"]),
            "static_top_issues": [
                {"type": i["type"], "severity": i["severity"], "desc": i["description"][:80]}
                for i in programmatic["issues"][:4]
            ],
        }
        brief = format_assignment_context_for_prompt(input_data.get("assignment_description"))
        user_prompt = (
            f"Code (language tag: {language}):\n```\n{truncated}\n```\n"
            f"{brief}"
            f"Non-binding heuristic hints (AST/metrics):\n{json.dumps(summary, ensure_ascii=False, separators=(',',':'))}\n"
            "Task: From the code, produce time_complexity, space_complexity, algorithm_analysis, "
            "data_structure_analysis, issues, and score."
            f"{build_llm_user_suffix(report_language=report_language)}"
        )

        llm_result = await self._call_llm(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            required_keys=["time_complexity", "score"],
            output_json_schema=CODE_QUALITY_OUTPUT_SCHEMA,
        )

        llm_result["score"] = self._safe_int(llm_result.get("score"), 50)
        if not isinstance(llm_result.get("issues"), list):
            llm_result["issues"] = []

        return llm_result

    def _programmatic_analysis(self, source_code: str, language: str) -> dict:
        """Programatik metrikler -- yalnizca LLM prompt ipucu."""
        clean_code = strip_comments(source_code, language)
        metrics = get_code_metrics(clean_code, language)

        issues = []
        penalty = 0
        has_syntax_error = any(
            ap["type"] == "syntax_error" for ap in metrics.antipatterns
        )

        worst_complexity = "O(1)"
        worst_non_algo = "O(1)"

        complexity_penalty = 0
        for fn in metrics.functions:
            worst_complexity = _worst_of(worst_complexity, fn.complexity)

            fn_rank = _complexity_rank(fn.complexity)
            clean_name = fn.name.lstrip("_")
            expected_rank = _KNOWN_ALGORITHMS.get(clean_name, _KNOWN_ALGORITHMS.get(fn.name, -1))
            is_known = expected_rank >= 0 or _is_known_recursive(fn.name)

            if not is_known:
                worst_non_algo = _worst_of(worst_non_algo, fn.complexity)

            if (
                fn_rank > _complexity_rank("O(n)")
                and fn.complexity not in _RECURSION_EXPECTED_COMPLEXITY
                and not is_known
            ):
                issues.append({
                    "type": "high_complexity",
                    "line": fn.line,
                    "description": (
                        f"{fn.name}() fonksiyonu {fn.complexity} karmasikliga sahip "
                        f"(satir {fn.line}-{fn.end_line}). "
                        f"{fn.nested_loops} ic ice dongu tespit edildi."
                    ),
                    "severity": "high" if fn_rank >= 5 else "medium",
                    "suggested_fix": "Ic donguyu hash map (dict/set) ile O(1) lookup'a cevirin.",
                })
                complexity_penalty += 12
            elif (
                fn_rank > _complexity_rank("O(n)")
                and fn.complexity not in _RECURSION_EXPECTED_COMPLEXITY
                and is_known
            ):
                issues.append({
                    "type": "expected_complexity",
                    "line": fn.line,
                    "description": (
                        f"{fn.name}() fonksiyonu {fn.complexity} karmasikliga sahip "
                        f"-- bu algoritma icin beklenen karmasiklik."
                    ),
                    "severity": "info",
                    "suggested_fix": "Algoritmanin dogasi geregi. Puan dusulmedi.",
                })

            if (
                fn.uses_recursion
                and not is_known
                and fn.complexity not in _RECURSION_EXPECTED_COMPLEXITY
            ):
                issues.append({
                    "type": "recursion_detected",
                    "line": fn.line,
                    "description": f"{fn.name}() fonksiyonu recursive. Stack overflow riski var (satir {fn.line}).",
                    "severity": "medium",
                    "suggested_fix": "Iteratif cozum kullanmayi dusunun veya derinlik limiti ekleyin.",
                })
                complexity_penalty += 5
            elif (
                fn.uses_recursion
                and is_known
                and fn.complexity not in _RECURSION_EXPECTED_COMPLEXITY
            ):
                issues.append({
                    "type": "expected_recursion",
                    "line": fn.line,
                    "description": f"{fn.name}() recursive -- bu algoritma icin standart yaklasim.",
                    "severity": "info",
                    "suggested_fix": "Algoritmanin dogasi geregi.",
                })

        penalty += min(complexity_penalty, 30)

        ap_penalty = 0
        for ap in metrics.antipatterns:
            issues.append({
                "type": ap["type"],
                "line": ap["line"],
                "description": f"Satir {ap['line']}: {ap['description']}",
                "severity": ap["severity"],
                "suggested_fix": _get_fix_suggestion(ap["type"]),
            })
            p = {"critical": 20, "high": 10, "medium": 5, "low": 2,
                 "suggestion": 0, "info": 0}.get(ap["severity"], 0)
            ap_penalty += p

        penalty += min(ap_penalty, 35)

        long_fn_penalty = 0
        for fn in metrics.functions:
            if fn.length > 25:
                issues.append({
                    "type": "long_function",
                    "line": fn.line,
                    "description": (
                        f"{fn.name}() {fn.length} satir (satir {fn.line}-{fn.end_line}). "
                        "Tek sorumluluk prensibine aykiri."
                    ),
                    "severity": "medium",
                    "suggested_fix": "Fonksiyonu daha kucuk yardimci fonksiyonlara bolun.",
                })
                long_fn_penalty += 5
        penalty += min(long_fn_penalty, 15)

        if not metrics.functions and metrics.code_lines > 5:
            issues.append({
                "type": "no_functions",
                "description": "Kod fonksiyonlara ayrilmamis. Tamamiyla prosedural yazi.",
                "severity": "high",
                "suggested_fix": "Mantiksal bloklari fonksiyonlara ayirin.",
            })
            penalty += 15

        if not metrics.functions and metrics.loop_patterns:
            max_nest = metrics.max_nesting_depth
            if max_nest >= 2:
                worst_complexity = _worst_of(worst_complexity, f"O(n^{max_nest})")
                issues.append({
                    "type": "nested_loops_global",
                    "description": f"{max_nest} seviye ic ice dongu tespit edildi (fonksiyon disi).",
                    "severity": "high",
                    "suggested_fix": "Ic donguyu optimize edin.",
                })
                penalty += 12
            elif max_nest == 1:
                worst_complexity = _worst_of(worst_complexity, "O(n)")

        bonus = 0
        if metrics.functions:
            bonus += 8
            if all(f.length <= 20 for f in metrics.functions):
                bonus += 4
        severe_issues = [i for i in issues if i["severity"] in ("high", "critical")]
        if not severe_issues:
            bonus += 8

        score = 80 - penalty + bonus
        floor = 5 if has_syntax_error else 22

        reported_complexity = worst_non_algo if worst_non_algo != "O(1)" else worst_complexity
        if metrics.functions and reported_complexity == "O(1)":
            non_algo_fns = [fn for fn in metrics.functions if fn.name not in _KNOWN_ALGORITHMS]
            if non_algo_fns:
                reported_complexity = max(
                    (fn.complexity for fn in non_algo_fns),
                    key=_complexity_rank,
                    default="O(1)",
                )
            else:
                reported_complexity = worst_complexity

        space_items = sum(1 for imp in metrics.imports if "collections" in imp or "numpy" in imp)
        space_complexity = "O(n)" if metrics.functions or space_items > 0 else "O(1)"

        algo_text = _build_algorithm_analysis(metrics, issues)
        ds_text = _build_ds_analysis(metrics)

        final_score = int(max(floor, min(100, round(score))))
        return {
            "time_complexity": reported_complexity,
            "space_complexity": space_complexity,
            "algorithm_analysis": algo_text,
            "data_structure_analysis": ds_text,
            "issues": issues,
            "score": final_score,
        }


def _get_fix_suggestion(ap_type: str) -> str:
    suggestions = {
        "range_len": "enumerate() kullanin: for i, item in enumerate(lst)",
        "bare_except": "Spesifik exception kullanin: except ValueError as e:",
        "mutable_default": "None kullanip fonksiyon icinde olusturun: if arg is None: arg = []",
        "global_keyword": "Fonksiyon parametresi veya sinif kullanin.",
        "syntax_error": "Syntax hatasini duzeltin.",
        "eq_true_false": "'== True' yerine direkt kosul, '== False' yerine 'not' kullanin.",
        "string_concat_loop": "Liste olusturup ''.join(lst) kullanin.",
    }
    return suggestions.get(ap_type, "Kodu refactor edin.")


def _build_algorithm_analysis(metrics, issues) -> str:
    parts = []
    if metrics.functions:
        for fn in metrics.functions:
            parts.append(f"{fn.name}(): {fn.complexity}")
    high_issues = [i for i in issues if i["severity"] in ("high", "critical")]
    if high_issues:
        parts.append(f"{len(high_issues)} ciddi sorun tespit edildi.")
    if not parts:
        parts.append("Belirgin algoritmik sorun tespit edilmedi.")
    return " | ".join(parts)


def _build_ds_analysis(metrics) -> str:
    if not metrics.functions and not metrics.imports:
        return "Temel veri yapilari kullanilmis."
    advanced = [f for f in metrics.modern_features
                if f in ("collections_usage", "set_comprehension", "dict_comprehension")]
    if advanced:
        return f"Ileri veri yapilari kullanilmis: {', '.join(advanced)}"
    return "Standart veri yapilari kullanilmis. Set/dict ile optimize edilebilir."
