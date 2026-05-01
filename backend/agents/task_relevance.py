"""
LLM tabanlı görev uyumu: ödev + rubrik ile yüklenen kodun **aynı görevi** hedefleyip hedeflemediği.

Alan (domain) spesifik kurallar yok; yeni projeler ve rubrikler için genel amaçlı değerlendirmedir.

Programatik `compute_brief_code_alignment` yalnızca nötr / neredeyse boş teslim ipucu verir; asıl uyum
burada belirlenir ve `merge_task_alignment` ile birleşir.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.assignment_alignment import BRIEF_MIN_LEN, _rubric_criteria_text
from backend.agents.base import build_llm_user_suffix
from backend.agents.json_output_schema import TASK_RELEVANCE_OUTPUT_SCHEMA, collect_validation_messages
from backend.core.config import settings
from backend.llm.ollama_client import chat_json

logger = logging.getLogger(__name__)

_TASK_RELEVANCE_SYSTEM = """\
You are a strict grading assistant. The instructor brief and rubric rows together define ONE assignment.
The student submitted source code. Your job is to judge whether this submission is actually aimed at
that assignment — for ANY subject (algorithms, OOP, web, data structures, games, etc.).

Output JSON fields:
- relevance_factor: float 0–1. Use 1.0 only when the code clearly implements what the assignment asks.
  Use 0.05–0.22 when the code is clearly a different project / wrong topic / unrelated file (wrong stack,
  wrong problem, or unrelated codebase). Middle values only for partial or ambiguous fit.
- off_topic: true if the code addresses a different problem than the assignment (not a minor bug).
- student_fulfills_assignment: true only if the code substantively meets the described deliverables.
- confidence: optional 0–1.
- explanation: 2–4 sentences in the report language. If off_topic or very low relevance, you MUST
  clearly state that the submission does not match the assignment (e.g. Turkish: «alakasız teslim»,
  «ödevle bağlantısı yok», «yanlış ödev / yanlış proje yüklendi»).
- submission_domain_guess: short neutral label of what the code does (e.g. "CRUD API", "linked list").
- task_domain_guess: short neutral label of what the assignment requires.

Rules:
- Compare **only** the stated assignment (brief + rubric) to the code. Do not assume a favorite domain.
- If brief + rubric are too vague to infer a task, set relevance_factor 1.0, off_topic false,
  student_fulfills_assignment true, and say the task was underspecified.
