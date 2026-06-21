"""
Guideline Agent -- tam LLM: stil ve rehber uyumu Ollama ile.

Programatik tespitler yalnizca prompt ipucu (LLM zorunlu).

Girdi:  {"source_code": str, "language": str}
Cikti:  GuidelineOutput dict
"""

import json
import re
from typing import Any

from backend.agents.base import BaseAgent, build_llm_user_suffix, format_assignment_context_for_prompt
from backend.agents.code_utils import get_code_metrics, strip_comments
from backend.agents.json_output_schema import GUIDELINE_OUTPUT_SCHEMA


def _python_main_guard_line_nums(lines: list[str]) -> frozenset[int]:
    """1-based satirlar: `if __name__ == '__main__'` blogu (demo verisi / print — agir ceza olmasin)."""
    result: list[int] = []
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        indent = len(lines[i]) - len(lines[i].lstrip())
        if re.match(r'if\s+__name__\s*==\s*["\']__main__["\']\s*:', stripped):
            main_indent = indent
            i += 1
            while i < n:
                raw = lines[i]
                st = raw.strip()
                ind = len(raw) - len(raw.lstrip())
                if not st or st.startswith("#"):
                    i += 1
                    continue
                if ind <= main_indent:
                    break
                result.append(i + 1)
                i += 1
            continue
        i += 1
    return frozenset(result)


_GUIDELINE_SYSTEM_PROMPT = """\
You are an expert on coding standards and style. The assessment must follow from your reading
of the code. Heuristic hints in the user message are non-binding.

Apply the right style guide based on the language tag in the user message:
- python  -> PEP 8 (layout) + PEP 257 (docstrings) + PEP 484 (type hints).
- cpp / c++ -> Google C++ Style Guide.
- java   -> Google Java Style Guide.
- js / ts -> Airbnb / Standard / Prettier conventions, semicolons, naming.
- Other languages -> mention which style guide you reference.

What you must inspect:
- Clean code principles: meaningful names, small focused functions, single
  responsibility, no dead code, comments that explain "why" not "what".
- Naming: snake_case / PascalCase / camelCase per language; banishing one-letter
  variables outside short loops; consistent prefixes/suffixes.
- Documentation sufficiency: module/class/function docstrings or doc-comments,
  parameter/return descriptions when the signature is non-trivial.
- Layout: max line length, indentation, import order, trailing whitespace,
  blank-line conventions.
- DRY violations and obvious anti-patterns.

Rules:
- naming_quality, documentation_quality: "poor"|"fair"|"good"|"excellent"
- Each style_violation: {"rule": str, "description": str, "line_hint": str, "severity": "low"|"medium"|"high"}
- Missing docstrings / type hints in student homework are common — do not treat them as severe.
- Keep this agent in its lane: evaluate style, naming, documentation, and clean-code
  structure. Do not grade algorithmic efficiency, task relevance, runtime success, or
  security except when a style rule directly exposes the problem.
- Every violation must point to a concrete line_hint or say "whole file" only for
  file-level facts such as no functions, no docstrings, or globally inconsistent naming.
- Avoid duplicate violations for the same root cause; group repeated naming/docstring
  issues when that is clearer for a teacher.
- JSON keys MUST be exactly: naming_quality, documentation_quality, clean_code_score, style_guide_compliance,
  style_violations, has_docstrings, has_type_hints, function_length_ok, nesting_depth_ok, dry_violations, score
  (English snake_case). All required for a valid reply.

Reply with ONLY this JSON shape:
{
  "naming_quality": "poor|fair|good|excellent",
  "documentation_quality": "poor|fair|good|excellent",
  "clean_code_score": 0-100,
  "style_guide_compliance": "...",
  "style_violations": [...],
  "has_docstrings": true|false,
  "has_type_hints": true|false,
  "function_length_ok": true|false,
  "nesting_depth_ok": true|false,
  "dry_violations": [],
  "score": 0-100
}
"""


_ALLOWED_Q = frozenset({"poor", "fair", "good", "excellent"})
_FILE_EXT_PATTERN = re.compile(
    r"""['"][^'"]+\.(csv|txt|json|log|xml|yaml|yml)['"]""",
    re.IGNORECASE,
)
_QUOTED_IDENTIFIER = re.compile(r"""['"`]([A-Za-z_]\w*)['"`]""")


def _looks_like_snake_case(name: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9_]*$", name or ""))


