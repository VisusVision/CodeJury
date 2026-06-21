"""Real-world validation: chatbot diversity + evidence fields smoke."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8001"
OUT = ROOT / "artifacts" / "qa" / "realworld_smoke.json"

TEACHER_EMAIL = "emre@gmail.com"
TEACHER_PASSWORD = "emre123"
ASSIGNMENT_ID = "3dd28399-01d9-4bcf-9aa8-7827437af8ff"
STUDENT_NO = "230501013"


async def _poll(client: httpx.AsyncClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        resp = await client.get(f"{API}/api/analyze/jobs/{job_id}")
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") == "completed":
            return payload["result"]
        if payload.get("status") == "failed":
            raise RuntimeError(payload.get("error"))
        await asyncio.sleep(2)
    raise TimeoutError(job_id)


async def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    summary: dict = {"checks": []}

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        # 1) Chatbot diversity
        login = await client.post(
            f"{API}/api/teacher/login",
            json={"email": TEACHER_EMAIL, "password": TEACHER_PASSWORD},
        )
        login.raise_for_status()

        sug = await client.post(
            f"{API}/api/faculty/assignment-assistant/suggestions",
            json={
                "course_hint": "python programlama (pro101), 3.sinif, CSV dosyasindan not okuyup rapor yazan CLI",
                "count": 5,
                "difficulty": "medium",
                "prefer_fresh": True,
            },
        )
        sug.raise_for_status()
        suggestions = sug.json().get("suggestions", [])
        titles = [s.get("title", "") for s in suggestions if isinstance(s, dict)]
        diversity_ok = len(suggestions) >= 3 and len(set(titles)) == len(titles)
        summary["checks"].append({
            "name": "chatbot_diversity",
            "passed": diversity_ok,
            "count": len(suggestions),
            "unique_titles": len(set(titles)),
        })

        # 2) Uygun code analysis with evidence fields
        uygun_path = ROOT / "artifacts" / "qa" / f"{ASSIGNMENT_ID}_uygun.py"
        if not uygun_path.exists():
            from scripts.chatbot_rubric_qa_run import _build_uygun_code

            code = _build_uygun_code()
        else:
            code = uygun_path.read_text(encoding="utf-8")

        analyze = await client.post(
            f"{API}/api/analyze",
            json={
                "file_name": f"{ASSIGNMENT_ID}_uygun.py",
                "file_content": code,
                "assignment_id": ASSIGNMENT_ID,
                "report_language": "tr",
                "student_no": STUDENT_NO,
            },
        )
        analyze.raise_for_status()
        report = await _poll(client, analyze.json()["job_id"])

        testing = next((a for a in report.get("agents", []) if a.get("id") == "testing"), {})
        evidence = report.get("evidence", [])
        rejected = report.get("rejectedClaims", [])
        file_level = [e for e in evidence if isinstance(e, dict) and (e.get("line") == 0 or e.get("scope") == "file")]
        p0_ok = float(report.get("totalScore") or 0) >= 60
        no_fnf = "FileNotFound" not in str(testing.get("summary", ""))

        summary["checks"].append({
            "name": "p0_uygun_analysis",
            "passed": p0_ok and no_fnf,
            "total_score": report.get("totalScore"),
            "testing_summary": testing.get("summary"),
            "file_not_found": not no_fnf,
        })
        summary["checks"].append({
            "name": "p1_evidence_api",
            "passed": "rejectedClaims" in report,
            "evidence_lines": len(evidence),
            "file_level_evidence": len(file_level),
            "rejected_claims": len(rejected),
        })

    summary["all_passed"] = all(c["passed"] for c in summary["checks"])
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
