"""Fresh E2E QA: Stack (LIFO) assignment — chatbot, rubric, 3 code variants, score consistency."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import chatbot_rubric_qa_run as base  # noqa: E402

API_BASE = base.API_BASE
ROOT = base.ROOT
DEMO_DIR = ROOT / "scripts" / "demo"
QA_DIR = ROOT / "artifacts" / "qa" / "scenario_stack"

CHATBOT_HINT = (DEMO_DIR / "stack_brief.txt").read_text(encoding="utf-8").strip()

COURSE_ID = base.COURSE_ID
COURSE_NAME = base.COURSE_NAME
COURSE_CODE = base.COURSE_CODE
COURSE_YEAR = base.COURSE_YEAR
TEACHER_EMAIL = base.TEACHER_EMAIL
TEACHER_PASSWORD = base.TEACHER_PASSWORD
TEACHER_ID = base.TEACHER_ID


def _score_suggestion(item: dict[str, Any]) -> int:
    text = " ".join(str(item.get(k, "")) for k in ("title", "summary", "description")).lower()
    score = 0
    for token in ("stack", "lifo", "push", "pop", "peek", "veri", "yapi", "sinif", "oop", "bos"):
        if token in text:
            score += 2
    for bad in ("csv", "banka", "api", "web", "flask", "django", "kelime", "frekans"):
        if bad in text:
            score -= 3
    return score


def _pick_best(suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(suggestions, key=_score_suggestion, reverse=True)[0]


def _load_demo(name: str) -> str:
    return (DEMO_DIR / name).read_text(encoding="utf-8")


def _rubric_earned(report: dict[str, Any]) -> tuple[int, int]:
    rubric = report.get("rubric", [])
    if not isinstance(rubric, list):
        return 0, 0
    earned = 0
    maximum = 0
    for row in rubric:
        if not isinstance(row, dict):
            continue
        earned += int(row.get("score", 0) or 0)
        maximum += int(row.get("maxScore", row.get("weight", 0)) or 0)
    return earned, maximum


def _agent_scores(report: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for agent in report.get("agents", []):
        if isinstance(agent, dict) and agent.get("id"):
            out[str(agent["id"])] = float(agent.get("score", 0) or 0)
    return out


def _positive_evidence_marked_error(report: dict[str, Any]) -> list[str]:
    import re

    positive = re.compile(
        r"dogru|basarili|uygun|temiz|iyi|guclu|eksiksiz|properly|correct|success",
        re.I,
    )
    bad: list[str] = []
    for line in report.get("evidence", []) or []:
        if not isinstance(line, dict):
            continue
        if line.get("severity") == "error" and positive.search(str(line.get("message", ""))):
            bad.append(str(line.get("message", ""))[:80])
    return bad


def _check_consistency(
    label: str,
    report: dict[str, Any],
    *,
    expected_relevant: bool,
    expected_security_risky: bool,
) -> dict[str, Any]:
    base_eval = base._evaluate_case(
        label,
        report,
        expected_relevant=expected_relevant,
        expected_security_risky=expected_security_risky,
    )
    issues: list[str] = []

    total = float(report.get("totalScore", 0) or 0)
    rubric_earned, rubric_max = _rubric_earned(report)
    if rubric_max and abs(rubric_max - 100) > 0:
        issues.append(f"rubrik max toplami {rubric_max} != 100")
    if rubric_earned and abs(rubric_earned - total) > 2:
        issues.append(f"rubrik satir toplami {rubric_earned} != totalScore {total}")

    agents = _agent_scores(report)
    core_ids = ("code_quality", "guideline", "security", "testing", "seniority")
    core_vals = [agents[k] for k in core_ids if k in agents]
    core_avg = sum(core_vals) / len(core_vals) if core_vals else 0.0

    if label == "uygun":
        if total < 55 and core_avg >= 70:
            issues.append(f"consensus collapse: total={total} core_avg={core_avg:.0f}")
        if total >= 60 and rubric_earned < 50:
            issues.append(f"uygun total yuksek ama rubrik dusuk: {rubric_earned}")

    if label == "alakasiz" and total > 55 and not base_eval.get("llm_off_topic"):
        issues.append(f"alakasiz ama skor yuksek: {total}")

    if label == "guvensiz":
        sec = agents.get("security", 100)
        if sec >= 70:
            issues.append(f"guvensiz kod ama security agent {sec}")

    pos_errors = _positive_evidence_marked_error(report)
    if pos_errors:
        issues.append(f"pozitif bulgu HATA olarak isaretli: {len(pos_errors)} adet")

    diagnostics = report.get("agentDiagnostics", {})
    llm_agents = []
    if isinstance(diagnostics, dict):
        for row in diagnostics.get("agents", []) or []:
            if isinstance(row, dict):
                llm_agents.append(
                    f"{row.get('id')}:{row.get('llm_status', '?')}"
                )

    consistency_ok = len(issues) == 0
    return {
        **base_eval,
        "rubric_earned": rubric_earned,
        "rubric_max": rubric_max,
        "core_agent_avg": round(core_avg, 1),
        "agent_scores": {k: round(v, 1) for k, v in agents.items()},
        "consistency_issues": issues,
        "consistency_ok": consistency_ok,
        "llm_agent_status": llm_agents,
        "passed": bool(base_eval.get("passed")) and consistency_ok,
    }


async def run_qa() -> dict[str, Any]:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        await base._wait_for_api(client)

        login = await client.post(
            f"{API_BASE}/api/teacher/login",
            json={"email": TEACHER_EMAIL, "password": TEACHER_PASSWORD},
        )
        if login.is_error:
            raise RuntimeError(f"Teacher login failed: {base._format_http_error(login)}")

        course_hint = f"{COURSE_NAME} ({COURSE_CODE}), {COURSE_YEAR}.sinif, {CHATBOT_HINT}"
        sug_resp = await client.post(
            f"{API_BASE}/api/faculty/assignment-assistant/suggestions",
            json={"course_hint": course_hint, "count": 5, "difficulty": "medium", "prefer_fresh": True},
        )
        sug_resp.raise_for_status()
        suggestions = sug_resp.json().get("suggestions", [])
        if not suggestions:
            raise RuntimeError("Chatbot oneri donmedi")

        picked = _pick_best(suggestions)
        title = str(picked.get("title", "")).strip()
        description = str(picked.get("description", "")).strip()

        ex_resp = await client.post(
            f"{API_BASE}/api/faculty/assignment-assistant/example",
            json={"assignment_title": title, "assignment_description": description},
        )
        ex_resp.raise_for_status()
        example = str(ex_resp.json().get("example", "")).strip()
        full_description = f"{description}\n\nOrnek Cikti:\n{example}" if example else description

        due_date = datetime(2026, 8, 1, 23, 59, tzinfo=timezone.utc).isoformat()
        assign_resp = await client.post(
            f"{API_BASE}/api/assignments",
            json={
                "course_id": COURSE_ID,
                "name": title,
                "description": full_description,
                "due_date": due_date,
            },
        )
        assign_resp.raise_for_status()
        assignment = assign_resp.json()
        assignment_id = str(assignment["id"])

        rubric_resp = await client.post(
            f"{API_BASE}/api/rubric/suggest",
            json={
                "assignment_title": title,
                "assignment_description": full_description,
                "report_language": "tr",
            },
        )
        rubric_resp.raise_for_status()
        criteria = rubric_resp.json().get("criteria", [])
        if not criteria:
            raise RuntimeError("Rubrik uretilemedi")

        upsert_resp = await client.post(
            f"{API_BASE}/api/rubrics/upsert",
            json={
                "assignment_id": assignment_id,
                "criteria": criteria,
                "status": "approved",
                "created_by": TEACHER_ID,
            },
        )
        upsert_resp.raise_for_status()

        meta = {
            "scenario": "stack_lifo",
            "started_at": started,
            "chatbot_hint": CHATBOT_HINT,
            "picked_suggestion": picked,
            "assignment_id": assignment_id,
        }
        (QA_DIR / "chatbot_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (QA_DIR / f"{assignment_id}_rubric.json").write_text(
            json.dumps({"criteria": criteria}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        cases = [
            ("uygun", f"{assignment_id}_uygun.py", _load_demo("stack_uygun.py"), True, False),
            ("alakasiz", f"{assignment_id}_alakasiz.py", _load_demo("stack_alakasiz.py"), False, False),
            ("guvensiz", f"{assignment_id}_guvensiz.py", _load_demo("stack_guvensiz.py"), True, True),
        ]
        for label, fname, code, _, _ in cases:
            (QA_DIR / fname).write_text(code, encoding="utf-8")

        student_no = base._qa_student_no()
        analysis_results: list[dict[str, Any]] = []
        for label, file_name, code, expected_relevant, expected_security_risky in cases:
            analyze_resp = await client.post(
                f"{API_BASE}/api/analyze",
                json={
                    "file_name": file_name,
                    "file_content": code,
                    "assignment_id": assignment_id,
                    "report_language": "tr",
                    "student_no": student_no,
                },
            )
            if analyze_resp.is_error:
                raise RuntimeError(
                    f"Analyze failed ({label}): {base._format_http_error(analyze_resp)}"
                )
            job_id = analyze_resp.json()["job_id"]
            report = await base._poll_job(client, job_id)
            evaluation = _check_consistency(
                label,
                report,
                expected_relevant=expected_relevant,
                expected_security_risky=expected_security_risky,
            )
            out_path = QA_DIR / f"{assignment_id}_{label}_analysis.json"
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            analysis_results.append(
                {
                    "label": label,
                    "evaluation": evaluation,
                    "report_path": str(out_path.relative_to(ROOT)),
                }
            )

        summary = {
            "scenario": "stack_lifo",
            "assignment_id": assignment_id,
            "assignment_title": title,
            "rubric_criteria_count": len(criteria),
            "analysis_results": analysis_results,
            "all_passed": all(r["evaluation"]["passed"] for r in analysis_results),
        }
        (QA_DIR / "qa_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary


async def main() -> int:
    try:
        summary = await run_qa()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["all_passed"] else 1
    except Exception as exc:
        print(f"Stack QA failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
