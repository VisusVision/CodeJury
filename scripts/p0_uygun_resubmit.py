"""Re-submit uygun CSV code against an existing assignment (P0 E2E smoke)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8001"

# Latest QA assignment from p0 e2e run
DEFAULT_ASSIGNMENT_ID = "3dd28399-01d9-4bcf-9aa8-7827437af8ff"
STUDENT_NO = "230501013"


def _uygun_code() -> str:
    path = ROOT / "artifacts" / "qa" / f"{DEFAULT_ASSIGNMENT_ID}_uygun.py"
    if path.exists():
        return path.read_text(encoding="utf-8")
    from scripts.chatbot_rubric_qa_run import _build_uygun_code

    return _build_uygun_code()


async def _poll(client: httpx.AsyncClient, job_id: str, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = await client.get(f"{API}/api/analyze/jobs/{job_id}")
        resp.raise_for_status()
        payload = resp.json()
        status = payload.get("status")
        if status == "completed":
            return payload["result"]
        if status == "failed":
            raise RuntimeError(payload.get("error"))
        await asyncio.sleep(2)
    raise TimeoutError(job_id)


async def main() -> int:
    assignment_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ASSIGNMENT_ID
    code = _uygun_code()
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        for _ in range(60):
            try:
                health = await client.get(f"{API}/api/health")
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
        else:
            print("API not ready", file=sys.stderr)
            return 2

        resp = await client.post(
            f"{API}/api/analyze",
            json={
                "file_name": f"{assignment_id}_uygun.py",
                "file_content": code,
                "assignment_id": assignment_id,
                "report_language": "tr",
                "student_no": STUDENT_NO,
            },
        )
        resp.raise_for_status()
        job_id = resp.json()["job_id"]
        report = await _poll(client, job_id)

    testing = next((a for a in report.get("agents", []) if a.get("id") == "testing"), {})
    summary = {
        "assignment_id": assignment_id,
        "total_score": report.get("totalScore"),
        "alignment_factor": (report.get("taskAlignment") or {}).get("factor"),
        "testing_score": testing.get("score"),
        "testing_summary": testing.get("summary"),
        "passed_p0": float(report.get("totalScore") or 0) >= 60,
    }
    out = ROOT / "artifacts" / "qa" / "after" / "p0_uygun_resubmit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed_p0"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
