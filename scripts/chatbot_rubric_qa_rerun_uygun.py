"""Re-run uygun analysis for existing QA assignment."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from chatbot_rubric_qa_run import (
    API_BASE,
    QA_DIR,
    STUDENT_NO,
    _build_uygun_code,
    _evaluate_case,
    _poll_job,
)

ASSIGNMENT_ID = "a4b2feb3-56ab-434c-9c87-921af9a6e661"


async def main() -> None:
    code = _build_uygun_code()
    file_name = f"{ASSIGNMENT_ID}_uygun.py"
    (QA_DIR / file_name).write_text(code, encoding="utf-8")

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        resp = await client.post(
            f"{API_BASE}/api/analyze",
            json={
                "file_name": file_name,
                "file_content": code,
                "assignment_id": ASSIGNMENT_ID,
                "report_language": "tr",
                "student_no": STUDENT_NO,
            },
        )
        resp.raise_for_status()
        report = await _poll_job(client, resp.json()["job_id"])
        evaluation = _evaluate_case("uygun", report, expected_relevant=True)
        out = QA_DIR / f"{ASSIGNMENT_ID}_uygun_analysis.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(evaluation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
