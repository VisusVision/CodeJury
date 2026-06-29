"""Tum odev tipleri + kullanici senaryolari icin birlesik QA kosusu."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "output" / "qa"
REPORT_PATH = OUT_DIR / "all_scenarios_report.json"


def _run_pytest(patterns: list[str]) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "pytest", *patterns, "-q", "--tb=line"]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    tail = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in tail.strip().splitlines() if ln.strip()]
    return {
        "name": "pytest_unit",
        "passed": proc.returncode == 0,
        "exit_code": proc.returncode,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "summary_line": lines[-1] if lines else "",
    }


async def _run_programmatic_calibration() -> dict[str, Any]:
    from scripts.agent_calibration_suite import run_programmatic_suite

    t0 = time.perf_counter()
    report = await run_programmatic_suite(
        checkpoint_path=ROOT / "artifacts" / "agent_calibration" / "programmatic_latest.json",
    )
    summary = report.get("summary", {})
    total = int(summary.get("total_cases", 0))
    passed = int(summary.get("passed_cases", 0))
    return {
        "name": "calibration_programmatic",
        "passed": passed == total and total > 0,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "summary": summary,
        "failures": _calibration_failures(report),
    }


async def _run_full_calibration(timeout_s: int) -> dict[str, Any]:
    from scripts.agent_calibration_suite import run_suite

    t0 = time.perf_counter()
    report = await run_suite(
        persist_demo_assignments=False,
        checkpoint_path=ROOT / "artifacts" / "agent_calibration" / "latest_report.json",
        timeout_seconds=timeout_s,
    )
    summary = report.get("summary", {})
    total = int(summary.get("total_cases", 0))
    passed = int(summary.get("passed_cases", 0))
    return {
        "name": "calibration_full_llm",
        "passed": passed == total and total > 0,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "summary": summary,
        "failures": _calibration_failures(report),
    }


def _calibration_failures(report: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for scenario in report.get("scenarios", []) or []:
        for case in scenario.get("cases", []) or []:
            res = case.get("result", {})
            if not res.get("case_passed"):
                out.append({
                    "scenario": scenario.get("scenario_key"),
                    "label": case.get("label"),
                    "score": res.get("total_score"),
                    "align": res.get("alignment_factor"),
                    "off_topic": res.get("llm_off_topic"),
                })
    return out


async def _run_matrix_module(module_name: str, *, monotonic: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    import importlib

    mod = importlib.import_module(module_name)
    brief = getattr(mod, "ASSIGNMENT_BRIEF", None) or getattr(mod, "ASSIGNMENT", {}).get("brief", "")
    rubric = getattr(mod, "RUBRIC", None) or getattr(mod, "ASSIGNMENT", {}).get("rubric", [])
    test_cases = getattr(mod, "TEST_CASES", None) or getattr(mod, "ASSIGNMENT", {}).get("test_cases")
    scenarios = getattr(mod, "SCENARIOS")

    from frontend.backend.main import run_analysis_pipeline

    t0 = time.perf_counter()
    scores: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    for key, scenario in scenarios.items():
        code = scenario["code"]
        result = await run_analysis_pipeline(
            f"{key}.py",
            code,
            assignment_brief=brief,
            faculty_rubric_criteria=rubric,
            test_cases=test_cases,
            report_language="tr",
        )
        total = float(result.get("totalScore", 0) or 0)
        scores[key] = total
        rows.append({
            "key": key,
            "title": scenario.get("title") or scenario.get("label"),
            "totalScore": total,
            "taskFactor": (result.get("taskAlignment") or {}).get("factor"),
            "offTopic": (result.get("taskAlignment") or {}).get("llm_off_topic"),
        })

    mono_issues: list[str] = []
    if monotonic:
        for better, worse in monotonic:
            if scores.get(better, 0) <= scores.get(worse, 0):
                mono_issues.append(f"{better}({scores.get(better)}) <= {worse}({scores.get(worse)})")

    return {
        "name": module_name.rsplit(".", 1)[-1],
        "passed": not mono_issues,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "scores": scores,
        "rows": rows,
        "monotonic_issues": mono_issues,
    }


async def _run_soak_once() -> dict[str, Any]:
    from scripts.qa_soak_consistency import _build_cases, _run_case

    t0 = time.perf_counter()
    cases = _build_cases()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in cases:
        result = await _run_case(case)
        row = {
            "scenario": case.scenario_id,
            "label": case.label,
            "kind": case.kind,
            "passed": result.passed,
            "totalScore": result.total_score,
            "alignment": result.alignment,
            "issues": result.consistency_issues,
            "error": result.error,
        }
        rows.append(row)
        if not result.passed:
            failures.append(row)

    passed = sum(1 for r in rows if r["passed"])
    return {
        "name": "soak_once",
        "passed": len(failures) == 0,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "summary": {"total": len(rows), "passed": passed, "failed": len(failures)},
        "failures": failures,
        "rows": rows,
    }


async def run_all(*, skip_llm: bool, timeout_s: int) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    suites: list[dict[str, Any]] = []

    suites.append(_run_pytest([
        "backend/tests/test_agent_behavior_matrix.py",
        "backend/tests/test_agent_contracts.py",
        "backend/tests/test_test_agent_sandbox_results.py",
        "backend/tests/test_algorithm_authorship_agents.py",
    ]))
    suites.append(await _run_programmatic_calibration())

    if not skip_llm:
        suites.append(await _run_full_calibration(timeout_s))
        suites.append(await _run_matrix_module(
            "scripts._qa_parantez_calibration",
            monotonic=[("good_stack", "slow_n2"), ("slow_n2", "off_topic")],
        ))
        suites.append(await _run_matrix_module(
            "scripts._qa_two_sum_assignment",
            monotonic=[
                ("good_on", "slow_n2"),
                ("good_on", "off_topic"),
                ("slow_n2", "off_topic"),
            ],
        ))
        try:
            import importlib.util

            nge_path = ROOT / "output" / "qa" / "multi_agent_production_readiness.py"
            if nge_path.is_file():
                spec = importlib.util.spec_from_file_location("nge_qa", nge_path)
                if spec and spec.loader:
                    nge = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(nge)
                    from frontend.backend.main import run_analysis_pipeline as pipeline

                    t0 = time.perf_counter()
                    nge_scores: dict[str, float] = {}
                    assignment = nge.ASSIGNMENT
                    for key, scenario in nge.SCENARIOS.items():
                        rep = await pipeline(
                            f"{key}.py",
                            scenario["code"],
                            assignment_brief=assignment["brief"],
                            faculty_rubric_criteria=assignment["rubric"],
                            test_cases=assignment["test_cases"],
                            report_language="tr",
                        )
                        nge_scores[key] = float(rep.get("totalScore", 0) or 0)
                    mono = []
                    if nge_scores.get("perfect", 0) <= nge_scores.get("logical_bug", 0):
                        mono.append("perfect <= logical_bug")
                    if nge_scores.get("perfect", 0) <= nge_scores.get("critical_bug", 0):
                        mono.append("perfect <= critical_bug")
                    suites.append({
                        "name": "next_greater_element",
                        "passed": not mono,
                        "elapsed_s": round(time.perf_counter() - t0, 1),
                        "scores": nge_scores,
                        "monotonic_issues": mono,
                    })
        except Exception as exc:
            suites.append({
                "name": "next_greater_element",
                "passed": False,
                "error": str(exc)[:300],
            })
        suites.append(await _run_soak_once())

    all_pass = all(s.get("passed") for s in suites)
    report = {
        "started_at": started,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "skip_llm": skip_llm,
        "all_passed": all_pass,
        "suites": suites,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _print_report(report: dict[str, Any]) -> None:
    print("\n=== ALL ASSIGNMENT SCENARIOS ===")
    for suite in report.get("suites", []):
        mark = "PASS" if suite.get("passed") else "FAIL"
        print(f"[{mark}] {suite.get('name')} ({suite.get('elapsed_s', '?')}s)")
        if suite.get("summary_line"):
            print(f"       {suite['summary_line']}")
        if suite.get("summary"):
            print(f"       {json.dumps(suite['summary'], ensure_ascii=False)}")
        if suite.get("scores"):
            print(f"       scores={json.dumps(suite['scores'], ensure_ascii=False)}")
        if suite.get("monotonic_issues"):
            print(f"       mono: {suite['monotonic_issues']}")
        if suite.get("failures"):
            for f in suite["failures"][:8]:
                print(f"       fail: {json.dumps(f, ensure_ascii=False)[:200]}")
        if suite.get("error"):
            print(f"       error: {suite['error']}")
    print(f"\nRapor: {REPORT_PATH}")
    print(f"Genel: {'PASS' if report.get('all_passed') else 'FAIL'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tum odev senaryolarini calistir.")
    parser.add_argument("--skip-llm", action="store_true", help="Sadece unit + programmatic kos.")
    parser.add_argument("--timeout", type=int, default=900, help="Full calibration pipeline timeout/sn.")
    args = parser.parse_args()
    report = asyncio.run(run_all(skip_llm=args.skip_llm, timeout_s=args.timeout))
    _print_report(report)
    return 0 if report.get("all_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
