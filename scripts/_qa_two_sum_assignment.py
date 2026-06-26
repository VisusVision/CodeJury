from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend.backend.main import run_analysis_pipeline


ASSIGNMENT_BRIEF = """\
Python ile Two Sum cozumunu yazin.

Standart girdiden ilk satirda hedef toplam T, ikinci satirda bosluklarla ayrilmis tamsayi listesi alinir.
Listedeki iki farkli elemanin toplami T ediyorsa bu elemanlarin indekslerini kucukten buyuge yazdirin.
Eslesen cift yoksa YOK yazdirin.

Beklenen algoritma: dict/set tabanli tek gecis O(n). Ic ice dongu O(n^2) cozum beklenenden daha yavas kabul edilir.
"""

RUBRIC = [
    {
        "name": "Girdi ve cikti formati",
        "description": "T ve sayi listesini stdin'den okur; indeksleri veya YOK sonucunu istenen formatta yazar.",
        "weight": 25,
    },
    {
        "name": "Dogru eslesme",
        "description": "Iki farkli eleman kullanir, bulunan indeksleri kucukten buyuge verir, eslesme yoksa YOK yazar.",
        "weight": 35,
    },
    {
        "name": "Algoritmik verimlilik",
        "description": "Beklenen cozum O(n) tek gecis dict/set lookup kullanir.",
        "weight": 25,
    },
    {
        "name": "Hata/kenar durumlari",
        "description": "Tek eleman, negatif sayilar, tekrarli degerler ve eslesme yok durumlarini dogru ele alir.",
        "weight": 15,
    },
]

TEST_CASES = [
    {
        "name": "public_basic_pair",
        "visibility": "public",
        "stdin": "9\n2 7 11 15\n",
        "expected_stdout": "0 1\n",
    },
    {
        "name": "public_no_pair",
        "visibility": "public",
        "stdin": "100\n1 2 3 4\n",
        "expected_stdout": "YOK\n",
    },
    {
        "name": "hidden_negative_values",
        "visibility": "hidden",
        "stdin": "4\n-3 7 1 5\n",
        "expected_stdout": "0 1\n",
    },
    {
        "name": "hidden_duplicate_values",
        "visibility": "hidden",
        "stdin": "6\n3 3 4\n",
        "expected_stdout": "0 1\n",
    },
]

SCENARIOS = {
    "good_on": {
        "title": "Dogru O(n) dict cozum",
        "code": """\
target = int(input())
values = list(map(int, input().split()))

seen = {}
answer = None
for i, value in enumerate(values):
    need = target - value
    if need in seen:
        answer = (seen[need], i)
        break
    seen[value] = i

if answer is None:
    print("YOK")
else:
    print(answer[0], answer[1])
""",
    },
    "slow_n2": {
        "title": "Dogru ama O(n^2) ic ice dongu",
        "code": """\
target = int(input())
values = list(map(int, input().split()))

answer = None
for i in range(len(values)):
    for j in range(i + 1, len(values)):
        if values[i] + values[j] == target:
            answer = (i, j)
            break
    if answer:
        break

if answer is None:
    print("YOK")
else:
    print(answer[0], answer[1])
""",
    },
    "runtime_bug": {
        "title": "Runtime/edge bug: cift yoksa None indexler",
        "code": """\
target = int(input())
values = list(map(int, input().split()))
seen = {}
answer = None
for i, value in enumerate(values):
    if target - value in seen:
        answer = (seen[target - value], i)
    seen[value] = i
print(answer[0], answer[1])
""",
    },
    "off_topic": {
        "title": "Alakasiz hava durumu kodu",
        "code": """\
city = input()
print("Hava gunesli")
""",
    },
    "unsafe_eval": {
        "title": "Guvensiz eval kullanan kod",
        "code": """\
target = int(input())
values = eval(input())
print("YOK")
""",
    },
}


def _agent_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(agent.get("id")): agent
        for agent in result.get("agents", [])
        if isinstance(agent, dict)
    }


def _short_findings(agent: dict[str, Any], limit: int = 3) -> list[str]:
    out: list[str] = []
    for finding in agent.get("findings", []) or []:
        if isinstance(finding, dict):
            text = str(finding.get("message") or "").strip()
        else:
            text = str(finding).strip()
        if text:
            out.append(" ".join(text.split())[:220])
        if len(out) >= limit:
            break
    return out


def _summarize(label: str, title: str, result: dict[str, Any]) -> dict[str, Any]:
    agents = _agent_map(result)
    task = result.get("taskAlignment") or {}
    return {
        "label": label,
        "title": title,
        "totalScore": result.get("totalScore"),
        "taskFactor": task.get("factor"),
        "taskOffTopic": task.get("llm_off_topic"),
        "relevanceWarning": result.get("relevanceScoreWarning") or "",
        "testing": {
            "score": agents.get("testing", {}).get("score"),
            "summary": agents.get("testing", {}).get("summary"),
            "findings": _short_findings(agents.get("testing", {}), 5),
        },
        "algorithm": {
            "score": agents.get("algorithm", {}).get("score"),
            "summary": agents.get("algorithm", {}).get("summary"),
            "findings": _short_findings(agents.get("algorithm", {}), 5),
        },
        "security": {
            "score": agents.get("security", {}).get("score"),
            "summary": agents.get("security", {}).get("summary"),
            "findings": _short_findings(agents.get("security", {}), 5),
        },
        "authorship": {
            "score": agents.get("ai_authorship", {}).get("score"),
            "summary": agents.get("ai_authorship", {}).get("summary"),
            "findings": _short_findings(agents.get("ai_authorship", {}), 3),
        },
    }


async def _run(selected: list[str], *, pool: bool) -> None:
    if pool:
        os.environ.setdefault("SANDBOX_POOL_SIZE", "1")
        os.environ.setdefault("SANDBOX_POOL_BASE_PORT", "8391")
        os.environ.setdefault("SANDBOX_POOL_TIMEOUT", "20")
        from backend.sandbox.pool_manager import initialize_pool, shutdown_pool

        initialize_pool()
    else:
        shutdown_pool = None

    try:
        print("ASSIGNMENT")
        print(ASSIGNMENT_BRIEF.strip())
        print("\nTEST_CASES")
        print(json.dumps(TEST_CASES, ensure_ascii=False, indent=2))
        print("\nSCENARIO_RESULTS")
        for label in selected:
            scenario = SCENARIOS[label]
            result = await run_analysis_pipeline(
                f"{label}.py",
                scenario["code"],
                assignment_brief=ASSIGNMENT_BRIEF,
                faculty_rubric_criteria=RUBRIC,
                test_cases=TEST_CASES,
                report_language="tr",
            )
            print(json.dumps(_summarize(label, scenario["title"], result), ensure_ascii=False, indent=2))
    finally:
        if pool and shutdown_pool is not None:
            shutdown_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Two Sum odevi icin AgentGrade QA matrix.")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="Sadece secilen senaryoyu/senaryolari calistir. Varsayilan: tumu.",
    )
    parser.add_argument("--pool", action="store_true", help="Docker sandbox pool acarak formal testleri gercek calistir.")
    args = parser.parse_args()
    selected = args.scenario or list(SCENARIOS)
    asyncio.run(_run(selected, pool=args.pool))


if __name__ == "__main__":
    main()
