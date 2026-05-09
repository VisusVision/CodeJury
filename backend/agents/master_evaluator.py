"""
Master Rubric Evaluator Agent -- tam LLM: nihai rubrik yorumu Ollama ile.

Agirlikli cekirdek puan ve ajan ozetleri yalnizca prompt ipucu; final_score ve metinler LLM'den (LLM zorunlu).

Ogretmenin `faculty_rubric_criteria` listesi verildiyse (name, description, max_score), degerlendirme
buna gore satir satir yapilir; her satirda kazanilan puan 0..max_score arasidir; nihai not 100 uzerindendir.
"""
import json
from typing import Any

from backend.agents.assignment_alignment import alignment_summary_tr, compute_brief_code_alignment
from backend.agents.base import BaseAgent, LLMInferenceError, build_llm_user_suffix, format_assignment_context_for_prompt
from backend.agents.json_output_schema import MASTER_EVALUATOR_OUTPUT_SCHEMA

_DEFAULT_WEIGHTS = {"functionality": 35, "algorithmic_efficiency": 25, "code_standards": 25, "security": 15}
_LABELS_EN = {
    "functionality": "Functionality",
    "algorithmic_efficiency": "Algorithmic efficiency",
    "code_standards": "Code standards",
    "security": "Security",
}


def normalize_faculty_rubric_criteria(raw: Any) -> list[dict[str, Any]]:
    """DB / API'den gelen kriter listesini Master Evaluator girisine cevir."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        desc = str(item.get("description", "")).strip()
        try:
            mx = int(round(float(item.get("max_score", 0))))
        except (TypeError, ValueError):
            mx = 0
        if mx < 1:
            mx = 1
        out.append({"name": name, "description": desc, "max_score": mx})
    return out


def _rubrik_score(
    agent_dict: dict,
    default: int,
    *,
    floor: int = 0,
    ceiling: int = 100,
    zero_means_missing: bool = False,
) -> int:
    """Ajan 'score' alanini guvenle sayiya cevirir.

    dict.get('score', default) anahtar varken 0 dondururse default kullanilmaz; bu yuzden
    kod kalitesi gibi ajanlarda 0 genelde hatali ciktidir (zero_means_missing=True).
    Test ajaninda 0 gecerlidir (zero_means_missing=False).
    """
    if not isinstance(agent_dict, dict):
        return max(floor, min(ceiling, default))
    raw = agent_dict.get("score")
    if raw is None:
        return max(floor, min(ceiling, default))
    try:
        x = int(round(float(raw)))
    except (TypeError, ValueError):
        return max(floor, min(ceiling, default))
    x = max(0, min(ceiling, x))
    if zero_means_missing and x == 0:
        return max(floor, min(ceiling, default))
    return max(floor, min(ceiling, x))


_MASTER_SYSTEM_PROMPT = """\
You are a senior final code-review expert. Produce final_score, rubric_breakdown, and all narrative
feedback by reasoning over the agent outputs. The compact summary in the user message is a weighted
core hint only — it is not binding.

Rules:
- final_score: number 0–100 (weighted judgment).
- rubric_breakdown: for each criterion: {"criterion": str, "label": str, "weight": int, "score": 0-100, "weighted_score": float, "justification": str}
- strengths, weaknesses, recommendations: arrays of short strings.
- summary: one or two sentences.
- Be fair and resolve serious contradictions between agents in a balanced way.
- Treat sandbox/runtime facts and security facts as hard constraints, not opinions. A runtime-failing normal
  script, compilation failure, timeout, memory overflow, or critical/high security issue must appear in
  weaknesses and must materially cap the final grade.
- Do not let high style/seniority scores compensate for a submission that does not run, is off-topic, or
  contains critical unsafe code.
- If an ASSIGNMENT BRIEF block appears in the user message, you must judge whether the submission
  fulfills that brief (topic, required concepts, deliverables). Clear mismatch (wrong task, missing
  required paradigm such as OOP when required) should lower final_score and must appear in weaknesses
  and in rubric_breakdown justifications (especially functionality and code_standards).
- The numeric field brief_code_alignment (0–1) in the compact hint is programmatic: if it is below
  ~0.45, treat functionality / task fit as largely failed even when the sandbox run succeeded; do not
  award high functionality on correctness of an unrelated program.
- If brief_alignment_flags in the compact hint is non-empty, treat the submission as **off-topic /
  wrong deliverable** unless evidence proves otherwise. Say so clearly in summary and weaknesses
  (e.g. code addresses a different problem than the brief).
- When compact.llm_task_relevance_skipped is false and llm_task_relevance_factor is present: values
  near 0 mean the automated relevance model judged a serious topic mismatch; align summary and
  penalties with brief_code_alignment and brief_alignment_flags.

Reply with ONLY this JSON shape, no other text:
{
  "final_score": 0-100,
  "rubric_breakdown": [...],
  "summary": "...",
  "strengths": [],
  "weaknesses": [],
  "recommendations": []
}
"""

_MASTER_SYSTEM_PROMPT_FACULTY = """\
You are a senior grader. The instructor defined an assignment rubric: each row has a name, description,
and maximum points (weight). You must grade the student's submission against **each row** using agent
outputs as supporting evidence — not as a mechanical copy of their numeric scores.

