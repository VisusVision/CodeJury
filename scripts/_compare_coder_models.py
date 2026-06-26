"""Compare qwen2.5-coder:7b vs 14b on core LLM agents (same inputs)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.code_quality import CodeQualityAgent
from backend.agents.evidence import EvidenceAgent
from backend.agents.guideline import GuidelineAgent
from backend.agents.security import SecurityAgent
from backend.agents.seniority import SeniorityAgent
from backend.agents.task_relevance import assess_task_relevance_llm
from backend.agents.test_agent import TestAgent
from backend.core.config import settings
from backend.sandbox.executor import _simulate_sandbox
from backend.sandbox.fixtures import infer_sandbox_files

MODELS = ("qwen2.5-coder:14b-instruct-q6_K",)
BRIEF = (
    "Sistem Log Ozetleme Araci\n\n"
    "Bir log dosyasini okuyup seviye bazli ozet cikaracak bir CLI araci gelistirin. "
    "Bozuk satirlari raporlayin, hata satirlarini ayri listede dondurun ve dosya hatalarini yonetin."
)
CASES = [
    ("uygun", ROOT / "samples/log_ozetleme_uygun.py"),
    ("alakasiz", ROOT / "sunum_demo_kodlari/02_alakasiz_playlist.py"),
    ("guvensiz", ROOT / "samples/log_ozetleme_guvensiz.py"),
]
OUT = ROOT / "artifacts/qa/coder_model_14b_extended.json"


def _pick(d: dict, *keys: str):
    return {k: d.get(k) for k in keys if k in d}


async def _run_agents(model: str, label: str, code: str) -> dict:
    settings.ollama_coder_model = model
    settings.llm_coder_provider = "ollama"
    settings.ollama_max_concurrent = 1

    base = {
        "source_code": code,
        "language": "python",
        "assignment_description": BRIEF,
        "report_language": "tr",
    }
    rubric = [
        {"name": "Dosya Okuma", "description": "Log dosyasini guvenli okur.", "max_score": 10},
        {"name": "Hata Yonetimi", "description": "Eksik dosya ve bozuk satirlari raporlar.", "max_score": 10},
        {"name": "Guvenlik", "description": "eval/exec gibi tehlikeli kalip kullanmaz.", "max_score": 10},
    ]
    out: dict = {"case": label, "model": model, "agents": {}, "errors": []}

    async def timed(name: str, coro):
        t0 = time.perf_counter()
        try:
            result = await coro
            out["agents"][name] = {
                "elapsed_s": round(time.perf_counter() - t0, 1),
                "llm_status": result.get("llm_status"),
                "summary": _summarize(name, result),
            }
        except Exception as exc:
            out["errors"].append({"agent": name, "error": str(exc)[:300]})
            out["agents"][name] = {
                "elapsed_s": round(time.perf_counter() - t0, 1),
                "llm_status": "error",
                "summary": {"error": str(exc)[:200]},
            }
            result = {}
        return result

    cq = await timed("code_quality", CodeQualityAgent().analyze(dict(base)))
    sec = await timed("security", SecurityAgent().analyze(dict(base)))
    gl = await timed(
        "guideline",
        GuidelineAgent().analyze({**base, "rubric_criteria": rubric}),
    )
    sandbox_files = infer_sandbox_files(assignment_brief=BRIEF, source_code=code)
    sandbox = _simulate_sandbox(code, files=sandbox_files or None)
    ta = await timed(
        "test_agent",
        TestAgent().analyze({**base, "sandbox_result": sandbox, "faculty_rubric_criteria": rubric}),
    )
    sn = await timed("seniority", SeniorityAgent().analyze(dict(base)))

    tr = await timed(
        "task_relevance",
        assess_task_relevance_llm(
            assignment_description=BRIEF,
            source_code=code,
            rubric_criteria=rubric,
        ),
    )

    findings = {
        "code_quality": cq if isinstance(cq, dict) else {},
        "security": sec if isinstance(sec, dict) else {},
        "guideline": gl if isinstance(gl, dict) else {},
        "test_agent": ta if isinstance(ta, dict) else {},
        "seniority": sn if isinstance(sn, dict) else {},
    }
    await timed(
        "evidence",
        EvidenceAgent().analyze({**base, "agent_findings": findings}),
    )
    return out


def _summarize(agent: str, result: dict) -> dict:
    if agent == "code_quality":
        return _pick(result, "score", "time_complexity", "llm_status") | {
            "issues_n": len(result.get("issues") or []),
        }
    if agent == "security":
        return _pick(result, "score", "risk_level", "llm_status") | {
            "threats_n": len(result.get("threats") or []),
            "threat_types": [t.get("type") for t in (result.get("threats") or [])[:4]],
        }
    if agent == "guideline":
        return _pick(result, "score", "llm_status") | {
            "violations_n": len(result.get("style_violations") or []),
        }
    if agent == "test_agent":
        return _pick(result, "score", "llm_status") | {
            "failures_n": len(result.get("test_failures") or []),
        }
    if agent == "task_relevance":
        return _pick(
            result,
            "relevance_factor",
            "off_topic",
            "student_fulfills_assignment",
            "submission_domain_guess",
            "task_domain_guess",
            "skipped",
        ) | {"explanation": str(result.get("explanation", ""))[:120]}
    if agent == "seniority":
        return _pick(result, "score", "seniority_level", "llm_status") | {
            "immaturity_n": len(result.get("immaturity_indicators") or []),
            "maturity_n": len(result.get("maturity_indicators") or []),
        }
    if agent == "evidence":
        return _pick(
            result,
            "total_claims_received",
            "total_claims_validated",
            "llm_status",
        ) | {
            "validated_n": len(result.get("validated_claims") or []),
            "rejected_n": len(result.get("rejected_claims") or []),
        }
    return {}


async def main() -> None:
    report: dict = {"brief": BRIEF, "runs": []}
    for model in MODELS:
        for label, path in CASES:
            code = path.read_text(encoding="utf-8")
            print(f"\n=== {model} / {label} ===", flush=True)
            run = await _run_agents(model, label, code)
            report["runs"].append(run)
            print(json.dumps(run, ensure_ascii=False, indent=2), flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
