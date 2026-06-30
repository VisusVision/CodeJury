"""20-minute soak: multi-scenario pipeline runs with score/agent consistency checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "artifacts" / "qa" / "soak"
sys.path.insert(0, str(ROOT))


CaseKind = Literal["uygun", "alakasiz", "guvensiz", "syntax", "neutral"]


@dataclass
class CaseSpec:
    scenario_id: str
    label: str
    kind: CaseKind
    brief: str
    code_path: str


@dataclass
class RunResult:
    scenario_id: str
    label: str
    kind: str
    elapsed_s: float
    total_score: float
    rubric_sum: int
    alignment: float
    off_topic: bool
    warning: bool
    security_score: float
    agent_statuses: dict[str, str]
    consistency_issues: list[str]
    passed: bool
    error: str | None = None


@dataclass
class SoakSummary:
    started_at: str
    ended_at: str
    duration_min: float
    total_runs: int
    passed_runs: int
    failed_runs: int
    error_runs: int
    sandbox_mode: str = "simulation"
    failures: list[dict[str, Any]] = field(default_factory=list)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _build_cases() -> list[CaseSpec]:
  cases: list[CaseSpec] = []

  sayilar_brief = (
      "Sayilar.txt dosyasindan sayilari okuyun. Tek sayilari filtreleyin. "
      "Ortalama ve medyan hesaplayin. Sonucu sonuc.txt dosyasina raporlayin."
  )
  for label, kind, fname in [
      ("sayilar_uygun", "uygun", "sunum_demo_kodlari/01_uygun_sayilar_analizi.py"),
      ("sayilar_alakasiz", "alakasiz", "sunum_demo_kodlari/02_alakasiz_playlist.py"),
      ("sayilar_syntax", "syntax", "sunum_demo_kodlari/03_syntax_hatasi_ornek.py"),
  ]:
      cases.append(CaseSpec("sayilar_analizi", label, kind, sayilar_brief, fname))

  stack_brief = _read("scripts/demo/stack_brief.txt")
  for label, kind, fname in [
      ("stack_uygun", "uygun", "scripts/demo/stack_uygun.py"),
      ("stack_alakasiz", "alakasiz", "scripts/demo/stack_alakasiz.py"),
      ("stack_guvensiz", "guvensiz", "scripts/demo/stack_guvensiz.py"),
  ]:
      cases.append(CaseSpec("stack_lifo", label, kind, stack_brief, fname))

  bank_brief = _read("scripts/demo/oop_bank_brief.txt")
  for label, kind, fname in [
      ("bank_uygun", "uygun", "scripts/demo/oop_bank_uygun.py"),
      ("bank_alakasiz", "alakasiz", "samples/faktoriyel_odev.py"),
  ]:
      cases.append(CaseSpec("oop_bank", label, kind, bank_brief, fname))

  csv_brief = (
      "CSV dosyasindan ogrenci adi ve not okuyup gecme/kalma durumunu hesaplayan, "
      "sonucu yeni bir CSV rapor dosyasina yazan CLI programi"
  )
  for label, kind, fname in [
      ("csv_uygun", "uygun", "samples/rapor_export_uygun.py"),
      ("csv_alakasiz", "alakasiz", "samples/faktoriyel_odev.py"),
      ("csv_guvensiz", "guvensiz", "samples/rapor_export_guvensiz.py"),
  ]:
      cases.append(CaseSpec("csv_cli", label, kind, csv_brief, fname))

  log_brief = "Log dosyasini okuyup ERROR, WARNING ve INFO sayilarini raporlayan CLI yazin."
  for label, kind, fname in [
      ("log_uygun", "uygun", "samples/log_ozetleme_uygun.py"),
      ("log_alakasiz", "alakasiz", "samples/log_ozetleme_alakasiz.py"),
  ]:
      cases.append(CaseSpec("log_cli", label, kind, log_brief, fname))

  lib_brief = (
      "Kitap ve uye siniflariyla kutuphane odunc alma/iade sistemi yazin. "
      "books.csv ve loans.csv dosyalarini kullanin."
  )
  for label, kind, fname in [
      ("lib_uygun", "uygun", "samples/library_system_uygun.py"),
      ("lib_alakasiz", "alakasiz", "samples/library_system_alakasiz.py"),
  ]:
      cases.append(CaseSpec("library_oop", label, kind, lib_brief, fname))

  text_brief = (
      "Metin dosyasindaki kelimelerin frekansini hesaplayan, noktalama temizleyen "
      "ve en sik N kelimeyi yazdiran CLI programi"
  )
  for label, kind, fname in [
      ("text_uygun", "uygun", "samples/kelime_frekans_uygun.py"),
      ("text_alakasiz", "alakasiz", "samples/faktoriyel_odev.py"),
  ]:
      cases.append(CaseSpec("text_freq", label, kind, text_brief, fname))

  return cases


def _rubric_earned(report: dict[str, Any]) -> int:
    rubric = report.get("rubric", [])
    if not isinstance(rubric, list) or not rubric:
        return 0
    rows = [row for row in rubric if isinstance(row, dict)]
    if not rows:
        return 0
    percent_rows = any(
        int(row.get("maxScore", 0) or 0) > 0
        and int(row.get("score", 0) or 0) > int(row.get("maxScore", 0) or 0)
        for row in rows
    )
    if percent_rows:
        total_weight = sum(int(row.get("weight", 0) or 0) for row in rows)
        if total_weight <= 0:
            return 0
        weighted = sum(
            float(row.get("score", 0) or 0) * int(row.get("weight", 0) or 0)
            for row in rows
        )
        return int(round(weighted / total_weight))
    return sum(int(row.get("score", 0) or 0) for row in rows)


def _agent_map(report: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for agent in report.get("agents", []) or []:
        if isinstance(agent, dict) and agent.get("id"):
            out[str(agent["id"])] = float(agent.get("score", 0) or 0)
    return out


def _agent_llm_status(report: dict[str, Any]) -> dict[str, str]:
    diag = report.get("agentDiagnostics", {})
    out: dict[str, str] = {}
    if isinstance(diag, dict):
        for row in diag.get("agents", []) or []:
            if isinstance(row, dict) and row.get("id"):
                out[str(row["id"])] = str(row.get("llm_status", "?"))
    return out


def _positive_marked_error(report: dict[str, Any]) -> int:
    positive = re.compile(
        r"dogru|basarili|uygun|temiz|iyi|guclu|eksiksiz|properly|correct|success",
        re.I,
    )
    count = 0
    for line in report.get("evidence", []) or []:
        if isinstance(line, dict) and line.get("severity") == "error":
            if positive.search(str(line.get("message", ""))):
                count += 1
    return count


def _uses_percent_rubric(rubric: list[Any]) -> bool:
    rows = [row for row in rubric if isinstance(row, dict)]
    return any(
        int(row.get("maxScore", 0) or 0) > 0
        and int(row.get("score", 0) or 0) > int(row.get("maxScore", 0) or 0)
        for row in rows
    )


def _validate(kind: CaseKind, report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    total = float(report.get("totalScore", 0) or 0)
    rubric = report.get("rubric", [])
    rubric_sum = _rubric_earned(report)
    align = float((report.get("taskAlignment") or {}).get("factor", 1.0) or 1.0)
    off_topic = bool((report.get("taskAlignment") or {}).get("llm_off_topic"))
    warning = bool(report.get("relevanceScoreWarning"))
    agents = _agent_map(report)
    sec = agents.get("security", 100.0)
    llm_status = _agent_llm_status(report)

    if rubric_sum and abs(rubric_sum - total) > 4:
        issues.append(f"rubric_sum {rubric_sum} != total {total}")

    allowed_status = {"ok", "repaired", "skipped_no_claims", "fallback", "unknown"}
    bad_llm = {k: v for k, v in llm_status.items() if v not in allowed_status}
    if bad_llm:
        issues.append(f"unexpected llm_status: {bad_llm}")

    core_ids = [k for k in ("testing", "quality", "seniority", "guideline", "security") if k in agents]
    if not core_ids:
        issues.append("missing core agent scores")

    pos_err = _positive_marked_error(report)
    if pos_err and kind not in {"alakasiz", "syntax"}:
        issues.append(f"positive evidence marked error: {pos_err}")

    if kind == "uygun":
        if total < 55:
            issues.append(f"uygun too low: {total}")
        if align < 0.50 and not off_topic:
            issues.append(f"uygun alignment low: {align}")
        if off_topic:
            issues.append("uygun marked off_topic")
    elif kind == "alakasiz":
        if total > 50 and not off_topic and align > 0.40:
            issues.append(f"alakasiz too high: total={total} align={align}")
        if not off_topic and not warning and align > 0.45:
            issues.append(f"alakasiz no warning/off_topic: align={align}")
    elif kind == "guvensiz":
        if sec >= 75 and total >= 60:
            issues.append(f"guvensiz not penalized: sec={sec} total={total}")
    elif kind == "syntax":
        testing = agents.get("testing", 100)
        if testing > 20 and total > 45:
            issues.append(f"syntax not penalized: testing={testing} total={total}")

    return issues


async def _run_case(case: CaseSpec) -> RunResult:
    from frontend.backend.main import run_analysis_pipeline

    t0 = time.time()
    try:
        code = _read(case.code_path)
        report = await run_analysis_pipeline(
            Path(case.code_path).name,
            code,
            assignment_brief=case.brief,
            report_language="tr",
        )
        elapsed = time.time() - t0
        align = float((report.get("taskAlignment") or {}).get("factor", 0) or 0)
        issues = _validate(case.kind, report)
        return RunResult(
            scenario_id=case.scenario_id,
            label=case.label,
            kind=case.kind,
            elapsed_s=round(elapsed, 1),
            total_score=float(report.get("totalScore", 0) or 0),
            rubric_sum=_rubric_earned(report),
            alignment=round(align, 3),
            off_topic=bool((report.get("taskAlignment") or {}).get("llm_off_topic")),
            warning=bool(report.get("relevanceScoreWarning")),
            security_score=_agent_map(report).get("security", 0.0),
            agent_statuses=_agent_llm_status(report),
            consistency_issues=issues,
            passed=len(issues) == 0,
        )
    except Exception as exc:
        return RunResult(
            scenario_id=case.scenario_id,
            label=case.label,
            kind=case.kind,
            elapsed_s=round(time.time() - t0, 1),
            total_score=0,
            rubric_sum=0,
            alignment=0,
            off_topic=False,
            warning=False,
            security_score=0,
            agent_statuses={},
            consistency_issues=[],
            passed=False,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_soak(duration_min: int, *, sandbox_mode: str = "simulation") -> SoakSummary:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    cases = _build_cases()
    started = datetime.now(timezone.utc)
    deadline = time.time() + duration_min * 60
    results: list[RunResult] = []
    cycle = 0

    print(
        f"[soak] {len(cases)} cases/cycle, target {duration_min} min, sandbox={sandbox_mode}",
        flush=True,
    )

    while time.time() < deadline:
        cycle += 1
        print(f"[soak] cycle {cycle} start", flush=True)
        for case in cases:
            if time.time() >= deadline:
                break
            print(f"[soak]  -> {case.scenario_id}/{case.label} ({case.kind})", flush=True)
            result = await _run_case(case)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            err = f" err={result.error}" if result.error else ""
            print(
                f"[soak]     {status} score={result.total_score} align={result.alignment} "
                f"sec={result.security_score} t={result.elapsed_s}s{err}",
                flush=True,
            )
            if result.consistency_issues:
                print(f"[soak]     issues: {result.consistency_issues}", flush=True)

            row_path = QA_DIR / f"{started.strftime('%Y%m%d_%H%M%S')}_cycle{cycle}_{case.label}.json"
            row_path.write_text(
                json.dumps(result.__dict__, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    ended = datetime.now(timezone.utc)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and not r.error)
    errors = sum(1 for r in results if r.error)

    failures = []
    for r in results:
        if not r.passed:
            failures.append(
                {
                    "scenario": r.scenario_id,
                    "label": r.label,
                    "kind": r.kind,
                    "total": r.total_score,
                    "alignment": r.alignment,
                    "issues": r.consistency_issues,
                    "error": r.error,
                }
            )

    summary = SoakSummary(
        started_at=started.isoformat(),
        ended_at=ended.isoformat(),
        duration_min=round((ended - started).total_seconds() / 60, 1),
        total_runs=len(results),
        passed_runs=passed,
        failed_runs=failed,
        error_runs=errors,
        sandbox_mode=sandbox_mode,
        failures=failures,
    )
    summary_path = QA_DIR / "soak_summary.json"
    summary_path.write_text(json.dumps(summary.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _init_sandbox_pool(*, pool_size: int, base_port: int, timeout_s: float) -> str:
    """Start Docker sandbox pool; return mode label for summary."""
    from backend.ops.runtime_diagnostics import try_initialize_sandbox_pool

    mode = try_initialize_sandbox_pool(
        pool_size=pool_size,
        base_port=base_port,
        timeout_s=timeout_s,
    )
    if mode == "pool":
        from backend.sandbox.pool_manager import get_pool

        pool = get_pool()
        if pool is not None:
            print(
                f"[soak] sandbox pool ready ({pool.available_count}/{len(pool._slots)} free)",
                flush=True,
            )
        return "pool"
    print("[soak] sandbox pool unavailable — falling back to simulation", flush=True)
    return "simulation"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=20)
    parser.add_argument(
        "--pool",
        action="store_true",
        help="Docker sandbox pool ile calistir (initialize_pool gerekir).",
    )
    parser.add_argument("--pool-size", type=int, default=int(os.getenv("SANDBOX_POOL_SIZE", "3")))
    parser.add_argument("--pool-base-port", type=int, default=int(os.getenv("SANDBOX_POOL_BASE_PORT", "8181")))
    parser.add_argument("--pool-timeout", type=float, default=float(os.getenv("SANDBOX_POOL_TIMEOUT", "30")))
    args = parser.parse_args()

    shutdown_pool = None
    sandbox_mode = "simulation"
    if args.pool:
        sandbox_mode = _init_sandbox_pool(
            pool_size=args.pool_size,
            base_port=args.pool_base_port,
            timeout_s=args.pool_timeout,
        )
        from backend.sandbox.pool_manager import shutdown_pool as _shutdown_pool

        shutdown_pool = _shutdown_pool

    try:
        summary = await run_soak(args.minutes, sandbox_mode=sandbox_mode)
        print(json.dumps(summary.__dict__, ensure_ascii=False, indent=2), flush=True)
        return 0 if summary.failed_runs == 0 and summary.error_runs == 0 else 1
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        if shutdown_pool is not None:
            shutdown_pool()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