Rules:
- rubric_breakdown: MUST contain **exactly one entry per row** in the FACULTY RUBRIC JSON array, in the **same order**.
- For row index i use "criterion": "criterion_i" (i zero-based).
- "label": must match the faculty row "name" **exactly** (same string).
- "weight": must equal that row's max_points (integer).
- "score": integer **points earned** from **0 to weight** inclusive (this is NOT a 0–100 scale per row unless weight is 100).
- "weighted_score": set equal to "score" (points earned for that row).
- "justification": Turkish (or report_language), specific to that criterion and the actual code/run results.
- final_score: single number 0–100: 100 * (sum of earned scores) / (sum of weights). Compute it correctly.
- Treat sandbox/runtime facts and security facts as hard constraints. If the code does not run, times out
  unexpectedly, exceeds memory, or contains critical/high security risks, cap the affected rubric rows and
  explain the cap in the relevant justifications.
- Never award near-full final credit to a runtime-failing or critically unsafe submission merely because it
  has good structure, naming, or partial implementation.
- If the assignment brief implies wrong topic / missing required concepts, heavily penalize the relevant criteria
  (e.g. scope/requirements/correctness rows).
- Use brief_code_alignment in the compact hint (0–1): if below ~0.45 and the brief is on record, cap points on
  rows about correctness, scope, or deliverables unless the code clearly matches the brief.
- If brief_alignment_flags is non-empty, the rubric row names/descriptions still define the **intended
  task**. Treat the submission as irrelevant / wrong-topic when the code clearly implements a different
  domain; say so in summary and in justifications for scope or correctness rows (do not praise unrelated work).
- When llm_task_relevance_skipped is false and llm_task_relevance_factor is low, echo topic mismatch in summary.

