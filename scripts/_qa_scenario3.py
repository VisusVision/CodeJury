"""One-off scenario-3 QA runner: OOP bank account class.

Reuses helpers from chatbot_rubric_qa_run with a fresh OOP topic to judge the
hybrid (coder->Ollama, general->NIM/DeepSeek) setup.
"""

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
QA_DIR = ROOT / "artifacts" / "qa" / "scenario3"

CHATBOT_HINT = (
    "Nesne tabanli (OOP) bir banka hesabi sinifi tasarlayin: para yatirma, para cekme ve "
    "bakiye sorgulama islemleri olsun; yetersiz bakiye durumunda ozel bir istisna (exception) "
    "firlatsin ve negatif/sifir tutarlari reddetsin."
)

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
    for token in ("banka", "hesap", "sinif", "nesne", "oop", "bakiye", "para", "cek", "yatir", "istisna"):
        if token in text:
            score += 2
    for bad in ("csv", "kelime", "frekans", "api", "web", "flask", "django"):
        if bad in text:
            score -= 3
    return score


def _pick_best(suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(suggestions, key=_score_suggestion, reverse=True)[0]


def _uygun_code() -> str:
    return '''"""Banka hesabi - OOP odevle uyumlu cozum."""

from __future__ import annotations


class InsufficientFundsError(Exception):
    """Bakiye yetersiz oldugunda firlatilir."""


class BankAccount:
    def __init__(self, owner: str, balance: float = 0.0) -> None:
        self.owner = owner
        self._balance = balance

    @property
    def balance(self) -> float:
        return self._balance

    def deposit(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("Yatirilacak tutar pozitif olmalidir")
        self._balance += amount

    def withdraw(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("Cekilecek tutar pozitif olmalidir")
        if amount > self._balance:
            raise InsufficientFundsError("Yetersiz bakiye")
        self._balance -= amount


def main() -> None:
    account = BankAccount("Ali", 100.0)
    account.deposit(50)
    account.withdraw(30)
    print(f"{account.owner} bakiye: {account.balance}")


if __name__ == "__main__":
    main()
'''


def _alakasiz_code() -> str:
    return (ROOT / "samples" / "faktoriyel_odev.py").read_text(encoding="utf-8")


def _guvensiz_code() -> str:
    return '''"""Banka hesabi - guvensiz surum (kod enjeksiyonu)."""

import os


class BankAccount:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance

    def run_command(self, cmd):
        # Kullanici girdisini dogrudan eval'e veriyor -> kod enjeksiyonu.
        return eval(cmd)

    def withdraw(self, amount):
        self.balance -= amount  # bakiye kontrolu yok


if __name__ == "__main__":
    acc = BankAccount("Veli", 100)
    os.system("echo " + acc.owner)
    print(acc.run_command(input("islem: ")))
'''


async def run() -> dict[str, Any]:
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
        sug = await client.post(
            f"{API_BASE}/api/faculty/assignment-assistant/suggestions",
            json={"course_hint": course_hint, "count": 5, "difficulty": "medium", "prefer_fresh": True},
        )
        if sug.is_error:
            raise RuntimeError(f"Suggestions failed: {base._format_http_error(sug)}")
        suggestions = sug.json().get("suggestions", [])
        if not suggestions:
            raise RuntimeError("Oneri donmedi")
        picked = _pick_best(suggestions)
        title = str(picked.get("title", "")).strip()
        description = str(picked.get("description", "")).strip()

        ex = await client.post(
            f"{API_BASE}/api/faculty/assignment-assistant/example",
            json={"assignment_title": title, "assignment_description": description, "course_hint": course_hint},
        )
        ex.raise_for_status()
        example = str(ex.json().get("example", "")).strip()
        full_description = f"{description}\n\nOrnek Cikti:\n{example}" if example else description

        due = datetime(2026, 7, 25, 23, 59, tzinfo=timezone.utc).isoformat()
        assign = await client.post(
            f"{API_BASE}/api/assignments",
            json={"course_id": COURSE_ID, "name": title, "description": full_description, "due_date": due},
        )
        assign.raise_for_status()
        assignment = assign.json()
        assignment_id = str(assignment["id"])

        rub = await client.post(
            f"{API_BASE}/api/rubric/suggest",
            json={"assignment_title": title, "assignment_description": full_description, "report_language": "tr"},
        )
        rub.raise_for_status()
        criteria = rub.json().get("criteria", [])
        if not criteria:
            raise RuntimeError("Rubrik uretilemedi")

        up = await client.post(
            f"{API_BASE}/api/rubrics/upsert",
            json={"assignment_id": assignment_id, "criteria": criteria, "status": "approved", "created_by": TEACHER_ID},
        )
        up.raise_for_status()

        meta = {
            "started_at": started,
            "chatbot_hint": CHATBOT_HINT,
            "course_hint": course_hint,
            "picked_suggestion": picked,
            "all_suggestions": suggestions,
            "example": example,
            "assignment": assignment,
            "assignment_id": assignment_id,
        }
        (QA_DIR / "chatbot_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (QA_DIR / f"{assignment_id}_rubric.json").write_text(
            json.dumps({"criteria": criteria}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        codes = {
            "uygun": _uygun_code(),
            "alakasiz": _alakasiz_code(),
            "guvensiz": _guvensiz_code(),
        }
        for label, code in codes.items():
            (QA_DIR / f"{assignment_id}_{label}.py").write_text(code, encoding="utf-8")

        cases = [
            ("uygun", codes["uygun"], True, False),
            ("alakasiz", codes["alakasiz"], False, False),
            ("guvensiz", codes["guvensiz"], True, True),
        ]

        results: list[dict[str, Any]] = []
        student_no = base._qa_student_no()
        for label, code, expected_relevant, expected_security_risky in cases:
            ana = await client.post(
                f"{API_BASE}/api/analyze",
                json={
                    "file_name": f"{assignment_id}_{label}.py",
                    "file_content": code,
                    "assignment_id": assignment_id,
                    "report_language": "tr",
                    "student_no": student_no,
                },
            )
            if ana.is_error:
                raise RuntimeError(f"Analyze failed for {label}: {base._format_http_error(ana)}")
            report = await base._poll_job(client, ana.json()["job_id"])
            evaluation = base._evaluate_case(
                label, report,
                expected_relevant=expected_relevant,
                expected_security_risky=expected_security_risky,
            )
            (QA_DIR / f"{assignment_id}_{label}_analysis.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            results.append({"label": label, "evaluation": evaluation})

        summary = {
            "scenario": "OOP banka hesabi sinifi",
            "assignment_id": assignment_id,
            "assignment_title": title,
            "rubric_criteria_count": len(criteria),
            "rubric_total_score": sum(int(c.get("max_score", 0)) for c in criteria),
            "analysis_results": results,
            "all_passed": all(r["evaluation"]["passed"] for r in results),
        }
        (QA_DIR / "qa_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary


async def main() -> int:
    try:
        summary = await run()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["all_passed"] else 1
    except Exception as exc:
        print(f"Scenario3 QA failed: {type(exc).__name__}: {str(exc).strip() or repr(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
