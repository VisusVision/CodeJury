"""Chatbot -> rubric -> full agent pipeline QA on local coder model (in-process)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "artifacts" / "qa" / "e2e_coder"
sys.path.insert(0, str(ROOT))

CHATBOT_HINT = (
    "CSV dosyasından öğrenci adı ve not okuyup geçme/kalma durumunu hesaplayan, "
    "sonucu yeni bir CSV rapor dosyasına yazan CLI programı"
)


def _force_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip()
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_GENERAL_PROVIDER"] = "ollama"
    os.environ["LLM_CODER_PROVIDER"] = "ollama"
    os.environ["OLLAMA_ENABLED"] = "true"
    os.environ["OLLAMA_GENERAL_MODEL"] = "qwen2.5-coder:14b-instruct-q6_K"
    os.environ["OLLAMA_CODER_MODEL"] = "qwen2.5-coder:14b-instruct-q6_K"
    os.environ["DEMO_MODE"] = "0"


def _score_suggestion(item: dict) -> int:
    text = " ".join(str(item.get(k, "")) for k in ("title", "summary", "description")).lower()
    hint = CHATBOT_HINT.lower()
    score = 0
    for token in ("csv", "dosya", "okuy", "rapor", "geç", "kal", "not", "cli"):
        if token in text:
            score += 2
    if text.strip() == hint.strip() or hint.strip() in text:
        score += 12
    for bad in ("api", "veritaban", "oop", "sunum", "web sunucu", "flask"):
        if bad in text:
            score -= 5
    return score


def _uygun_code() -> str:
    return (ROOT / "samples" / "rapor_export_uygun.py").read_text(encoding="utf-8")


def _alakasiz_code() -> str:
    return (ROOT / "samples" / "faktoriyel_odev.py").read_text(encoding="utf-8")


def _guvensiz_code() -> str:
    return (ROOT / "samples" / "rapor_export_guvensiz.py").read_text(encoding="utf-8")


def _agent_map(report: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in report.get("agents") or []:
        if isinstance(row, dict) and row.get("id"):
            try:
                out[str(row["id"])] = float(row.get("score", 0) or 0)
            except (TypeError, ValueError):
                pass
    return out


def _evaluate(label: str, report: dict, *, relevant: bool, risky: bool = False) -> dict:
    align = report.get("taskAlignment") or {}
    factor = float(align.get("factor", 0) or 0)
    off = bool(align.get("llm_off_topic"))
    total = float(report.get("totalScore", 0) or 0)
    agents = _agent_map(report)
    sec = agents.get("security", 100.0)
    ta = agents.get("testing", 0.0)

    if relevant and not risky:
        ok = factor >= 0.55 and not off and total >= 55 and sec >= 60
    elif not relevant:
        ok = (factor <= 0.35 or off or total <= 50)
    else:
        ok = total <= 55 and sec < 75

    return {
        "label": label,
        "total": round(total, 1),
        "align": round(factor, 3),
        "off_topic": off,
        "testing": ta,
        "security": sec,
        "agents": agents,
        "passed": ok,
    }


async def main() -> int:
    _force_env()
    QA_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.time()

    from backend.core.config import settings
    from frontend.backend.main import (
        AssignmentAssistantSuggestionsRequest,
        RubricSuggestionRequest,
        assignment_assistant_suggestions,
        suggest_rubric,
        run_analysis_pipeline,
    )

    print(
        f"[e2e] LLM general={settings.ollama_general_model} "
        f"coder={settings.ollama_coder_model} provider={settings.llm_provider}",
        flush=True,
    )

    # 1) Chatbot
    print("[e2e] 1/5 chatbot suggestions...", flush=True)
    sug = await assignment_assistant_suggestions(
        AssignmentAssistantSuggestionsRequest(
            course_hint=f"python programlama (pro101), 3. sinif. {CHATBOT_HINT}",
            count=5,
            difficulty="medium",
            prefer_fresh=True,
        )
    )
    suggestions = sug.get("suggestions") or []
    if not suggestions:
        print("FAIL: chatbot bos", flush=True)
        return 1
    picked = max(suggestions, key=_score_suggestion)
    title = str(picked.get("title", "")).strip()
    description = str(picked.get("description", "")).strip()
    print(f"[e2e] picked: {title[:80]}", flush=True)

    # 2) Rubric
    print("[e2e] 2/5 rubric suggest...", flush=True)
    rub = await suggest_rubric(
        RubricSuggestionRequest(
            assignment_title=title,
            assignment_description=description,
            report_language="tr",
        )
    )
    criteria = rub.get("criteria") or []
    if len(criteria) < 5:
        print("FAIL: rubric yetersiz", flush=True)
        return 1
    rubric_total = sum(int(c.get("max_score", 0) or 0) for c in criteria)
    print(f"[e2e] rubric: {len(criteria)} kriter, toplam={rubric_total}", flush=True)

    brief = description
    faculty = [
        {
            "name": str(c.get("name", "")),
            "description": str(c.get("description", "")),
            "max_score": int(c.get("max_score", 0) or 0),
        }
        for c in criteria
    ]

    # 3-5) Analysis cases
    cases = [
        ("uygun", _uygun_code(), True, False),
        ("alakasiz", _alakasiz_code(), False, False),
        ("guvensiz", _guvensiz_code(), True, True),
    ]
    analysis_rows: list[dict] = []
    for idx, (label, code, relevant, risky) in enumerate(cases, start=3):
        print(f"[e2e] {idx}/5 analyze {label}...", flush=True)
        t_case = time.time()
        report = await run_analysis_pipeline(
            f"qa_{label}.py",
            code,
            assignment_brief=brief,
            faculty_rubric_criteria=faculty,
            report_language="tr",
        )
        ev = _evaluate(label, report, relevant=relevant, risky=risky)
        ev["elapsed_s"] = round(time.time() - t_case, 1)
        analysis_rows.append({"evaluation": ev, "report": report})
        out = QA_DIR / f"{label}_analysis.json"
        out.write_text(json.dumps({"evaluation": ev, "report": report}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[e2e]   {label}: total={ev['total']} align={ev['align']} "
            f"TA={ev['testing']} SC={ev['security']} -> {'PASS' if ev['passed'] else 'FAIL'} ({ev['elapsed_s']}s)",
            flush=True,
        )

    summary = {
        "started_at": started,
        "elapsed_s": round(time.time() - t0, 1),
        "llm": {
            "general_model": settings.ollama_general_model,
            "coder_model": settings.ollama_coder_model,
            "provider": settings.llm_provider,
        },
        "assignment_title": title,
        "assignment_description": description,
        "rubric_criteria_count": len(criteria),
        "rubric_total_score": rubric_total,
        "chatbot_suggestions": suggestions,
        "analysis": [row["evaluation"] for row in analysis_rows],
        "all_passed": all(row["evaluation"]["passed"] for row in analysis_rows),
    }
    (QA_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