Reply with ONLY this JSON shape:
{
  "final_score": 0-100,
  "rubric_breakdown": [...],
  "summary": "...",
  "strengths": [],
  "weaknesses": [],
  "recommendations": []
}
"""


class MasterEvaluatorAgent(BaseAgent):
    name = "master_evaluator"
    description = "Rubrik degerlendirme ve nihai puanlama"

    async def analyze(self, input_data: dict) -> dict:
        report_language = input_data.get("report_language") or "tr"
        faculty = normalize_faculty_rubric_criteria(input_data.get("faculty_rubric_criteria"))

        programmatic = self._programmatic_analysis(input_data, faculty_rubric=faculty)
        compact = {
            "core_weighted_suggestion": programmatic["final_score"],
            "brief_code_alignment": round(float(programmatic.get("brief_alignment_factor", 1.0)), 3),
            "brief_alignment_flags": programmatic.get("brief_alignment_reasons", []),
            "rubric": [
                {"c": b["criterion"], "w": b["weight"], "s": b["score"]}
                for b in programmatic["rubric_breakdown"]
            ],
            "strengths": programmatic.get("strengths", [])[:4],
            "weaknesses": programmatic.get("weaknesses", [])[:4],
        }
        task_meta_in = input_data.get("task_alignment")
        if isinstance(task_meta_in, dict):
            compact["llm_task_relevance_factor"] = task_meta_in.get("llm_factor")
            compact["llm_task_relevance_skipped"] = bool(task_meta_in.get("llm_skipped", True))
            compact["task_domain_guess"] = task_meta_in.get("task_domain_guess")
            compact["submission_domain_guess"] = task_meta_in.get("submission_domain_guess")

        brief = format_assignment_context_for_prompt(input_data.get("assignment_description"))

        if faculty:
            faculty_json = [
                {
                    "order": i,
                    "name": c["name"],
                    "description": c["description"],
                    "max_points": c["max_score"],
                }
                for i, c in enumerate(faculty)
            ]
            user_prompt = (
                f"{brief}"
                "FACULTY RUBRIC — you MUST output exactly one rubric_breakdown entry per row, same order, exact names:\n"
                f"{json.dumps(faculty_json, ensure_ascii=False, separators=(',', ':'))}\n\n"
                "Non-binding automated agent summary (internal dimensions; map evidence to faculty rows yourself):\n"
                f"{json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}\n\n"
                "Task: Award integer points per row (0..max_points). Set final_score = 100 * sum(points)/sum(max_points). "
                "Write summary, strengths, weaknesses, recommendations."
                f"{build_llm_user_suffix(report_language=report_language)}"
            )
            try:
                llm_result = await self._call_llm(
                    system_prompt=_MASTER_SYSTEM_PROMPT_FACULTY,
                    user_prompt=user_prompt,
                    required_keys=[
                        "final_score",
                        "rubric_breakdown",
                        "summary",
                        "strengths",
                        "weaknesses",
                        "recommendations",
                    ],
                    output_json_schema=MASTER_EVALUATOR_OUTPUT_SCHEMA,
                    temperature=0.22,
                    num_predict=4096,
                    use_cache=False,
                )
            except LLMInferenceError as exc:
                llm_result = self._fallback_master_result(programmatic, faculty, exc)
            if not isinstance(llm_result.get("rubric_breakdown"), list):
                raise LLMInferenceError("[master_evaluator] rubric_breakdown gecersiz (faculty mode).")
            self._finalize_faculty_rubric_output(llm_result, faculty)
            self._apply_faculty_reasonableness_floor(llm_result, programmatic)
            self._apply_brief_alignment_guard(llm_result, programmatic, faculty_mode=True)
            self._apply_runtime_guard(
                llm_result,
                input_data.get("sandbox_result", {}),
                source_code=str(input_data.get("source_code") or ""),
                language=str(input_data.get("language") or "python"),
                faculty_mode=True,
            )
            self._apply_security_guard(
                llm_result,
                input_data.get("security", {}),
                faculty_mode=True,
            )
            return llm_result

        user_prompt = (
            f"{brief}"
            "Non-binding core hints from agents (weighted average — use your own judgment):\n"
            f"{json.dumps(compact, ensure_ascii=False, separators=(',',':'))}\n"
            "Task: Produce final_score, rubric_breakdown (with justification per criterion), summary, "
            "strengths, weaknesses, and recommendations. Resolve major contradictions fairly."
            f"{build_llm_user_suffix(report_language=report_language)}"
        )

        try:
            llm_result = await self._call_llm(
                system_prompt=_MASTER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                required_keys=[
                    "final_score",
                    "rubric_breakdown",
                    "summary",
                    "strengths",
                    "weaknesses",
                    "recommendations",
                ],
                output_json_schema=MASTER_EVALUATOR_OUTPUT_SCHEMA,
                temperature=0.22,
                num_predict=4096,
                use_cache=False,
            )
        except LLMInferenceError as exc:
            llm_result = self._fallback_master_result(programmatic, [], exc)

        if not isinstance(llm_result.get("rubric_breakdown"), list) or not llm_result["rubric_breakdown"]:
            raise LLMInferenceError("[master_evaluator] rubric_breakdown bos veya gecersiz.")

        # Doküman Bölüm 4 -- "not hesaplama LLM'e değil, bir Python script aracına
        # yaptırılmalıdır": LLM rubric_breakdown.score'u versin, final_score'u biz
        # ağırlıklara göre programatik olarak yeniden üretelim.
        self._recompute_default_final_score(llm_result)

        self._apply_brief_alignment_guard(llm_result, programmatic, faculty_mode=False)
        self._apply_runtime_guard(
            llm_result,
            input_data.get("sandbox_result", {}),
            source_code=str(input_data.get("source_code") or ""),
            language=str(input_data.get("language") or "python"),
            faculty_mode=False,
        )
        self._apply_security_guard(
            llm_result,
            input_data.get("security", {}),
            faculty_mode=False,
        )
        return llm_result

    @staticmethod
    def _fallback_master_result(
        programmatic: dict[str, Any],
        faculty: list[dict[str, Any]],
        error: Exception,
    ) -> dict[str, Any]:
        """Return a complete report if the final LLM emits malformed JSON.

        Other agents have already supplied LLM-backed facts; this prevents one malformed
        master JSON envelope from turning the whole analysis into HTTP 500.
        """
        base_score = max(0.0, min(100.0, float(programmatic.get("final_score", 0) or 0)))
        strengths = list(programmatic.get("strengths", []) or [])
        weaknesses = list(programmatic.get("weaknesses", []) or [])
        recommendations = list(programmatic.get("recommendations", []) or [])
        warning = (
            "Master evaluator LLM ciktisi beklenen JSON semasina uymadi; "
            "nihai rapor ajan ozetleri ve rubrik puanlariyla programatik olarak tamamlandi."
        )
        if warning not in weaknesses:
            weaknesses.insert(0, warning)

        if faculty:
            source_breakdown = programmatic.get("rubric_breakdown", [])
            score_by_criterion: dict[str, float] = {}
            if isinstance(source_breakdown, list):
                for row in source_breakdown:
                    if not isinstance(row, dict):
                        continue
                    key = str(row.get("criterion", "")).lower().strip()
                    try:
                        val = float(row.get("score", base_score))
                    except (TypeError, ValueError):
                        val = base_score
                    if key:
                        score_by_criterion[key] = max(0.0, min(100.0, val))
            security_score = score_by_criterion.get("security", base_score)
            functionality_score = score_by_criterion.get("functionality", base_score)
            efficiency_score = score_by_criterion.get("algorithmic_efficiency", base_score)
            standards_score = score_by_criterion.get("code_standards", base_score)

            def _row_percent(label_text: str) -> float:
                lower = label_text.lower()
                if any(token in lower for token in ("guven", "security", "risk", "tehdit")):
                    return security_score
                if any(token in lower for token in ("performans", "algorit", "karma", "big-o", "verim")):
                    return efficiency_score
                if any(token in lower for token in ("dokuman", "dokum", "yorum", "okun", "standart", "kod kalitesi")):
                    return standards_score
                if any(token in lower for token in ("api", "endpoint", "test", "hata", "temiz", "guzel", "sunucu", "calis", "islev")):
                    return functionality_score
                return base_score

            if isinstance(source_breakdown, list):
                for row in source_breakdown:
                    if isinstance(row, dict) and str(row.get("criterion", "")).lower() == "security":
                        try:
                            security_score = float(row.get("score", base_score))
                        except (TypeError, ValueError):
                            security_score = base_score
                        break

            rows: list[dict[str, Any]] = []
            total_max = 0
            total_earned = 0
            for i, criterion in enumerate(faculty):
                weight = int(criterion.get("max_score", 0) or 0)
                label = str(criterion.get("name", f"Kriter {i + 1}"))
                score_base = _row_percent(label)
                earned = max(0, min(weight, int(round(weight * score_base / 100.0))))
                rows.append({
                    "criterion": f"criterion_{i}",
                    "label": label,
                    "weight": weight,
                    "score": earned,
                    "weighted_score": float(earned),
                    "justification": (
                        f"LLM format hatasi nedeniyle bu satir, diger ajanlarin ozet puanlari "
                        f"ve rubrik agirligi kullanilarak hesaplandi. Hata: {error}"
                    ),
                })
                total_max += weight
                total_earned += earned
            final_score = round(100.0 * total_earned / total_max, 1) if total_max > 0 else 0.0
            breakdown = rows
        else:
            breakdown = list(programmatic.get("rubric_breakdown", []) or [])
            final_score = base_score

        return {
            "final_score": max(0.0, min(100.0, float(final_score))),
            "rubric_breakdown": breakdown,
            "summary": (
                f"{warning} Programatik nihai puan: {round(float(final_score), 1)}/100."
            ),
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendations": recommendations,
            "llm_status": "fallback",
            "llm_error": str(error),
        }

    @staticmethod
    def _recompute_default_final_score(llm_result: dict[str, Any]) -> None:
        """LLM matematiksel halüsinasyonunu ortadan kaldır: final_score'u Python ile yeniden hesapla.

        Default rubric satırlarında `score` 0..100 ölçeğindedir; final = sum(score * weight) / sum(weight).
        weighted_score alanı da tutarlı şekilde yeniden yazılır.
        """
        bd = llm_result.get("rubric_breakdown")
        if not isinstance(bd, list) or not bd:
            return
        total_weight = 0.0
        accumulated = 0.0
        for row in bd:
            if not isinstance(row, dict):
                continue
            try:
                w = float(row.get("weight", 0))
                s = float(row.get("score", 0))
            except (TypeError, ValueError):
                continue
            if w <= 0:
                continue
            s = max(0.0, min(100.0, s))
            row["score"] = int(round(s))
            row["weight"] = int(round(w))
            row["weighted_score"] = round(s * w / 100.0, 2)
            total_weight += w
            accumulated += s * w / 100.0
        if total_weight <= 0:
            try:
                fs = float(llm_result.get("final_score", 0))
            except (TypeError, ValueError):
                fs = 0.0
            llm_result["final_score"] = max(0.0, min(100.0, round(fs, 1)))
            return
        final = round(100.0 * accumulated / total_weight, 1)
        llm_result["final_score"] = max(0.0, min(100.0, final))

    @staticmethod
    def _alignment_score_cap(alignment_factor: float) -> float:
        """Clear topic mismatch gets a hard final-score ceiling, independent of LLM optimism."""
        if alignment_factor < 0.18:
            return 28.0
        if alignment_factor < 0.30:
            return 35.0
        if alignment_factor < 0.45:
            return 42.0
        if alignment_factor < 0.70:
            return 65.0
        return 100.0

    @staticmethod
    def _is_security_row(row: dict[str, Any]) -> bool:
        label = str(row.get("label", row.get("criterion", ""))).lower()
        return any(token in label for token in ("security", "güven", "guven"))

    @classmethod
    def _apply_brief_alignment_guard(
        cls,
        llm_result: dict[str, Any],
        programmatic: dict[str, Any],
        *,
        faculty_mode: bool,
    ) -> None:
        """Rubric/brief mismatch is a grading invariant, not just a prompt suggestion."""
        try:
            align_f = float(programmatic.get("brief_alignment_factor", 1.0))
        except (TypeError, ValueError):
            align_f = 1.0
        if align_f >= 0.70:
            return

        cap = cls._alignment_score_cap(align_f)
        if cap >= 100.0:
            return

        reasons = programmatic.get("brief_alignment_reasons", [])
        reason_text = alignment_summary_tr(reasons if isinstance(reasons, list) else [])
        if not reason_text:
            reason_text = (
                "Teslim, ödev açıklaması ve rubrik kriterleriyle örtüşmüyor; "
                "kod hedef görevi karşılamıyor olabilir (alakasız veya yanlış teslim)."
            )
        expl_guard = programmatic.get("llm_relevance_explanation")
        if expl_guard and str(expl_guard).strip():
            extra = str(expl_guard).strip()
            if extra not in reason_text:
                reason_text = f"{reason_text} LLM görev uyumu: {extra}"

        raw_bd = llm_result.get("rubric_breakdown")
        if isinstance(raw_bd, list):
            for row in raw_bd:
                if not isinstance(row, dict):
                    continue

                try:
                    weight = int(round(float(row.get("weight", 100))))
                except (TypeError, ValueError):
                    weight = 100
                try:
                    current = float(row.get("score", 0))
                except (TypeError, ValueError):
                    current = 0.0

                if faculty_mode:
                    # Faculty rows are points. Security-only rows can stay high; every other row
                    # depends on solving the requested assignment.
                    row_cap = weight if cls._is_security_row(row) else max(0, int(round(weight * cap / 100.0)))
                    new_score = min(current, float(row_cap))
                    row["score"] = int(round(new_score))
                    row["weighted_score"] = float(row["score"])
                else:
                    # Default rows use 0..100 scores inside the evaluator.
                    criterion = str(row.get("criterion", "")).lower()
                    if criterion in {"functionality", "code_standards"}:
                        row_cap = cap
                    elif criterion == "algorithmic_efficiency":
                        row_cap = max(cap, 55.0)
                    elif cls._is_security_row(row):
                        row_cap = 100.0
                    else:
                        row_cap = max(cap, 60.0)
                    row["score"] = int(round(max(0.0, min(current, row_cap))))
                    if weight > 0:
                        row["weighted_score"] = round(row["score"] * weight / 100.0, 2)

                just = str(row.get("justification", "")).strip()
                note = f"Ödev uyumu cezası: {reason_text}"
                row["justification"] = f"{just} {note}".strip() if just else note

        if faculty_mode and isinstance(llm_result.get("rubric_breakdown"), list):
            total_max = 0
            total_earned = 0
            for row in llm_result["rubric_breakdown"]:
                if not isinstance(row, dict):
                    continue
                try:
                    total_max += int(round(float(row.get("weight", 0))))
                    total_earned += int(round(float(row.get("score", 0))))
                except (TypeError, ValueError):
                    continue
            guarded = round(100.0 * total_earned / total_max, 1) if total_max > 0 else 0.0
        else:
            try:
                guarded = float(llm_result.get("final_score", 0))
            except (TypeError, ValueError):
                guarded = 0.0

        llm_result["final_score"] = round(max(0.0, min(float(cap), guarded)), 1)

        weaknesses = llm_result.get("weaknesses")
        if not isinstance(weaknesses, list):
            weaknesses = []
        if reason_text not in weaknesses:
            weaknesses.insert(0, reason_text)
        llm_result["weaknesses"] = weaknesses

    @staticmethod
    def _apply_faculty_reasonableness_floor(
        llm_result: dict[str, Any],
        programmatic: dict[str, Any],
    ) -> None:
        """Prevent faculty-mode LLM variance from crushing clearly relevant, high-signal work.

        The LLM still writes the row-level narrative, but deterministic agent scores define a
        conservative floor when the final faculty score is implausibly below the core analysis.
        Hard caps for off-topic/runtime/security run after this method.
        """
        raw_bd = llm_result.get("rubric_breakdown")
        if not isinstance(raw_bd, list) or not raw_bd:
            return
        try:
            current = float(llm_result.get("final_score", 0) or 0)
            core = float(programmatic.get("final_score", 0) or 0)
            align_f = float(programmatic.get("brief_alignment_factor", 1.0) or 1.0)
        except (TypeError, ValueError):
            return

        reasons = programmatic.get("brief_alignment_reasons", [])
        if not isinstance(reasons, list):
            reasons = []
        has_topic_warning = any(
            reason in {"llm_task_relevance_off_topic", "llm_low_task_fit"}
            for reason in reasons
        )
        if align_f < 0.70 or has_topic_warning or core < 60 or current >= core - 18:
            return

        target = max(current, min(core, core - 12))
        target = max(0.0, min(100.0, target))
        total_max = 0
        total_earned = 0
        adjustable: list[dict[str, Any]] = []
        for row in raw_bd:
            if not isinstance(row, dict):
                continue
            try:
                weight = int(round(float(row.get("weight", 0) or 0)))
                score = int(round(float(row.get("score", 0) or 0)))
            except (TypeError, ValueError):
                continue
            if weight <= 0:
                continue
            score = max(0, min(weight, score))
            row["score"] = score
            row["weighted_score"] = float(score)
            total_max += weight
            total_earned += score
            if score < weight and not MasterEvaluatorAgent._is_security_row(row):
                adjustable.append(row)
        if total_max <= 0:
            return

        target_earned = int(round(total_max * target / 100.0))
        missing = max(0, target_earned - total_earned)
        if missing <= 0:
            return

        note = (
            "Deterministik tutarlilik duzeltmesi: alt ajan puanlari ve gorev uyumu bu "
            "satirda LLM'in ilk puanindan daha yuksek bir taban gerektirdi."
        )
        while missing > 0 and adjustable:
            progressed = False
            for row in adjustable:
                if missing <= 0:
                    break
                try:
                    weight = int(round(float(row.get("weight", 0) or 0)))
                    score = int(round(float(row.get("score", 0) or 0)))
                except (TypeError, ValueError):
                    continue
                if score >= weight:
                    continue
                row["score"] = score + 1
                row["weighted_score"] = float(row["score"])
                just = str(row.get("justification", "")).strip()
                if note not in just:
                    row["justification"] = f"{just} {note}".strip() if just else note
                missing -= 1
                progressed = True
            adjustable = [
                row
                for row in adjustable
                if int(round(float(row.get("score", 0) or 0)))
                < int(round(float(row.get("weight", 0) or 0)))
            ]
            if not progressed:
                break

        total_earned = 0
        for row in raw_bd:
            if not isinstance(row, dict):
                continue
            try:
                total_earned += int(round(float(row.get("score", 0) or 0)))
            except (TypeError, ValueError):
                continue
        llm_result["final_score"] = round(100.0 * total_earned / total_max, 1)

        recs = llm_result.get("recommendations")
        if not isinstance(recs, list):
            recs = []
        msg = (
            "Nihai puan, alt ajan skorlarina gore asiri dusuk kalan faculty rubrik "
            "puanlarini deterministik olarak yeniden dengelendi."
        )
        if msg not in recs:
            recs.append(msg)
        llm_result["recommendations"] = recs

    @classmethod
    def _apply_runtime_guard(
        cls,
        llm_result: dict[str, Any],
        sandbox_result: dict[str, Any],
        *,
        source_code: str = "",
        language: str = "python",
        faculty_mode: bool,
    ) -> None:
        """Runtime facts are hard grading constraints, independent of LLM optimism."""
        if not isinstance(sandbox_result, dict) or not sandbox_result:
            return

        compilation_ok = bool(sandbox_result.get("compilation_success", True))
        exit_code = sandbox_result.get("exit_code", 0)
        timed_out = bool(sandbox_result.get("timed_out") or sandbox_result.get("timeout"))
        memory_exceeded = bool(sandbox_result.get("memory_exceeded"))

        cap: float | None = None
        reason = ""
        if not compilation_ok:
            cap = 20.0
            reason = "Derleme basarisiz oldugu icin nihai not yuksek olamaz."
        elif timed_out:
            from backend.agents.test_agent import _looks_like_service_program

            if _looks_like_service_program(source_code, language):
                return
            cap = 35.0
            reason = "Program zaman asimina dustugu icin calisabilirlik ciddi sekilde basarisiz."
        elif memory_exceeded:
            cap = 35.0
            reason = "Program bellek limitini astigi icin calisabilirlik ciddi sekilde basarisiz."
        else:
            try:
                exit_i = int(exit_code)
            except (TypeError, ValueError):
                exit_i = 0
            if exit_i != 0:
                from backend.agents.test_agent import _looks_like_cli_program, _looks_like_cli_usage_error

                if _looks_like_cli_program(source_code, language) and _looks_like_cli_usage_error(
                    str(sandbox_result.get("stderr") or "")
                ):
                    return
                cap = 55.0
                reason = f"Program runtime hatasiyla sonlandi (exit code {exit_i}); calisabilirlik puani sinirlandi."

        if cap is None:
            return

        raw_bd = llm_result.get("rubric_breakdown")
        if isinstance(raw_bd, list):
            for row in raw_bd:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label", row.get("criterion", ""))).lower()
                runtime_sensitive = any(
                    token in label
                    for token in (
                        "calis",
                        "çalis",
                        "correct",
                        "dogru",
                        "test",
                        "hata",
                        "kose",
                        "gereksin",
                        "islev",
                        "fonksiyon",
                        "endpoint",
                        "api",
                    )
                )
                if not runtime_sensitive:
                    continue
                try:
                    weight = float(row.get("weight", 100))
                    current = float(row.get("score", 0))
                except (TypeError, ValueError):
                    continue
                if faculty_mode:
                    row_cap = max(0.0, weight * cap / 100.0)
                    row["score"] = int(round(min(current, row_cap)))
                    row["weighted_score"] = float(row["score"])
                else:
                    row["score"] = int(round(min(current, cap)))
                    row["weighted_score"] = round(row["score"] * weight / 100.0, 2)
                just = str(row.get("justification", "")).strip()
                row["justification"] = f"{just} Runtime cezasi: {reason}".strip()

        if faculty_mode and isinstance(llm_result.get("rubric_breakdown"), list):
            total_max = 0
            total_earned = 0
            for row in llm_result["rubric_breakdown"]:
                if not isinstance(row, dict):
                    continue
                try:
                    total_max += int(round(float(row.get("weight", 0))))
                    total_earned += int(round(float(row.get("score", 0))))
                except (TypeError, ValueError):
                    continue
            guarded = round(100.0 * total_earned / total_max, 1) if total_max > 0 else 0.0
        else:
            cls._recompute_default_final_score(llm_result)
            try:
                guarded = float(llm_result.get("final_score", 0))
            except (TypeError, ValueError):
                guarded = 0.0

        llm_result["final_score"] = round(max(0.0, min(float(cap), guarded)), 1)
        weaknesses = llm_result.get("weaknesses")
        if not isinstance(weaknesses, list):
            weaknesses = []
        if reason and reason not in weaknesses:
            weaknesses.insert(0, reason)
        llm_result["weaknesses"] = weaknesses

    @classmethod
    def _apply_security_guard(
        cls,
        llm_result: dict[str, Any],
        security_result: dict[str, Any],
        *,
        faculty_mode: bool,
    ) -> None:
        """Critical security findings should materially constrain the final grade."""
        if not isinstance(security_result, dict) or not security_result:
            return
        risk = str(security_result.get("risk_level", "")).lower()
        try:
            critical = int(security_result.get("critical_count", 0) or 0)
            high = int(security_result.get("high_count", 0) or 0)
            sec_score = float(security_result.get("score", 100) or 100)
        except (TypeError, ValueError):
            critical = 0
            high = 0
            sec_score = 100.0

        cap: float | None = None
        if risk == "critical" or critical > 0 or sec_score <= 55:
            cap = 65.0
            reason = "Kritik guvenlik riski tespit edildigi icin nihai not sinirlandi."
        elif risk == "high" or high > 0 or sec_score <= 70:
            cap = 78.0
            reason = "Yuksek guvenlik riski tespit edildigi icin nihai not sinirlandi."
        else:
            return

        raw_bd = llm_result.get("rubric_breakdown")
        if isinstance(raw_bd, list):
            for row in raw_bd:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label", row.get("criterion", ""))).lower()
                if not any(token in label for token in ("guven", "güven", "security", "risk")):
                    continue
                try:
                    weight = float(row.get("weight", 100))
                    current = float(row.get("score", 0))
                except (TypeError, ValueError):
                    continue
                if faculty_mode:
                    row_cap = max(0.0, weight * sec_score / 100.0)
                    row["score"] = int(round(min(current, row_cap)))
                    row["weighted_score"] = float(row["score"])
                else:
                    row["score"] = int(round(min(current, sec_score)))
                    row["weighted_score"] = round(row["score"] * weight / 100.0, 2)
                just = str(row.get("justification", "")).strip()
                row["justification"] = f"{just} Guvenlik cezasi: {reason}".strip()

        if faculty_mode and isinstance(llm_result.get("rubric_breakdown"), list):
            total_max = 0
            total_earned = 0
            for row in llm_result["rubric_breakdown"]:
                if not isinstance(row, dict):
                    continue
                try:
                    total_max += int(round(float(row.get("weight", 0))))
                    total_earned += int(round(float(row.get("score", 0))))
                except (TypeError, ValueError):
                    continue
            guarded = round(100.0 * total_earned / total_max, 1) if total_max > 0 else 0.0
        else:
            cls._recompute_default_final_score(llm_result)
            try:
                guarded = float(llm_result.get("final_score", 0))
            except (TypeError, ValueError):
                guarded = 0.0

        llm_result["final_score"] = round(max(0.0, min(float(cap), guarded)), 1)
        weaknesses = llm_result.get("weaknesses")
        if not isinstance(weaknesses, list):
            weaknesses = []
        if reason not in weaknesses:
            weaknesses.insert(0, reason)
        llm_result["weaknesses"] = weaknesses

    @staticmethod
    def _finalize_faculty_rubric_output(llm_result: dict, faculty: list[dict[str, Any]]) -> None:
        """LLM ciktisini ogretmen satirlariyla hizalar; puanlari 0..max'a kirpar; nihai notu hesaplar."""
        raw_bd = llm_result.get("rubric_breakdown")
        if not isinstance(raw_bd, list):
            raw_bd = []
        total_max = sum(int(c["max_score"]) for c in faculty)
        new_bd: list[dict[str, Any]] = []
        for i, fc in enumerate(faculty):
            wmax = int(fc["max_score"])
            row: dict[str, Any] = raw_bd[i] if i < len(raw_bd) and isinstance(raw_bd[i], dict) else {}
            try:
                raw_s = float(row.get("score", 0))
            except (TypeError, ValueError):
                raw_s = 0.0
            if raw_s > float(wmax) + 0.5:
                earned = int(round(raw_s * wmax / 100.0))
            else:
                earned = int(round(raw_s))
            earned = max(0, min(wmax, earned))
            just = str(row.get("justification", "")).strip()
            if not just:
                just = (
                    f"\"{fc['name']}\" kriteri: Otomatik agent ozetine dayanarak degerlendirildi; "
                    f"detay icin kanit listesine bakin."
                )
            new_bd.append({
                "criterion": f"criterion_{i}",
                "label": fc["name"],
                "weight": wmax,
                "score": earned,
                "weighted_score": float(earned),
                "justification": just,
            })
        llm_result["rubric_breakdown"] = new_bd
        total_earned = sum(int(b["score"]) for b in new_bd)
        llm_result["final_score"] = (
            round(100.0 * total_earned / total_max, 1) if total_max > 0 else 0.0
        )
        llm_result["final_score"] = max(0.0, min(100.0, float(llm_result["final_score"])))

    def _programmatic_analysis(
        self,
        input_data: dict,
        *,
        faculty_rubric: list[dict[str, Any]] | None = None,
    ) -> dict:
        """Agirlikli cekirdek ve ozetler -- yalnizca LLM prompt ipucu."""
        evidence = input_data.get("evidence", {})
        sandbox_result = input_data.get("sandbox_result", {})
        rubric = input_data.get("rubric")
        brief_txt = str(input_data.get("assignment_description") or "").strip()
        source_txt = str(input_data.get("source_code") or "")
        task_meta = input_data.get("task_alignment")
        if isinstance(task_meta, dict) and "factor" in task_meta:
            align_f = float(task_meta["factor"])
            align_rs = list(task_meta.get("reasons", []))
        else:
            align_f, align_rs = compute_brief_code_alignment(
                brief_txt,
                source_txt,
                rubric_criteria=faculty_rubric,
            )
        if not rubric or not isinstance(rubric, dict):
            rubric = dict(_DEFAULT_WEIGHTS)
        else:
            rubric = {k: int(v) for k, v in rubric.items() if isinstance(v, (int, float))}
            if not rubric:
                rubric = dict(_DEFAULT_WEIGHTS)

        cq = input_data.get("code_quality", {}) or {}
        ta = input_data.get("test_agent", {}) or {}
        sn = input_data.get("seniority", {}) or {}
        gl = input_data.get("guideline", {}) or {}
        sc = input_data.get("security", {}) or {}
        validated = evidence.get("validated_claims", [])

        ta_s = _rubrik_score(ta, 72, floor=0, ceiling=100, zero_means_missing=False)
        cq_s = _rubrik_score(cq, 72, floor=0, ceiling=100, zero_means_missing=True)
        sn_s = _rubrik_score(sn, 60, floor=0, ceiling=100, zero_means_missing=True)
        gl_raw = _rubrik_score(gl, 60, floor=0, ceiling=100, zero_means_missing=True)
        gl_alt = gl.get("clean_code_score") if isinstance(gl, dict) else None
        gl_s = gl_raw
        if isinstance(gl_alt, (int, float)):
            try:
                alt_i = int(round(float(gl_alt)))
                gl_s = max(gl_s, max(0, min(100, alt_i)))
            except (TypeError, ValueError):
                pass
        std_s = max(12, min(100, int(round((sn_s + gl_s) / 2))))
        sc_s = _rubrik_score(sc, 98, floor=0, ceiling=100, zero_means_missing=False)

        if align_f < 1.0:
            cq_s = max(0, min(100, int(round(cq_s * (0.52 + 0.48 * align_f)))))

        criteria_map = {
            "functionality": {"agents": ["test_agent"], "claims": [], "score": ta_s},
            "algorithmic_efficiency": {"agents": ["code_quality"], "claims": [], "score": cq_s},
            "code_standards": {"agents": ["seniority", "guideline"], "claims": [], "score": std_s},
            "security": {"agents": ["security"], "claims": [], "score": sc_s},
        }
        for claim in validated:
            src = claim.get("agent_source", "")
            for _c, info in criteria_map.items():
                if src in info["agents"]:
                    info["claims"].append(claim)

        if sandbox_result:
            if not sandbox_result.get("compilation_success", True):
                criteria_map["functionality"]["score"] = min(criteria_map["functionality"]["score"], 10)
            elif sandbox_result.get("exit_code", 0) != 0:
                from backend.agents.test_agent import (
                    _looks_like_cli_program,
                    _looks_like_cli_usage_error,
                    _looks_like_service_program,
                )

                stderr = str(sandbox_result.get("stderr") or "")
                timed_out = bool(sandbox_result.get("timed_out") or sandbox_result.get("timeout"))
                service_timeout = timed_out and _looks_like_service_program(source_txt, str(input_data.get("language") or "python"))
                cli_usage_exit = _looks_like_cli_program(source_txt, str(input_data.get("language") or "python")) and _looks_like_cli_usage_error(stderr)
                if not (service_timeout or cli_usage_exit):
                    criteria_map["functionality"]["score"] = min(criteria_map["functionality"]["score"], 35)

        tw = sum(rubric.get(k, 0) for k in criteria_map)
        if tw <= 0:
            tw = sum(_DEFAULT_WEIGHTS.values())
        breakdown, wsum = [], 0.0
        for crit in criteria_map:
            w = int(rubric.get(crit, _DEFAULT_WEIGHTS.get(crit, 0)))
            if w <= 0:
                continue
            sc_ = criteria_map[crit]["score"]
            wp = (sc_ * w) / tw
            wsum += wp
            claims = criteria_map[crit]["claims"]
            if not claims:
                just = f"{crit}: Summary score {sc_}/100."
            else:
                lines_j = [f"{crit} ({sc_}/100):"]
                for c in claims[:5]:
                    sev = str(c.get("severity", "medium")).upper()
                    ln = c.get("lines", [])
                    fb = str(c.get("feedback", ""))[:120]
                    lines_j.append(f"  [{sev}] {ln if ln else 'General'}: {fb}")
                just = "\n".join(lines_j)
            breakdown.append({
                "criterion": crit,
                "label": _LABELS_EN.get(crit, crit),
                "weight": w,
                "score": sc_,
                "weighted_score": round(wp, 2),
                "justification": just,
            })
        final_score = round(wsum, 1)
        strengths, weaknesses, recommendations = [], [], []
        if sandbox_result and sandbox_result.get("compilation_success") and sandbox_result.get("exit_code") == 0:
            strengths.append("Code compiles and runs successfully")
        fs = criteria_map["functionality"]["score"]
        as_ = criteria_map["algorithmic_efficiency"]["score"]
        ss = criteria_map["code_standards"]["score"]
        se = criteria_map["security"]["score"]
        if fs >= 70:
            strengths.append("Functionality is adequate")
        elif fs < 40:
            weaknesses.append("Code does not run or does not match expected output")
            recommendations.append("Fix correctness before polish")
        if as_ >= 70:
            strengths.append("Algorithmic efficiency is solid")
        elif as_ < 50:
            weaknesses.append("Algorithmic efficiency is weak")
            recommendations.append("Optimize hot paths (e.g. hash-based lookups)")
        if ss >= 70:
            strengths.append("Code standards compliance is good")
        elif ss < 50:
            weaknesses.append("Code standards and documentation are insufficient")
            recommendations.append("Add docstrings and consider type hints")
        if se >= 90:
            strengths.append("Security posture looks clean")
        elif se < 50:
            weaknesses.append("Security risks were flagged")
            recommendations.append("Remove risky calls/imports where possible")
        if align_f < 1.0:
            hum = alignment_summary_tr(align_rs)
            if hum:
                weaknesses.append(hum)
        expl: str | None = None
        if isinstance(task_meta, dict):
            expl = task_meta.get("llm_explanation")
        if (
            align_f < 0.98
            and expl
            and str(expl).strip()
            and isinstance(task_meta, dict)
            and not task_meta.get("llm_skipped")
        ):
            line = f"Görev uyumu (LLM): {str(expl).strip()}"
            if line not in weaknesses:
                weaknesses.append(line)

        if any(c.get("severity") in ("high", "critical") for c in validated):
            weaknesses.append("High-severity issues were validated")
        if not strengths:
            strengths.append("There is a clear attempt to solve the problem")
        tv = evidence.get("total_claims_received", 0)
        vv = evidence.get("total_claims_validated", 0)
        hc = sum(1 for c in validated if c.get("severity") in ("high", "critical"))
        expl_out: str | None = None
        if isinstance(task_meta, dict):
            expl_out = task_meta.get("llm_explanation")
            if expl_out is not None:
                expl_out = str(expl_out).strip() or None
        summary = (
            f"Hint final score: {final_score}/100. {vv}/{tv} claims validated ({hc} high / critical). "
            f"Functionality: {fs}/100, Efficiency: {as_}/100, Standards: {ss}/100, Security: {se}/100."
        )
        return {
            "final_score": final_score,
            "rubric_breakdown": breakdown,
            "summary": summary,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendations": recommendations,
            "brief_alignment_factor": align_f,
            "brief_alignment_reasons": list(align_rs),
            "llm_relevance_explanation": expl_out,
        }


def generate_markdown_report(result: dict) -> str:
    out = ["# Kod Degerlendirme Raporu\n", f"**Nihai Puan: {result.get('final_score', 0)}/100**\n"]
    for it in result.get("rubric_breakdown", []):
        w = it.get("weight", 100)
        s = it.get("score", 0)
        out.append(f"- {it.get('label', it.get('criterion'))}: {s}/{w} puan\n")
    out.append("\n---\n" + result.get("summary", ""))
    return "".join(out)
