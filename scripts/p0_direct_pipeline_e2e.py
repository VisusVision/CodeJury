"""Direct pipeline E2E for P0 (fresh Python process, real Ollama)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.chatbot_rubric_qa_run import _build_uygun_code, API_BASE, TEACHER_EMAIL, TEACHER_PASSWORD
import httpx

CSV_BRIEF = (
    "CSV dosyasindan ogrenci adi ve not okuyup gecme/kalma durumunu hesaplayan, "
    "sonucu yeni bir CSV rapor dosyasina yazan CLI programi"
)


async def main() -> int:
    from frontend.backend.main import run_analysis_pipeline

    async with httpx.AsyncClient(timeout=30.0) as client:
        login = await client.post(
            f"{API_BASE}/api/teacher/login",
            json={"email": TEACHER_EMAIL, "password": TEACHER_PASSWORD},
        )
        login.raise_for_status()

    assignment_id = sys.argv[1] if len(sys.argv) > 1 else "3dd28399-01d9-4bcf-9aa8-7827437af8ff"
    async with httpx.AsyncClient(timeout=30.0) as client:
        rubric_resp = await client.get(f"{API_BASE}/api/rubrics/by-assignment/{assignment_id}")
        rubric_resp.raise_for_status()
        criteria = rubric_resp.json().get("criteria", [])

    report = await run_analysis_pipeline(
        f"{assignment_id}_uygun.py",
        _build_uygun_code(),
        assignment_brief=CSV_BRIEF,
        faculty_rubric_criteria=criteria,
        report_language="tr",
    )

    testing = next((a for a in report.get("agents", []) if a.get("id") == "testing"), {})
    summary = {
        "mode": "direct_pipeline",
        "total_score": report.get("totalScore"),
        "alignment_factor": (report.get("taskAlignment") or {}).get("factor"),
        "testing_score": testing.get("score"),
        "testing_summary": testing.get("summary"),
        "file_not_found": "FileNotFound" in str(testing.get("summary", "")),
        "passed_p0": float(report.get("totalScore") or 0) >= 60,
    }
    out = ROOT / "artifacts" / "qa" / "after" / "p0_direct_pipeline.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed_p0"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
