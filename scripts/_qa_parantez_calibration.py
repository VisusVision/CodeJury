"""Parantez dengeleme odevi: 3 kod varyanti + tum ajan puanlari."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend.backend.main import run_analysis_pipeline

ASSIGNMENT_BRIEF = """\
Python ile parantez dengeleme cozumunu yazin.

Standart girdiden tek satir parantez dizisi alinir (sadece (), [], {} karakterleri).
Dizi dengeli ise EVET, degilse HAYIR yazdirin.

Beklenen algoritma: stack tabanli O(n) tek gecis.
Ic ice dongu ile O(n^2) cozum beklenenden daha yavas kabul edilir.
Bos string dengeli sayilir. Kapatma parantezi acilmadan gelirse dengesizdir.
"""

RUBRIC = [
    {
        "name": "Girdi ve cikti formati",
        "description": "Tek satir stdin okur; EVET veya HAYIR yazar.",
        "max_score": 20,
    },
    {
        "name": "Dogru denge kontrolu",
        "description": "(), [], {} eslestirmelerini dogru kontrol eder.",
        "max_score": 40,
    },
    {
        "name": "Algoritmik verimlilik",
        "description": "Stack ile O(n) tek gecis cozum kullanir.",
        "max_score": 25,
    },
    {
        "name": "Kenar durumlari",
        "description": "Bos string, tek karakter, ic ice ve karisik parantez turlerini dogru ele alir.",
        "max_score": 15,
    },
]

TEST_CASES = [
    {
        "name": "public_simple_balanced",
        "visibility": "public",
        "stdin": "([])\n",
        "expected_stdout": "EVET\n",
    },
    {
        "name": "public_unbalanced",
        "visibility": "public",
        "stdin": "([)]\n",
        "expected_stdout": "HAYIR\n",
    },
    {
        "name": "hidden_empty",
        "visibility": "hidden",
        "stdin": "\n",
        "expected_stdout": "EVET\n",
    },
    {
        "name": "hidden_nested",
        "visibility": "hidden",
        "stdin": "{[()]}\n",
        "expected_stdout": "EVET\n",
    },
    {
        "name": "hidden_extra_close",
        "visibility": "hidden",
        "stdin": "())\n",
        "expected_stdout": "HAYIR\n",
    },
]

SCENARIOS = {
    "good_stack": {
        "title": "Dogru O(n) stack cozum",
        "code": """\
PAIRS = {")": "(", "]": "[", "}": "{"}
OPEN = set(PAIRS.values())

def is_balanced(text: str) -> bool:
    stack = []
    for ch in text.strip():
        if ch in OPEN:
            stack.append(ch)
        elif ch in PAIRS:
            if not stack or stack[-1] != PAIRS[ch]:
                return False
            stack.pop()
    return not stack

s = input()
print("EVET" if is_balanced(s) else "HAYIR")
""",
    },
    "slow_n2": {
        "title": "Dogru ama O(n^2) ic ice tarama",
        "code": """\
def is_balanced(text: str) -> bool:
    s = text.strip()
    if not s:
        return True
    while True:
        changed = False
        for pair in ("()", "[]", "{}"):
            if pair in s:
                s = s.replace(pair, "", 1)
                changed = True
                break
        if not changed:
            break
    return s == ""

s = input()
print("EVET" if is_balanced(s) else "HAYIR")
""",
    },
    "off_topic": {
        "title": "Alakasiz faktoriyel kodu",
        "code": """\
n = int(input())
f = 1
for i in range(2, n + 1):
    f *= i
print(f)
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
            out.append(" ".join(text.split())[:200])
        if len(out) >= limit:
            break
    return out


def _summarize(label: str, title: str, result: dict[str, Any]) -> dict[str, Any]:
    agents = _agent_map(result)
    task = result.get("taskAlignment") or {}
    agent_scores = {}
    for aid, agent in sorted(agents.items()):
        agent_scores[aid] = {
            "score": agent.get("score"),
            "summary": (agent.get("summary") or "")[:180],
            "findings": _short_findings(agent, 2),
        }
    return {
        "label": label,
        "title": title,
        "totalScore": result.get("totalScore"),
        "rubric": result.get("rubric"),
        "taskFactor": task.get("factor"),
        "taskOffTopic": task.get("llm_off_topic"),
        "capabilityMatch": task.get("capability_match"),
        "relevanceWarning": result.get("relevanceScoreWarning") or "",
        "agents": agent_scores,
    }


async def _run(selected: list[str]) -> None:
    out_dir = ROOT / "output" / "qa"
    out_dir.mkdir(parents=True, exist_ok=True)
    all_results: dict[str, Any] = {
        "assignment": {
            "brief": ASSIGNMENT_BRIEF.strip(),
            "rubric": RUBRIC,
            "test_cases": TEST_CASES,
        },
        "scenarios": {},
    }

    for label in selected:
        scenario = SCENARIOS[label]
        print(f"\n=== {label}: {scenario['title']} ===", flush=True)
        result = await run_analysis_pipeline(
            f"{label}.py",
            scenario["code"],
            assignment_brief=ASSIGNMENT_BRIEF,
            faculty_rubric_criteria=RUBRIC,
            test_cases=TEST_CASES,
            report_language="tr",
        )
        summary = _summarize(label, scenario["title"], result)
        all_results["scenarios"][label] = {
            "title": scenario["title"],
            "code": scenario["code"],
            "summary": summary,
            "full_report": result,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    json_path = out_dir / "parantez_calibration.json"
    json_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON: {json_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parantez odevi ajan kalibrasyon QA.")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="Tek senaryo calistir (varsayilan: hepsi).",
    )
    args = parser.parse_args()
    selected = args.scenario or list(SCENARIOS)
    asyncio.run(_run(selected))


if __name__ == "__main__":
    main()