class GuidelineAgent(BaseAgent):
    name = "guideline"
    description = "Kodlama standartlari ve stil kontrolu"

    async def analyze(self, input_data: dict) -> dict:
        source_code = input_data["source_code"]
        language = input_data.get("language", "python")
        report_language = input_data.get("report_language") or "tr"

        programmatic = self._programmatic_analysis(source_code, language)

        truncated = self._truncate_code(source_code)
        summary = {
            "naming": programmatic["naming_quality"],
            "docs": programmatic["documentation_quality"],
            "has_docstrings": programmatic["has_docstrings"],
            "has_type_hints": programmatic["has_type_hints"],
            "fn_length_ok": programmatic["function_length_ok"],
            "nesting_ok": programmatic["nesting_depth_ok"],
            "violation_count": len(programmatic["style_violations"]),
            "top_violations": [
                {"rule": v["rule"], "severity": v["severity"], "desc": v["description"][:60]}
                for v in programmatic["style_violations"][:4]
            ],
        }
        brief = format_assignment_context_for_prompt(input_data.get("assignment_description"))
        user_prompt = (
            f"Code (language tag: {language}):\n```\n{truncated}\n```\n"
            f"{brief}"
            f"Non-binding heuristic hints:\n{json.dumps(summary, ensure_ascii=False, separators=(',',':'))}\n"
            "Task: Produce naming/documentation fields, style observations, violations, and score."
            f"{build_llm_user_suffix(report_language=report_language)}"
        )

        llm_result = await self._call_llm(
            system_prompt=_GUIDELINE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            required_keys=[
                "naming_quality",
                "documentation_quality",
                "clean_code_score",
                "style_guide_compliance",
                "style_violations",
                "has_docstrings",
                "has_type_hints",
                "function_length_ok",
                "nesting_depth_ok",
                "dry_violations",
                "score",
            ],
            output_json_schema=GUIDELINE_OUTPUT_SCHEMA,
        )
        if not isinstance(llm_result, dict):
            llm_result = {}

        merged = self._merge_llm_with_programmatic(llm_result, programmatic)

        merged["score"] = self._safe_int(merged.get("score"), programmatic["score"])
        if "clean_code_score" in merged:
            merged["clean_code_score"] = self._safe_int(
                merged["clean_code_score"], merged["score"]
            )

        if not isinstance(merged.get("style_violations"), list):
            merged["style_violations"] = list(programmatic.get("style_violations") or [])

        return merged

    @staticmethod
    def _coerce_quality(value: Any, fallback: str) -> str:
        if isinstance(value, str):
            v = value.strip().lower()
            if v in _ALLOWED_Q:
                return v
        return fallback if fallback in _ALLOWED_Q else "fair"

    @classmethod
    def _merge_llm_with_programmatic(cls, llm: dict[str, Any], prog: dict[str, Any]) -> dict[str, Any]:
        """LLM alanlari eksik / yanlis formatta olabilir; programatik ipucu ile tamamla."""
        out: dict[str, Any] = {**llm}
        out["naming_quality"] = cls._coerce_quality(out.get("naming_quality"), prog["naming_quality"])
        out["documentation_quality"] = cls._coerce_quality(
            out.get("documentation_quality"),
            prog.get("documentation_quality", "fair"),
        )
        raw_score = out.get("score")
        score_ok = False
        if raw_score is not None:
            try:
                float(raw_score)
                score_ok = True
            except (TypeError, ValueError):
                pass
        if not score_ok:
            out["score"] = prog["score"]
        ccs = out.get("clean_code_score")
        ccs_ok = False
        if ccs is not None:
            try:
                float(ccs)
                ccs_ok = True
            except (TypeError, ValueError):
                pass
        if not ccs_ok:
            out["clean_code_score"] = prog.get("clean_code_score", prog["score"])
        if not isinstance(out.get("style_guide_compliance"), str) or not str(out.get("style_guide_compliance")).strip():
            out["style_guide_compliance"] = prog.get("style_guide_compliance", "")
        for key in ("has_docstrings", "has_type_hints", "function_length_ok", "nesting_depth_ok"):
            if key not in out or not isinstance(out[key], bool):
                out[key] = bool(prog.get(key, False))
        if not isinstance(out.get("dry_violations"), list):
            out["dry_violations"] = list(prog.get("dry_violations") or [])
        out["style_violations"] = cls._filter_style_violations(out.get("style_violations"))
        return out

    @staticmethod
    def _filter_style_violations(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        filtered: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            desc = str(item.get("description") or item.get("rule") or "").strip()
            desc_l = desc.lower()
            # LLMs occasionally praise snake_case while emitting it as a warning.
            if "snake_case kullan" in desc_l and "yerine" in desc_l:
                continue
            if _FILE_EXT_PATTERN.search(desc) and any(
                token in desc_l
                for token in ("pascalcase", "camelcase", "snake_case", "naming", "isimlendirme")
            ):
                continue
            quoted = _QUOTED_IDENTIFIER.findall(desc)
            if quoted and "snake_case" in desc_l and all(_looks_like_snake_case(name) for name in quoted):
                continue
            if "snake_case" in desc_l:
                snake_refs = [
                    token
                    for token in re.findall(r"\b([a-z][a-z0-9_]{2,})\b", desc_l)
                    if token not in {"snake_case", "fonksiyon", "degisken", "kullan", "kullanin", "tercih"}
                ]
                if snake_refs and all(_looks_like_snake_case(name) for name in snake_refs):
                    continue
            filtered.append(item)
        return filtered

    def _programmatic_analysis(self, source_code: str, language: str) -> dict:
        clean_code = strip_comments(source_code, language)
        metrics = get_code_metrics(clean_code, language)
        lines = source_code.splitlines()
        demo_lines = (
            _python_main_guard_line_nums(lines)
            if language.lower() in ("python", "py")
            else frozenset()
        )

        violations = []
        score = 80
        dry_violations = []

        style_guide = {
            "python": "PEP 8", "cpp": "Google C++ Style Guide", "java": "Google Java Style Guide"
        }.get(language.lower(), "Genel")

        fns_no_doc = [f for f in metrics.functions if not f.has_docstring]
        has_docs = len(fns_no_doc) == 0 and len(metrics.functions) > 0

        if fns_no_doc:
            sample = ", ".join(f"{f.name}@{f.line}" for f in fns_no_doc[:5])
            if len(fns_no_doc) > 5:
                sample += ", ..."
            violations.append({
                "rule": "PEP257 - Docstring eksik",
                "description": (
                    f"{len(fns_no_doc)} fonksiyonda docstring yok (ogrenci odevleri icin zorunlu degil)."
                ),
                "line_hint": sample,
                "severity": "info",
            })
            score -= min(len(fns_no_doc), 3)

        has_hints = metrics.has_type_hints
        if not has_hints and metrics.functions:
            fns_no_hints = [f for f in metrics.functions if not f.has_type_hints]
            if fns_no_hints:
                violations.append({
                    "rule": "PEP484 - Type hints eksik",
                    "description": (
                        f"{len(fns_no_hints)} fonksiyonda type hint yok (zorunlu degil; "
                        "ileri seviye icin onerilir)."
                    ),
                    "line_hint": ", ".join(f"Satir {f.line}" for f in fns_no_hints[:5]),
                    "severity": "info",
                })
                score -= 3

        long_fns = [f for f in metrics.functions if f.length > 20]
        fn_length_ok = len(long_fns) == 0
        for fn in long_fns:
            violations.append({
                "rule": "Clean Code - Uzun fonksiyon",
                "description": f"{fn.name}() {fn.length} satir (satir {fn.line}-{fn.end_line}). Max 20 satir onerilir.",
                "line_hint": f"Satir {fn.line}",
                "severity": "medium",
            })
            score -= 4

        nesting_ok = metrics.max_nesting_depth <= 3
        if not nesting_ok:
            deep_loops = [lp for lp in metrics.loop_patterns if lp["nesting_level"] >= 2]
            violations.append({
                "rule": "Clean Code - Derin ic ice yapi",
                "description": f"Max derinlik {metrics.max_nesting_depth}. 3'ten fazla okunabilirligi dusurur.",
                "line_hint": ", ".join(f"Satir {lp['line']}" for lp in deep_loops[:5]),
                "severity": "high",
            })
            score -= 10

        naming = _check_naming(metrics, lines, language)
        if naming["violations"]:
            violations.extend(naming["violations"])
            score -= 2 * min(len(naming["violations"]), 5)

        if not metrics.functions and metrics.code_lines > 10:
            violations.append({
                "rule": "Clean Code - Kod organizasyonu",
                "description": "Kod fonksiyonlara ayrilmamis, duz script yapisi.",
                "line_hint": "Tum dosya",
                "severity": "high",
            })
            score -= 12

        long_lines = [
            (i + 1, len(line))
            for i, line in enumerate(lines)
            if len(line) > 99 and (i + 1) not in demo_lines
        ]
        if long_lines:
            violations.append({
                "rule": f"{style_guide} - Uzun satir",
                "description": f"{len(long_lines)} satir 99 karakterden uzun",
                "line_hint": ", ".join(f"Satir {l[0]} ({l[1]} kar.)" for l in long_lines[:5]),
                "severity": "low",
            })
            score -= 1

        long_in_demo = [
            (i + 1, len(line))
            for i, line in enumerate(lines)
            if len(line) > 99 and (i + 1) in demo_lines
        ]
        if long_in_demo and not long_lines:
            violations.append({
                "rule": f"{style_guide} - Uzun satir (demo blogu)",
                "description": f"{len(long_in_demo)} satir __main__ icinde 99+ karakter (genelde ornek veri).",
                "line_hint": ", ".join(f"Satir {l[0]}" for l in long_in_demo[:3]),
                "severity": "info",
            })

        for dup in metrics.duplicate_lines:
            dry_violations.append(
                f"Satir {dup['first_line']} ve {dup['duplicate_line']}: '{dup['code']}'"
            )
        if dry_violations:
            score -= 3 * min(len(dry_violations), 5)

        for ap in metrics.antipatterns:
            violations.append({
                "rule": f"Anti-pattern: {ap['type']}",
                "description": f"Satir {ap['line']}: {ap['description']}",
                "line_hint": f"Satir {ap['line']}",
                "severity": ap["severity"],
            })
            penalty = {"critical": 10, "high": 6, "medium": 3, "low": 1}.get(ap["severity"], 3)
            score -= penalty

        magic_core = [m for m in metrics.magic_numbers if m["line"] not in demo_lines]
        if magic_core:
            violations.append({
                "rule": "Clean Code - Magic number",
                "description": f"{len(magic_core)} magic number tespit edildi: "
                    + ", ".join(f"{m['value']} (satir {m['line']})" for m in magic_core[:5]),
                "line_hint": ", ".join(f"Satir {m['line']}" for m in magic_core[:5]),
                "severity": "low",
            })
            score -= 2

        doc_quality = "good" if has_docs else ("fair" if metrics.has_docstrings else "poor")
        compliance_text = f"{style_guide} kontrolu yapildi. " + (
            "Genel uyum iyi." if score > 65 else
            "Bazi ihlaller mevcut." if score > 45 else
            "Ciddi ihlaller tespit edildi."
        )

        final = max(22, min(100, score))
        return {
            "naming_quality": naming["quality"],
            "documentation_quality": doc_quality,
            "clean_code_score": final,
            "style_guide_compliance": compliance_text,
            "style_violations": violations,
            "has_docstrings": has_docs or metrics.has_docstrings,
            "has_type_hints": has_hints,
            "function_length_ok": fn_length_ok,
            "nesting_depth_ok": nesting_ok,
            "dry_violations": dry_violations,
            "score": final,
        }


def _check_naming(metrics, lines: list[str], language: str) -> dict:
    """Isimlendirme kurallarini kontrol eder."""
    violations = []
    good_count = 0
    bad_count = 0

    _snake = re.compile(r'^_?_?[a-z][a-z0-9_]*_?_?$')

    for fn in metrics.functions:
        if language.lower() in ("python", "py"):
            if fn.name.startswith("__") and fn.name.endswith("__"):
                good_count += 1
            elif not _snake.match(fn.name):
                violations.append({
                    "rule": "PEP8 - Fonksiyon isimlendirme",
                    "description": f"'{fn.name}' snake_case olmali",
                    "line_hint": f"Satir {fn.line}",
                    "severity": "low",
                })
                bad_count += 1
            else:
                good_count += 1

            if len(fn.name) <= 1:
                violations.append({
                    "rule": "Clean Code - Anlamli isimlendirme",
                    "description": f"'{fn.name}' cok kisa, aciklayici isim kullanin",
                    "line_hint": f"Satir {fn.line}",
                    "severity": "medium",
                })
                bad_count += 1

    for cls in metrics.classes:
        cls_name = cls["name"] if isinstance(cls, dict) else getattr(cls, "name", "")
        cls_line = cls["line"] if isinstance(cls, dict) else getattr(cls, "line", 0)
        if re.match(r'^[A-Z][a-zA-Z0-9]*$', cls_name):
            good_count += 1
        else:
            violations.append({
                "rule": "PEP8 - Sinif isimlendirme",
                "description": f"'{cls_name}' PascalCase olmali",
                "line_hint": f"Satir {cls_line}",
                "severity": "low",
            })
            bad_count += 1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("self.") or stripped.startswith("cls."):
            continue
        var_match = re.match(r'^([a-zA-Z])\s*=\s*', stripped)
        if var_match:
            var_name = var_match.group(1)
            if var_name not in ("i", "j", "k", "x", "y", "n", "e", "f", "d", "m", "p", "q", "r", "s", "t", "v", "w", "_"):
                violations.append({
                    "rule": "Clean Code - Tek harfli degisken",
                    "description": f"'{var_name}' degiskeni cok kisa (satir {i+1})",
                    "line_hint": f"Satir {i+1}",
                    "severity": "low",
                })
                bad_count += 1

    total = good_count + bad_count
    if total == 0:
        quality = "fair"
    elif bad_count == 0:
        quality = "excellent" if good_count >= 5 else "good"
    elif bad_count <= 1 and good_count >= 3:
        quality = "good"
    elif bad_count / total > 0.5:
        quality = "poor"
    else:
        quality = "fair"

    return {"quality": quality, "violations": violations}
