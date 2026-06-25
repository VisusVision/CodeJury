"""End-to-end Chatbot -> Rubric -> Agent QA runner for AgentGrade."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "artifacts" / "qa"
API_BASE = "http://127.0.0.1:8001"

CHATBOT_HINT = (
    "CSV dosyasından öğrenci adı ve not okuyup geçme/kalma durumunu hesaplayan, "
    "sonucu yeni bir CSV rapor dosyasına yazan CLI programı"
)

COURSE_ID = "20ed08b0-531f-40f0-844d-de166f9e1c8c"  # python programlama / pro101
COURSE_NAME = "python programlama"
COURSE_CODE = "pro101"
COURSE_YEAR = 3

TEACHER_EMAIL = "emre@gmail.com"
TEACHER_PASSWORD = "emre123"
TEACHER_ID = "a624f0e1-e305-4c85-9095-3ea8203cd729"

STUDENT_NO = "230501013"
STUDENT_TC = "11111111111"


def _qa_student_no() -> str:
    return f"qa{int(time.time()) % 1_000_000:06d}"


def _format_http_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        detail = body.get("detail") if isinstance(body, dict) else body
    except Exception:
        detail = resp.text[:500]
    return f"HTTP {resp.status_code}: {detail or resp.reason_phrase}"


async def _wait_for_api(client: httpx.AsyncClient, timeout_s: int = 90) -> None:
    deadline = time.time() + timeout_s
    last_error = "API health check timed out"
    while time.time() < deadline:
        try:
            resp = await client.get(f"{API_BASE}/api/health")
            if resp.status_code == 200:
                return
            last_error = _format_http_error(resp)
        except httpx.HTTPError as exc:
            last_error = str(exc) or repr(exc)
        await asyncio.sleep(2)
    raise RuntimeError(f"API not ready at {API_BASE}: {last_error}")


def _score_suggestion(item: dict[str, Any]) -> int:
    text = " ".join(
        str(item.get(k, "")) for k in ("title", "summary", "description")
    ).lower()
    hint = CHATBOT_HINT.lower()
    score = 0
    for token in ("csv", "dosya", "okuy", "rapor", "geç", "kal", "not", "cli", "geçme", "kalma"):
        if token in text:
            score += 2
    if "geçme/kalma" in text or "gecme/kalma" in text:
        score += 8
    if "rapor dosyası" in text or "rapor dosyasina" in text:
        score += 6
    # Hint-faithful generic templates (chatbot id 3–5) beat expanded LLM variants.
    if text.strip() == hint.strip() or hint.strip() in text:
        score += 12
    for bad in (
        "api", "veritaban", "oop", "sunum", "web sunucu", "flask", "django",
        "istatistik", "histogram", "ortalama", "en yüksek", "en düşük", "harf notu",
    ):
        if bad in text:
            score -= 5
    return score


def _pick_best_suggestion(suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(suggestions, key=_score_suggestion, reverse=True)
    return ranked[0]


def _build_uygun_code() -> str:
    return '''"""CSV not analizi - odevle uyumlu cozum."""

from __future__ import annotations

import csv
from pathlib import Path


PASS_THRESHOLD = 60


def read_scores(input_path: Path) -> list[dict[str, str]]:
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def summarize(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for row in rows:
        name = row.get("name", "").strip()
        score_text = row.get("score", "0").strip() or "0"
        score = int(score_text)
        status = "passed" if score >= PASS_THRESHOLD else "failed"
        summary.append({"name": name, "score": str(score), "status": status})
    return summary


def export_report(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "score", "status"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    input_path = Path("scores.csv")
    output_path = Path("report.csv")
    rows = read_scores(input_path)
    export_report(summarize(rows), output_path)
    print(f"{output_path} yazildi")


if __name__ == "__main__":
    main()
'''


def _build_alakasiz_code() -> str:
    return (ROOT / "samples" / "faktoriyel_odev.py").read_text(encoding="utf-8")


def _build_guvensiz_code() -> str:
    return (ROOT / "samples" / "rapor_export_guvensiz.py").read_text(encoding="utf-8")


def _extract_agent(report: dict[str, Any], agent_id: str) -> dict[str, Any]:
    agents = report.get("agents", [])
    if not isinstance(agents, list):
        return {}
    for agent in agents:
        if isinstance(agent, dict) and agent.get("id") == agent_id:
            return agent
    return {}


def _evaluate_case(
    label: str,
    report: dict[str, Any],
    *,
    expected_relevant: bool,
    expected_security_risky: bool = False,
) -> dict[str, Any]:
    align = report.get("taskAlignment", {}) if isinstance(report.get("taskAlignment"), dict) else {}
    align_factor = float(align.get("factor", 1.0) or 1.0)
    llm_off_topic = bool(align.get("llm_off_topic"))
    relevance_warning = bool(report.get("relevanceScoreWarning"))
    total_score = float(report.get("totalScore", 0) or 0)
    sec = _extract_agent(report, "security")
    sec_score = float(sec.get("score", 0) or 0)
    sec_summary = str(sec.get("summary", ""))

    if expected_relevant:
        relevance_ok = align_factor >= 0.55 and not llm_off_topic
    else:
        relevance_ok = align_factor <= 0.30 or llm_off_topic or relevance_warning or total_score <= 50

    if expected_security_risky:
        security_ok = sec_score < 70 or "HIGH" in sec_summary or "CRITICAL" in sec_summary
        score_ok = total_score <= 55
    elif expected_relevant:
        security_ok = sec_score >= 70 or total_score >= 60
        score_ok = total_score >= 60
    else:
        security_ok = True
        score_ok = total_score <= 50

    rubric = report.get("rubric", [])
    rubric_count_ok = isinstance(rubric, list) and len(rubric) >= 5

    return {
        "label": label,
        "total_score": round(total_score, 1),
        "alignment_factor": round(align_factor, 3),
        "llm_off_topic": llm_off_topic,
        "relevance_warning": relevance_warning,
        "security_score": round(sec_score, 1),
        "security_summary": sec_summary,
        "rubric_rows": len(rubric) if isinstance(rubric, list) else 0,
        "relevance_ok": relevance_ok,
        "score_ok": score_ok,
        "security_ok": security_ok,
        "rubric_count_ok": rubric_count_ok,
        "passed": relevance_ok and score_ok and security_ok and rubric_count_ok,
    }


async def _poll_job(client: httpx.AsyncClient, job_id: str, timeout_s: int = 600) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = await client.get(f"{API_BASE}/api/analyze/jobs/{job_id}")
        resp.raise_for_status()
        payload = resp.json()
        status = payload.get("status")
        if status == "completed":
            result = payload.get("result")
            if isinstance(result, dict):
                return result
            raise RuntimeError(f"Job completed without result: {job_id}")
        if status == "failed":
            raise RuntimeError(f"Job failed: {payload.get('error')}")
        await asyncio.sleep(2)
    raise TimeoutError(f"Analysis job timed out: {job_id}")


async def run_qa(*, include_guvensiz: bool = True) -> dict[str, Any]:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        await _wait_for_api(client)

        # Teacher login (sanity)
        login = await client.post(
            f"{API_BASE}/api/teacher/login",
            json={"email": TEACHER_EMAIL, "password": TEACHER_PASSWORD},
        )
        if login.is_error:
            raise RuntimeError(f"Teacher login failed: {_format_http_error(login)}")

        course_hint = (
            f"{COURSE_NAME} ({COURSE_CODE}), {COURSE_YEAR}.sinif, {CHATBOT_HINT}"
        )
        sug_resp = await client.post(
            f"{API_BASE}/api/faculty/assignment-assistant/suggestions",
            json={
                "course_hint": course_hint,
                "count": 5,
                "difficulty": "medium",
                "prefer_fresh": True,
            },
        )
        if sug_resp.is_error:
            raise RuntimeError(f"Chatbot suggestions failed: {_format_http_error(sug_resp)}")
        suggestions = sug_resp.json().get("suggestions", [])
        if not suggestions:
            raise RuntimeError("Chatbot oneri donmedi")

        picked = _pick_best_suggestion(suggestions)
        title = str(picked.get("title", "")).strip()
        description = str(picked.get("description", "")).strip()

        ex_resp = await client.post(
            f"{API_BASE}/api/faculty/assignment-assistant/example",
            json={
                "assignment_title": title,
                "assignment_description": description,
            },
        )
        ex_resp.raise_for_status()
        example = str(ex_resp.json().get("example", "")).strip()
        full_description = description
        if example:
            full_description = f"{description}\n\nOrnek Cikti:\n{example}"

        due_date = datetime(2026, 7, 15, 23, 59, tzinfo=timezone.utc).isoformat()
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

        # Persist artifacts
        meta = {
            "started_at": started,
            "chatbot_hint": CHATBOT_HINT,
            "course_hint": course_hint,
            "picked_suggestion": picked,
            "all_suggestions": suggestions,
            "example": example,
            "assignment": assignment,
            "assignment_id": assignment_id,
            "course_id": COURSE_ID,
        }
        (QA_DIR / "chatbot_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (QA_DIR / f"{assignment_id}_rubric.json").write_text(
            json.dumps({"criteria": criteria}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        uygun_code = _build_uygun_code()
        alakasiz_code = _build_alakasiz_code()
        guvensiz_code = _build_guvensiz_code()
        (QA_DIR / f"{assignment_id}_uygun.py").write_text(uygun_code, encoding="utf-8")
        (QA_DIR / f"{assignment_id}_alakasiz.py").write_text(alakasiz_code, encoding="utf-8")
        (QA_DIR / f"{assignment_id}_guvensiz.py").write_text(guvensiz_code, encoding="utf-8")

        cases = [
            ("uygun", f"{assignment_id}_uygun.py", uygun_code, True, False),
            ("alakasiz", f"{assignment_id}_alakasiz.py", alakasiz_code, False, False),
        ]
        if include_guvensiz:
            cases.append(
                ("guvensiz", f"{assignment_id}_guvensiz.py", guvensiz_code, True, True)
            )

        analysis_results: list[dict[str, Any]] = []
        student_no = _qa_student_no()
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
                    f"Analyze request failed for {label}: {_format_http_error(analyze_resp)}"
                )
            job_id = analyze_resp.json()["job_id"]
            report = await _poll_job(client, job_id)
            evaluation = _evaluate_case(
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
                    "file_name": file_name,
                    "evaluation": evaluation,
                    "report_path": str(out_path.relative_to(ROOT)),
                }
            )

        summary = {
            "assignment_id": assignment_id,
            "assignment_title": title,
            "rubric_criteria_count": len(criteria),
            "rubric_total_score": sum(int(c.get("max_score", 0)) for c in criteria),
            "analysis_results": analysis_results,
            "all_passed": all(r["evaluation"]["passed"] for r in analysis_results),
        }
        (QA_DIR / "qa_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary


def _write_markdown_report(summary: dict[str, Any]) -> None:
    lines = [
        "# Chatbot → Rubrik → Ajan QA Raporu",
        "",
        f"**Tarih:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Ödev",
        "",
        f"- **ID:** `{summary['assignment_id']}`",
        f"- **Başlık:** {summary['assignment_title']}",
        f"- **Rubrik kriter sayısı:** {summary['rubric_criteria_count']}",
        f"- **Rubrik toplam puan:** {summary['rubric_total_score']}",
        "",
        "## Analiz Sonuçları",
        "",
        "| Kod | Skor | Alignment | Off-topic | Güvenlik | Sonuç |",
        "|-----|------|-----------|-----------|----------|-------|",
    ]
    for row in summary["analysis_results"]:
        ev = row["evaluation"]
        status = "PASS" if ev["passed"] else "FAIL"
        lines.append(
            f"| {ev['label']} | {ev['total_score']} | {ev['alignment_factor']} | "
            f"{'evet' if ev['llm_off_topic'] or ev['relevance_warning'] else 'hayir'} | "
            f"{ev['security_score']} | **{status}** |"
        )

    lines.extend(
        [
            "",
            "## Beklenti Matrisi",
            "",
            "- **uygun:** skor ≥ 60, alignment ≥ 0.55, off-topic yok",
            "- **alakasiz:** skor ≤ 50 veya düşük alignment / uyarı",
            "- **guvensiz:** konuya uygun ama güvenlik skoru düşük",
            "",
            f"## Genel Sonuç: **{'PASS' if summary['all_passed'] else 'FAIL'}**",
            "",
            "## Ekran Görüntüleri",
            "",
            "- `artifacts/qa/01_faculty_assignments.png` — öğretmen paneli giriş",
            "",
            "## Meta Dosyalar",
            "",
            "- `artifacts/qa/chatbot_meta.json`",
            "- `artifacts/qa/qa_summary.json`",
            "- `artifacts/qa/*_analysis.json`",
        ]
    )
    (QA_DIR / "chatbot_rubric_agent_report.md").write_text("\n".join(lines), encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-guvensiz", action="store_true")
    args = parser.parse_args()
    try:
        summary = await run_qa(include_guvensiz=not args.no_guvensiz)
        _write_markdown_report(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["all_passed"] else 1
    except Exception as exc:
        detail = str(exc).strip() or repr(exc)
        print(f"QA run failed: {type(exc).__name__}: {detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
