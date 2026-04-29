"""
Seniority Agent -- tam LLM: kidem/yetkinlik degerlendirmesi Ollama ile.

Programatik metrikler yalnizca prompt ipucu (LLM zorunlu).

Girdi:  {"source_code": str, "language": str}
Cikti:  SeniorityOutput dict
"""

import json

from backend.agents.base import BaseAgent, build_llm_user_suffix, format_assignment_context_for_prompt
from backend.agents.code_utils import get_code_metrics, strip_comments

_SENIORITY_SYSTEM_PROMPT = """\
You are an expert at estimating developer skill level from code. Junior / mid / senior and the
score must follow your independent judgment. Heuristic lines are hints only.

What "modern_features_usage" should cover (when applicable to the language):
- Modern memory / resource management: context managers (with-statement / RAII),
  generators, weakref, smart pointers, automatic move semantics — anything that
  prevents leaks or dangling references.
- Ownership / scope discipline: no leaky globals, no mutable default arguments,
  clean separation of state vs. behaviour, immutability where reasonable.
- Advanced synchronization tools when relevant: threading.Lock / RLock / Event /
  Queue, asyncio primitives, multiprocessing, std::mutex / std::atomic,
  concurrent collections, etc.
- Idiomatic modern syntax: comprehensions, f-strings, dataclasses/records,
  pattern matching, type hints / generics, async/await, decorators.

Rules:
- estimated_level: "junior"|"mid"|"senior"
- error_handling_quality, abstraction_quality: "poor"|"fair"|"good"|"excellent"
- maturity_indicators: concrete signs of maturity you observed in this code
- immaturity_indicators: concrete signs of inexperience you observed
- Score 0–100; be fair: simple but correct code is not automatically "junior".
- modern_features_usage must be a sentence or two that names the specific
  features you saw (or explicitly says they are missing).

Reply with ONLY this JSON shape:
{
  "estimated_level": "junior|mid|senior",
  "modern_features_usage": "...",
  "error_handling_quality": "poor|fair|good|excellent",
  "abstraction_quality": "poor|fair|good|excellent",
  "design_patterns": [],
  "maturity_indicators": [],
  "immaturity_indicators": [],
  "idiomatic_usage_score": 0-100,
  "score": 0-100
}
"""


