from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


BASE_URL = "http://127.0.0.1:8001"


def request_json(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 900) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else body
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def create_context() -> dict[str, str]:
    stamp = int(time.time())
    email = f"qa-edge-{stamp}@agentgrade.local"
    status, teacher = request_json(
        "POST",
        "/api/teacher/register",
        {"first_name": "QA", "last_name": "Edges", "email": email, "password": "qa-pass-123"},
    )
    assert_true(status == 200, f"teacher register {status}: {teacher}")
    status, dept = request_json(
        "POST",
        "/api/departments",
        {"name": f"QA Edge Bolum {stamp}", "created_by": teacher["id"]},
    )
    assert_true(status == 200, f"department {status}: {dept}")
    status, course = request_json(
        "POST",
        "/api/courses",
        {
            "name": f"QA Edge Programlama {stamp}",
            "code": f"QE{stamp % 100000}",
            "class_year": 2,
            "department_id": dept["id"],
        },
    )
    assert_true(status == 200, f"course {status}: {course}")
    return {"teacher_id": str(teacher["id"]), "course_id": str(course["id"])}


def create_assignment(ctx: dict[str, str]) -> str:
    status, assignment = request_json(
        "POST",
        "/api/assignments",
        {
            "course_id": ctx["course_id"],
            "name": "QA Edge Log Dosyasi Analiz Araci",
            "description": (
                "Python ile log dosyasini komut satiri argumani olarak okuyup DEBUG, INFO, WARNING, "
                "ERROR ve CRITICAL seviyelerini sayan; ERROR/CRITICAL satirlarini raporlayan CLI uygulamasi yazin."
            ),
        },
        timeout=300,
    )
    assert_true(status == 200, f"assignment {status}: {assignment}")
    return str(assignment["id"])


def upsert_rubric(ctx: dict[str, str], assignment_id: str) -> None:
    criteria = [
        {"name": "Log Okuma", "description": "Dosyayi komut satiri argumaniyla okuyup satirlari isler.", "max_score": 10},
        {"name": "Seviye Sayimi", "description": "DEBUG, INFO, WARNING, ERROR ve CRITICAL sayimlarini dogru yapar.", "max_score": 10},
        {"name": "Hata Raporlama", "description": "ERROR ve CRITICAL satirlarini ayrica raporlar.", "max_score": 10},
        {"name": "Fonksiyonel Tasarim", "description": "Is mantigini test edilebilir fonksiyonlara ayirir.", "max_score": 10},
        {"name": "Kenar Durumlar", "description": "Bos satir ve bilinmeyen seviye gibi durumlari guvenli ele alir.", "max_score": 10},
        {"name": "CLI Davranisi", "description": "Eksik argumanda anlasilir kullanim mesaji verir.", "max_score": 10},
        {"name": "Kod Okunabilirligi", "description": "Isimler ve akis okunabilir, gereksiz karmasiklik yoktur.", "max_score": 10},
        {"name": "Guvenlik", "description": "Gereksiz komut calistirma, secret veya riskli dosya islemi yoktur.", "max_score": 10},
        {"name": "Performans", "description": "Dosyayi makul bellek ve sureyle isler.", "max_score": 10},
        {"name": "Cikti Kalitesi", "description": "Ozet ve hata satirlari anlasilir formatta uretilir.", "max_score": 10},
    ]
    status, body = request_json(
        "POST",
        "/api/rubrics/upsert",
        {
            "assignment_id": assignment_id,
            "criteria": criteria,
            "status": "approved",
            "created_by": ctx["teacher_id"],
        },
    )
    assert_true(status == 200, f"rubric upsert {status}: {body}")


def analyze(assignment_id: str, name: str, code: str) -> dict[str, Any]:
    status, body = request_json(
        "POST",
        "/api/analyze",
        {
            "file_name": name,
            "file_content": code,
            "assignment_id": assignment_id,
            "report_language": "tr",
        },
        timeout=1200,
    )
    assert_true(status == 200, f"analyze {name} {status}: {body}")
    return body


def score(body: dict[str, Any]) -> float:
    return float(body.get("totalScore", body.get("final_score", 0)) or 0)


def agent(body: dict[str, Any], key: str) -> dict[str, Any]:
    agents = body.get("agents")
    if isinstance(agents, dict):
        return agents.get(key, {})
    if isinstance(agents, list):
        for item in agents:
            if isinstance(item, dict) and item.get("id") == key:
                return item
    return {}


def main() -> int:
    ctx = create_context()
    assignment_id = create_assignment(ctx)
    upsert_rubric(ctx, assignment_id)

    matching_code = r'''
from collections import Counter
import sys

def summarize(lines):
    counts = Counter()
    important = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        level = line.split(":", 1)[0].upper()
        if level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            counts[level] += 1
            if level in {"ERROR", "CRITICAL"}:
                important.append(line)
    return counts, important

def main(path):
    with open(path, encoding="utf-8") as handle:
        counts, important = summarize(handle)
    for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        print(f"{level}: {counts.get(level, 0)}")
    for line in important:
        print(line)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: log_analyzer.py FILE")
    main(sys.argv[1])
'''

    off_topic_code = r'''
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

print(fibonacci(8))
'''

    syntax_error_code = "def broken(:\n    pass\n"

    risky_code = r'''
api_key = "abcdefghijklmnopqrstuvwxyz123456"
password = "hardcoded-password"
def summarize(lines):
    return {"INFO": len(lines)}, []
'''

    cases: list[tuple[str, dict[str, Any]]] = []
    cases.append(("matching", analyze(assignment_id, "log_analyzer.py", matching_code)))
    cases.append(("off_topic", analyze(assignment_id, "fibonacci.py", off_topic_code)))
    cases.append(("syntax_error", analyze(assignment_id, "broken.py", syntax_error_code)))
    cases.append(("risky", analyze(assignment_id, "risky.py", risky_code)))

    report = []
    for name, body in cases:
        report.append(
            {
                "case": name,
                "score": score(body),
                "taskAlignment": body.get("taskAlignment"),
                "security": agent(body, "security"),
                "testing": agent(body, "testing"),
                "rubricRows": len(body.get("rubric", []) if isinstance(body.get("rubric"), list) else []),
            }
        )

    by_name = {name: body for name, body in cases}
    matching_score = score(by_name["matching"])
    off_topic_score = score(by_name["off_topic"])
    syntax_score = score(by_name["syntax_error"])
    risky_score = score(by_name["risky"])

    assert_true(matching_score >= 55, f"matching score too low: {matching_score}")
    assert_true(off_topic_score <= min(55, matching_score - 15), f"off-topic not penalized enough: {off_topic_score} vs {matching_score}")
    assert_true(syntax_score <= 25, f"syntax error should be hard capped: {syntax_score}")
    assert_true(risky_score <= 70, f"critical security should be capped: {risky_score}")

    risky_security = agent(by_name["risky"], "security")
    risky_security_blob = json.dumps(risky_security, ensure_ascii=False).lower()
    assert_true(
        "critical" in risky_security_blob or "high" in risky_security_blob or risky_security.get("score", 100) <= 70,
        f"risky security agent did not flag risk: {risky_security}",
    )

    syntax_test = agent(by_name["syntax_error"], "testing")
    syntax_test_blob = json.dumps(syntax_test, ensure_ascii=False).lower()
    assert_true(
        "derleme hatasi" in syntax_test_blob or syntax_test.get("score", 100) <= 25,
        f"syntax test agent did not flag failure: {syntax_test}",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