- Empty or placeholder code → very low relevance_factor, student_fulfills_assignment false.
Reply with ONLY valid JSON matching the schema in the user message.
"""



async def assess_task_relevance_llm(
    *,
    assignment_description: str,
    source_code: str,
    rubric_criteria: list[dict[str, Any]] | None,
    report_language: str = "tr",
) -> dict[str, Any]:
    brief = (assignment_description or "").strip()
    rub_blob = _rubric_criteria_text(rubric_criteria)
    combined = "\n".join(x for x in (brief, rub_blob) if x).strip()
    if len(combined) < BRIEF_MIN_LEN:
        return {"skipped": True, "relevance_factor": 1.0, "reason": "insufficient_task_context"}

    if not settings.ollama_enabled:
        return {"skipped": True, "relevance_factor": 1.0, "reason": "ollama_disabled"}

    rubric_json = []
    if rubric_criteria:
        for i, row in enumerate(rubric_criteria):
            if not isinstance(row, dict):
                continue
            rubric_json.append({
                "row": i,
                "name": str(row.get("name", "") or ""),
                "description": str(row.get("description", "") or ""),
            })

    code_sample = source_code or ""
    max_chars = 12000
    if len(code_sample) > max_chars:
        code_sample = (
            code_sample[: max_chars // 2]
            + "\n# [... truncated for relevance check ...]\n"
            + code_sample[-max_chars // 2 :]
        )

    user_prompt = (
        "[INSTRUCTOR BRIEF]\n"
        f"{brief or '(none)'}\n\n"
        "[FACULTY RUBRIC ROWS — name + description]\n"
        f"{json.dumps(rubric_json, ensure_ascii=False, indent=2) if rubric_json else '(none)'}\n\n"
        "[STUDENT SOURCE — excerpt]\n"
        f"```\n{code_sample}\n```\n"
        "Return JSON with: relevance_factor, off_topic, student_fulfills_assignment, explanation, "
        "submission_domain_guess, task_domain_guess; optional confidence 0–1."
        f"{build_llm_user_suffix(report_language=report_language)}"
    )

    try:
        raw = await chat_json(
            system_prompt=_TASK_RELEVANCE_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.15,
            num_predict=1536,
            use_cache=False,
        )
    except Exception as exc:
        logger.warning("[task_relevance] LLM cagrisi basarisiz: %s", exc)
        return {"skipped": True, "relevance_factor": 1.0, "reason": "llm_error"}

    if not isinstance(raw, dict):
        return {"skipped": True, "relevance_factor": 1.0, "reason": "invalid_response"}

    msgs = collect_validation_messages(raw, TASK_RELEVANCE_OUTPUT_SCHEMA)
    if msgs:
        logger.warning("[task_relevance] schema ilk tur: %s", msgs[:4])
        repair = (
            user_prompt
            + "\n\n[SCHEMA REPAIR] Fix JSON. Errors:\n"
            + "\n".join(msgs)
            + "\nReturn ONLY complete valid JSON."
        )
        try:
            raw2 = await chat_json(
                system_prompt=_TASK_RELEVANCE_SYSTEM,
                user_prompt=repair,
                temperature=0.1,
                num_predict=1536,
                use_cache=False,
            )
        except Exception as exc:
            logger.warning("[task_relevance] schema onarim basarisiz: %s", exc)
            return {"skipped": True, "relevance_factor": 1.0, "reason": "schema_repair_failed"}
        if isinstance(raw2, dict):
            raw = raw2
            msgs = collect_validation_messages(raw, TASK_RELEVANCE_OUTPUT_SCHEMA)
        if msgs:
            logger.warning("[task_relevance] schema ikinci tur hata: %s", msgs[:4])
            return {"skipped": True, "relevance_factor": 1.0, "reason": "schema_invalid"}

    try:
        rf = float(raw.get("relevance_factor", 1.0))
    except (TypeError, ValueError):
        rf = 1.0
    rf = max(0.05, min(1.0, rf))

    out = {
        "skipped": False,
        "relevance_factor": rf,
        "off_topic": bool(raw.get("off_topic")),
        "student_fulfills_assignment": bool(raw.get("student_fulfills_assignment")),
        "explanation": str(raw.get("explanation", "")).strip(),
        "submission_domain_guess": str(raw.get("submission_domain_guess", "")).strip(),
        "task_domain_guess": str(raw.get("task_domain_guess", "")).strip(),
    }
    try:
        cf = raw.get("confidence")
        if cf is not None:
            out["confidence"] = max(0.0, min(1.0, float(cf)))
    except (TypeError, ValueError):
        pass
    return out


def merge_task_alignment(
    programmatic_factor: float,
    programmatic_reasons: list[str],
    llm_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """LLM görev uyumu ile birleştirir; alakasız teslimde çarpanı doğrudan düşürür."""
    reasons = list(programmatic_reasons)
    out: dict[str, Any] = {
        "factor": max(0.05, min(1.0, float(programmatic_factor))),
        "reasons": reasons,
        "programmatic_factor": max(0.05, min(1.0, float(programmatic_factor))),
        "llm_factor": None,
        "llm_explanation": None,
        "llm_off_topic": False,
        "llm_skipped": True,
        "submission_domain_guess": None,
        "task_domain_guess": None,
    }

    if not llm_payload or llm_payload.get("skipped"):
        return out

    try:
        llm_raw = float(llm_payload.get("relevance_factor", 1.0))
    except (TypeError, ValueError):
        llm_raw = 1.0
    llm_raw = max(0.05, min(1.0, llm_raw))

    off = bool(llm_payload.get("off_topic"))
    fulfils = bool(llm_payload.get("student_fulfills_assignment", True))

    llm_f = llm_raw
    if off:
        llm_f = min(llm_f, 0.2)
    elif not fulfils:
        llm_f = min(llm_f, 0.3)
    elif llm_raw < 0.45:
        llm_f = min(llm_f, 0.35)
    llm_f = max(0.05, min(1.0, llm_f))

    out["llm_skipped"] = False
    out["llm_factor"] = llm_f
    out["factor"] = min(out["factor"], llm_f)
    out["submission_domain_guess"] = llm_payload.get("submission_domain_guess") or None
    out["task_domain_guess"] = llm_payload.get("task_domain_guess") or None

    expl = str(llm_payload.get("explanation", "") or "").strip()
    if expl:
        out["llm_explanation"] = expl

    out["llm_off_topic"] = off

    if off:
        if "llm_task_relevance_off_topic" not in reasons:
            reasons.append("llm_task_relevance_off_topic")
    elif not fulfils:
        if "llm_task_not_fulfilled" not in reasons:
            reasons.append("llm_task_not_fulfilled")
    elif llm_f <= 0.38:
        if "llm_low_task_fit" not in reasons:
            reasons.append("llm_low_task_fit")

    out["reasons"] = reasons
    return out