class SeniorityAgent(BaseAgent):
    name = "seniority"
    description = "Kidem ve yetkinlik seviyesi degerlendirmesi"

    async def analyze(self, input_data: dict) -> dict:
        source_code = input_data["source_code"]
        language = input_data.get("language", "python")
        report_language = input_data.get("report_language") or "tr"

        programmatic = self._programmatic_analysis(source_code, language)

        truncated = self._truncate_code(source_code)
        summary = {
            "static_level_hint": programmatic["estimated_level"],
            "error_handling": programmatic["error_handling_quality"],
            "abstraction": programmatic["abstraction_quality"],
            "maturity": programmatic["maturity_indicators"][:5],
            "immaturity": programmatic["immaturity_indicators"][:5],
            "patterns": programmatic.get("design_patterns", []),
        }
        brief = format_assignment_context_for_prompt(input_data.get("assignment_description"))
        user_prompt = (
            f"Code (language tag: {language}):\n```\n{truncated}\n```\n"
            f"{brief}"
            f"Non-binding heuristic hints:\n{json.dumps(summary, ensure_ascii=False, separators=(',',':'))}\n"
            "Task: Produce estimated_level, quality fields, indicators, and score."
            f"{build_llm_user_suffix(report_language=report_language)}"
        )

        llm_result = await self._call_llm(
            system_prompt=_SENIORITY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            required_keys=["estimated_level", "score"],
        )

        llm_result["score"] = self._safe_int(llm_result.get("score"), 50)
        if "idiomatic_usage_score" in llm_result:
            llm_result["idiomatic_usage_score"] = self._safe_int(
                llm_result["idiomatic_usage_score"], llm_result["score"]
            )

        return llm_result

    def _programmatic_analysis(self, source_code: str, language: str) -> dict:
        clean_code = strip_comments(source_code, language)
        metrics = get_code_metrics(clean_code, language)

        score = 35
        maturity = []
        immaturity = []

        if metrics.functions:
            maturity.append(f"Kod {len(metrics.functions)} fonksiyona ayrilmis")
            score += 10
            if all(f.length <= 20 for f in metrics.functions):
                maturity.append("Tum fonksiyonlar makul uzunlukta")
                score += 5
        else:
            if metrics.code_lines > 10:
                immaturity.append("Fonksiyon kullanilmamis, duz script")
                score -= 10

        typed_fns = sum(1 for f in metrics.functions if f.has_type_hints)
        if typed_fns > 0:
            maturity.append(f"Type hint kullanimi mevcut ({typed_fns}/{len(metrics.functions)} fonksiyonda)")
            score += 10
        elif metrics.functions:
            immaturity.append("Hicbir fonksiyonda type hint yok")
            score -= 3

        ret_fns = sum(1 for f in metrics.functions if f.has_return_annotation)
        if ret_fns > 0:
            maturity.append(f"Return annotation ({ret_fns}/{len(metrics.functions)} fonksiyonda)")
            score += 5

        doc_fns = sum(1 for f in metrics.functions if f.has_docstring)
        if doc_fns > 0:
            maturity.append(f"Docstring mevcut ({doc_fns}/{len(metrics.functions)} fonksiyonda)")
            score += 8
        elif metrics.functions:
            immaturity.append("Hicbir fonksiyonda docstring yok")
            score -= 2

        if metrics.modern_features:
            maturity.append(f"Modern ozellikler: {', '.join(metrics.modern_features)}")
            score += 3 * min(len(metrics.modern_features), 5)

        for ap in metrics.antipatterns:
            immaturity.append(f"Anti-pattern: {ap['description']} (satir {ap['line']})")
            score -= 4

        if metrics.max_nesting_depth > 3:
            immaturity.append(f"Cok derin ic ice yapi ({metrics.max_nesting_depth} seviye)")
            score -= 10
        elif metrics.max_nesting_depth > 2:
            immaturity.append(f"Yuksek ic ice derinlik ({metrics.max_nesting_depth} seviye)")
            score -= 5

        has_error_handling = "try" in source_code and ("except" in source_code or "catch" in source_code)
        if has_error_handling:
            maturity.append("Hata yonetimi mevcut (try/except)")
            score += 8

        if metrics.has_main_guard:
            maturity.append("if __name__ == '__main__' korumasi var")
            score += 5

        if metrics.classes:
            maturity.append(f"OOP: {len(metrics.classes)} sinif tanimlanmis")
            score += 8

        advanced = (
            _detect_advanced_features(source_code)
            if language.lower() in ("python", "py")
            else []
        )
        for feat in advanced:
            maturity.append(feat)
            score += 3

        score = max(22, min(100, score))
        if score <= 35:
            level = "junior"
        elif score <= 60:
            level = "mid"
        else:
            level = "senior"

        error_q = "good" if has_error_handling else "poor"
        abstraction_q = "poor"
        if metrics.functions and metrics.classes:
            abstraction_q = "good"
        elif metrics.functions:
            abstraction_q = "fair"

        if metrics.modern_features:
            modern_text = f"Kullanilan modern ozellikler: {', '.join(metrics.modern_features)}"
        else:
            modern_text = "Modern dil ozellikleri kullanilmamis (comprehension, f-string, type hints vb.)"

        design_patterns = []
        if metrics.classes and any(f.name == "__init__" for f in metrics.functions):
            design_patterns.append("OOP / Encapsulation")
        if metrics.has_main_guard:
            design_patterns.append("Module pattern (main guard)")
        if "@staticmethod" in source_code or "@classmethod" in source_code:
            design_patterns.append("Static/Class method pattern")
        if "abc.ABC" in source_code or "ABC)" in source_code:
            design_patterns.append("Abstract Base Class")

        return {
            "estimated_level": level,
            "modern_features_usage": modern_text,
            "error_handling_quality": error_q,
            "abstraction_quality": abstraction_q,
            "design_patterns": design_patterns,
            "maturity_indicators": maturity,
            "immaturity_indicators": immaturity,
            "idiomatic_usage_score": max(0, min(100, score - 5)),
            "score": score,
        }


def _detect_advanced_features(source: str) -> list[str]:
    """Metin tabanli ileri ozellik ipuclari (basit substring kontrolleri)."""
    feats: list[str] = []
    if "@property" in source:
        feats.append("@property decorator kullanimi")
    if "def __repr__" in source:
        feats.append("__repr__ tanimlanmis (debug-friendly)")
    if "def __str__" in source:
        feats.append("__str__ tanimlanmis")
    if "__all__" in source:
        feats.append("__all__ export listesi tanimlanmis")
    if "yield " in source or "yield\n" in source:
        feats.append("Generator (yield) kullanimi")
    if "with open(" in source:
        feats.append("Context manager ile dosya islemleri")
    if "logging." in source or "import logging" in source:
        feats.append("logging modulu kullanimi (print yerine)")
    if "pathlib" in source or "Path(" in source:
        feats.append("pathlib kullanimi (os.path yerine)")
    if "from functools import" in source or "import functools" in source:
        feats.append("functools decorator kullanimi")
    if "@dataclass" in source or "dataclasses" in source:
        feats.append("dataclass kullanimi")
    if "def __enter__" in source or "def __exit__" in source:
        feats.append("Custom context manager (__enter__/__exit__)")
    return feats
