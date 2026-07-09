"""120-min faculty flow soak: chatbot -> rubric -> uygun/alakasiz/guvensiz analyses."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "artifacts" / "qa" / "e2e_soak"
sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class Scenario:
    id: str
    hint: str
    course_hint: str
    uygun: str
    alakasiz: str
    guvensiz: str
    hint_tokens: tuple[str, ...] = ()
    bad_tokens: tuple[str, ...] = ()


SCENARIOS: list[Scenario] = [
    Scenario(
        id="csv_cli",
        hint=(
            "CSV dosyasından öğrenci adı ve not okuyup geçme/kalma durumunu hesaplayan, "
            "sonucu yeni bir CSV rapor dosyasına yazan CLI programı"
        ),
        course_hint="python programlama (pro101), 3. sınıf",
        uygun="samples/rapor_export_uygun.py",
        alakasiz="samples/faktoriyel_odev.py",
        guvensiz="samples/rapor_export_guvensiz.py",
        hint_tokens=("csv", "dosya", "okuy", "rapor", "geç", "kal", "not", "cli"),
        bad_tokens=("api", "veritaban", "oop", "sunum", "web sunucu", "flask"),
    ),
    Scenario(
        id="log_cli",
        hint="Log dosyasını okuyup ERROR, WARNING ve INFO sayılarını raporlayan CLI yazın.",
        course_hint="python programlama, dosya işleme",
        uygun="samples/log_ozetleme_uygun.py",
        alakasiz="samples/log_ozetleme_alakasiz.py",
        guvensiz="samples/log_ozetleme_guvensiz.py",
        hint_tokens=("log", "error", "warning", "info", "dosya", "cli", "rapor"),
        bad_tokens=("web", "flask", "api", "oop"),
    ),
    Scenario(
        id="stack_lifo",
        hint="LIFO yığın (stack) veri yapısı: push, pop, peek ve boş kontrolü.",
        course_hint="veri yapıları dersi, 2. sınıf",
        uygun="scripts/demo/stack_uygun.py",
        alakasiz="scripts/demo/stack_alakasiz.py",
        guvensiz="scripts/demo/stack_guvensiz.py",
        hint_tokens=("stack", "lifo", "push", "pop", "yığın", "veri yapı"),
        bad_tokens=("csv", "log", "web", "api"),
    ),
    Scenario(
        id="text_freq",
        hint=(
            "Metin dosyasındaki kelimelerin frekansını hesaplayan, noktalama temizleyen "
            "ve en sık N kelimeyi yazdıran CLI programı"
        ),
        course_hint="python programlama, metin analizi",
        uygun="samples/kelime_frekans_uygun.py",
        alakasiz="samples/faktoriyel_odev.py",
        guvensiz="samples/rapor_export_guvensiz.py",
        hint_tokens=("metin", "kelime", "frekans", "dosya", "cli", "noktalama"),
        bad_tokens=("api", "web", "oop", "bank"),
    ),
    Scenario(
        id="library_oop",
        hint=(
            "Kitap ve üye sınıflarıyla kütüphane ödünç alma/iade sistemi yazın. "
            "books.csv ve loans.csv dosyalarını kullanın."
        ),
        course_hint="nesne yönelimli programlama, 3. sınıf",
        uygun="samples/library_system_uygun.py",
        alakasiz="samples/library_system_alakasiz.py",
        guvensiz="samples/log_ozetleme_guvensiz.py",
        hint_tokens=("kitap", "kütüphane", "ödünç", "csv", "sınıf", "oop"),
        bad_tokens=("web", "flask", "api"),
    ),
    Scenario(
        id="sayilar_analizi",
        hint=(
            "Sayilar.txt dosyasından sayıları okuyun. Tek sayıları filtreleyin. "
            "Ortalama ve medyan hesaplayın. Sonucu sonuc.txt dosyasına raporlayın."
        ),
        course_hint="python programlama, dosya okuma",
        uygun="sunum_demo_kodlari/01_uygun_sayilar_analizi.py",
        alakasiz="sunum_demo_kodlari/02_alakasiz_playlist.py",
        guvensiz="scripts/demo/stack_guvensiz.py",
        hint_tokens=("sayi", "dosya", "ortalama", "medyan", "tek", "rapor"),
        bad_tokens=("web", "api", "playlist"),
    ),
    Scenario(
        id="api_client",
        hint="Harici API'den yapılandırma çeken ve sonucu yazdıran istemci yazın.",
        course_hint="python programlama, ağ programlama",
        uygun="samples/api_config_client_uygun.py",
        alakasiz="samples/api_config_client_alakasiz.py",
        guvensiz="samples/rapor_export_guvensiz.py",
        hint_tokens=("api", "http", "istek", "yapılandırma", "config"),
        bad_tokens=("csv", "log", "stack", "kütüphane"),
    ),
    Scenario(
        id="data_clean_api",
        hint=(
            "SQLite tablosu oluşturan, POST /clean ve PUT /beautify endpointleri sunan mini API geliştirin."
        ),
        course_hint="web programlama, veri temizleme",
        uygun="samples/veri_guzellestirme_temizleme_uygun.py",
        alakasiz="samples/veri_guzellestirme_temizleme_alakasiz.py",
        guvensiz="samples/log_ozetleme_guvensiz.py",
        hint_tokens=("sqlite", "api", "post", "clean", "endpoint", "veri"),
        bad_tokens=("csv", "log", "stack"),
    ),
]


def _force_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip()
    os.environ.setdefault("LLM_GENERAL_PROVIDER", "ollama")
    os.environ.setdefault("LLM_CODER_PROVIDER", "ollama")
    os.environ.setdefault("OLLAMA_ENABLED", "true")
    os.environ.setdefault("OLLAMA_GENERAL_MODEL", "qwen2.5-coder:14b-instruct-q6_K")
    os.environ.setdefault("OLLAMA_CODER_MODEL", "qwen2.5-coder:14b-instruct-q6_K")
    os.environ["DEMO_MODE"] = "0"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _score_suggestion(item: dict, scenario: Scenario) -> int:
    text = " ".join(str(item.get(k, "")) for k in ("title", "summary", "description")).lower()
    hint = scenario.hint.lower()
    score = 0
    for token in scenario.hint_tokens:
        if token in text:
            score += 2
    if hint.strip() in text or text.strip() == hint.strip():
        score += 12
    for bad in scenario.bad_tokens:
        if bad in text:
            score -= 5
    return score


def _agent_map(report: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in report.get("agents") or []:
        if isinstance(row, dict) and row.get("id"):
            try:
                out[str(row["id"])] = float(row.get("score", 0) or 0)
            except (TypeError, ValueError):
                pass
    return out


def _agent_llm_status(report: dict) -> dict[str, str]:
    diag = report.get("agentDiagnostics", {})
    out: dict[str, str] = {}
    if isinstance(diag, dict):
        for row in diag.get("agents", []) or []:
            if isinstance(row, dict) and row.get("id"):
                out[str(row["id"])] = str(row.get("llm_status", "?"))
    return out


def _evaluate(label: str, report: dict, *, relevant: bool, risky: bool = False) -> dict:
    align = report.get("taskAlignment") or {}
    factor = float(align.get("factor", 0) or 0)
    off = bool(align.get("llm_off_topic"))
    total = float(report.get("totalScore", 0) or 0)
    agents = _agent_map(report)
    sec = agents.get("security", 100.0)
    ta = agents.get("testing", 0.0)
    issues: list[str] = []

    if relevant and not risky:
        ok = factor >= 0.55 and not off and total >= 55 and sec >= 60
        if total < 55:
            issues.append(f"uygun too low: {total}")
        if off:
            issues.append("uygun marked off_topic")
        if factor < 0.50 and not off:
            issues.append(f"uygun alignment low: {factor}")
    elif not relevant:
        ok = factor <= 0.35 or off or total <= 50
        if total > 50 and not off and factor > 0.40:
            issues.append(f"alakasiz too high: total={total} align={factor}")
    else:
        ok = total <= 40 and sec < 75
        if sec >= 75 and total >= 60:
            issues.append(f"guvensiz not penalized: sec={sec} total={total}")
        elif total > 40 and sec < 75:
            issues.append(f"guvensiz too high: total={total} sec={sec}")

    return {
        "label": label,
        "total": round(total, 1),
        "align": round(factor, 3),
        "off_topic": off,
        "testing": ta,
        "security": sec,
        "agents": agents,
        "llm_status": _agent_llm_status(report),
        "issues": issues,
        "passed": ok and not issues,
    }


@dataclass
class CycleResult:
    cycle: int
    scenario_id: str
    started_at: str
    elapsed_s: float
    assignment_title: str
    rubric_criteria_count: int
    chatbot_ok: bool
    rubric_ok: bool
    analysis: list[dict] = field(default_factory=list)
    all_passed: bool = False
    error: str | None = None


async def _run_cycle(cycle: int, scenario: Scenario) -> CycleResult:
    from frontend.backend.main import (
        AssignmentAssistantSuggestionsRequest,
        RubricSuggestionRequest,
        _assignment_hint_anchor_terms,
        _direct_assignment_suggestion_from_hint,
        _matches_long_brief_anchor,
        assignment_assistant_suggestions,
        run_analysis_pipeline,
        suggest_rubric,
    )

    started = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    result = CycleResult(
        cycle=cycle,
        scenario_id=scenario.id,
        started_at=started,
        elapsed_s=0,
        assignment_title="",
        rubric_criteria_count=0,
        chatbot_ok=False,
        rubric_ok=False,
    )

    try:
        course_hint = f"{scenario.course_hint}. {scenario.hint}"
        direct = _direct_assignment_suggestion_from_hint(course_hint)
        anchor_terms = _assignment_hint_anchor_terms(course_hint)

        print(f"[e2e-soak] cycle {cycle} scenario={scenario.id} chatbot...", flush=True)
        sug = await assignment_assistant_suggestions(
            AssignmentAssistantSuggestionsRequest(
                course_hint=course_hint,
                count=5,
                difficulty="medium",
                prefer_fresh=True,
            )
        )
        suggestions = sug.get("suggestions") or []
        if not suggestions and not direct:
            result.error = "chatbot empty"
            return result

        if direct:
            picked = dict(direct)
        elif suggestions:
            picked = max(suggestions, key=lambda s: _score_suggestion(s, scenario))
            if _score_suggestion(picked, scenario) < 10:
                picked = {
                    "title": scenario.hint[:90],
                    "summary": scenario.hint[:160],
                    "description": scenario.hint,
                }
        else:
            picked = {
                "title": scenario.hint[:90],
                "summary": scenario.hint[:160],
                "description": scenario.hint,
            }

        title = str(picked.get("title", "")).strip()
        description = str(picked.get("description", "")).strip() or scenario.hint
        generic_title = len(title.split()) <= 3 or title.lower() in {
            "python programlama",
            "web programlama",
            "nesne yönelimli programlama",
            "nesne yonelimli programlama",
        }
        if generic_title or (
            anchor_terms and not _matches_long_brief_anchor(f"{title} {description}", anchor_terms)
        ):
            if direct:
                picked = dict(direct)
            else:
                picked = {
                    "title": scenario.hint[:90],
                    "summary": scenario.hint[:160],
                    "description": scenario.hint,
                }
            title = str(picked.get("title", "")).strip()
            description = str(picked.get("description", "")).strip() or scenario.hint
            print(f"[e2e-soak]   hint fallback: {title[:70]}", flush=True)

        result.assignment_title = title
        result.chatbot_ok = True
        print(f"[e2e-soak]   picked: {title[:70]}", flush=True)

        print(f"[e2e-soak] cycle {cycle} rubric...", flush=True)
        rub = await suggest_rubric(
            RubricSuggestionRequest(
                assignment_title=title,
                assignment_description=description,
                report_language="tr",
            )
        )
        criteria = rub.get("criteria") or []
        if len(criteria) < 5:
            result.error = f"rubric insufficient: {len(criteria)} criteria"
            return result
        result.rubric_criteria_count = len(criteria)
        result.rubric_ok = True
        faculty = [
            {
                "name": str(c.get("name", "")),
                "description": str(c.get("description", "")),
                "max_score": int(c.get("max_score", 0) or 0),
            }
            for c in criteria
        ]
        brief = description

        cases = [
            ("uygun", scenario.uygun, True, False),
            ("alakasiz", scenario.alakasiz, False, False),
            ("guvensiz", scenario.guvensiz, True, True),
        ]
        for label, code_path, relevant, risky in cases:
            print(f"[e2e-soak] cycle {cycle} analyze {label}...", flush=True)
            t_case = time.time()
            code = _read(code_path)
            report = await run_analysis_pipeline(
                Path(code_path).name,
                code,
                assignment_brief=brief,
                faculty_rubric_criteria=faculty,
                report_language="tr",
            )
            ev = _evaluate(label, report, relevant=relevant, risky=risky)
            ev["elapsed_s"] = round(time.time() - t_case, 1)
            ev["code_path"] = code_path
            result.analysis.append(ev)
            status = "PASS" if ev["passed"] else "FAIL"
            print(
                f"[e2e-soak]   {label}: total={ev['total']} align={ev['align']} "
                f"TA={ev['testing']} SC={ev['security']} -> {status} ({ev['elapsed_s']}s)",
                flush=True,
            )
            if ev.get("issues"):
                print(f"[e2e-soak]     issues: {ev['issues']}", flush=True)

        result.all_passed = all(row["passed"] for row in result.analysis)
        result.elapsed_s = round(time.time() - t0, 1)
        return result
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.elapsed_s = round(time.time() - t0, 1)
        traceback.print_exc()
        return result


async def run_soak(duration_min: int, *, sandbox_mode: str = "simulation") -> dict[str, Any]:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = QA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    from backend.core.config import settings

    started = datetime.now(timezone.utc)
    deadline = time.time() + duration_min * 60
    cycles: list[CycleResult] = []
    cycle_num = 0
    scenario_idx = 0

    gen_prov = (settings.llm_general_provider or settings.llm_provider or "ollama").strip()
    coder_prov = (settings.llm_coder_provider or settings.llm_provider or "ollama").strip()
    print(
        f"[e2e-soak] {duration_min} min, {len(SCENARIOS)} scenarios, sandbox={sandbox_mode}\n"
        f"[e2e-soak] chatbot/rubric: {gen_prov} -> {settings.ollama_general_model}\n"
        f"[e2e-soak] analysis agents: {coder_prov} -> {settings.ollama_coder_model}",
        flush=True,
    )

    while time.time() < deadline:
        cycle_num += 1
        scenario = SCENARIOS[scenario_idx % len(SCENARIOS)]
        scenario_idx += 1

        result = await _run_cycle(cycle_num, scenario)
        cycles.append(result)

        cycle_path = run_dir / f"cycle_{cycle_num:03d}_{scenario.id}.json"
        cycle_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")

        status = "PASS" if result.all_passed and not result.error else "FAIL"
        err = f" err={result.error}" if result.error else ""
        print(
            f"[e2e-soak] cycle {cycle_num} {status} scenario={scenario.id} "
            f"t={result.elapsed_s}s{err}",
            flush=True,
        )

        _write_rolling_summary(run_dir, started, cycles, duration_min, sandbox_mode, settings)

        if time.time() >= deadline:
            break

    ended = datetime.now(timezone.utc)
    summary = _build_summary(run_dir, started, ended, cycles, duration_min, sandbox_mode, settings)
    summary_path = run_dir / "soak_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = QA_DIR / "latest_summary.json"
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def _write_rolling_summary(
    run_dir: Path,
    started: datetime,
    cycles: list[CycleResult],
    duration_min: int,
    sandbox_mode: str,
    settings: Any,
) -> None:
    summary = _build_summary(run_dir, started, datetime.now(timezone.utc), cycles, duration_min, sandbox_mode, settings)
    (run_dir / "rolling_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_summary(
    run_dir: Path,
    started: datetime,
    ended: datetime,
    cycles: list[CycleResult],
    duration_min: int,
    sandbox_mode: str,
    settings: Any,
) -> dict[str, Any]:
    all_analyses: list[dict] = []
    for c in cycles:
        for row in c.analysis:
            all_analyses.append({**row, "cycle": c.cycle, "scenario_id": c.scenario_id})

    passed_cycles = sum(1 for c in cycles if c.all_passed and not c.error)
    failed_cycles = sum(1 for c in cycles if not c.all_passed and not c.error)
    error_cycles = sum(1 for c in cycles if c.error)

    by_label: dict[str, list] = {"uygun": [], "alakasiz": [], "guvensiz": []}
    for row in all_analyses:
        by_label.setdefault(row["label"], []).append(row)

    failures: list[dict] = []
    for c in cycles:
        if c.error:
            failures.append({"cycle": c.cycle, "scenario": c.scenario_id, "error": c.error})
        for row in c.analysis:
            if not row.get("passed"):
                failures.append(
                    {
                        "cycle": c.cycle,
                        "scenario": c.scenario_id,
                        "label": row["label"],
                        "total": row["total"],
                        "align": row["align"],
                        "issues": row.get("issues", []),
                    }
                )

    agent_avgs: dict[str, float] = {}
    for agent_id in ("testing", "quality", "seniority", "guideline", "security", "algorithm"):
        vals = [
            float(row["agents"].get(agent_id, 0))
            for row in all_analyses
            if row.get("label") == "uygun" and row.get("agents")
        ]
        if vals:
            agent_avgs[agent_id] = round(sum(vals) / len(vals), 1)

    return {
        "run_dir": str(run_dir),
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "target_duration_min": duration_min,
        "actual_duration_min": round((ended - started).total_seconds() / 60, 1),
        "total_cycles": len(cycles),
        "passed_cycles": passed_cycles,
        "failed_cycles": failed_cycles,
        "error_cycles": error_cycles,
        "total_analyses": len(all_analyses),
        "sandbox_mode": sandbox_mode,
        "llm": {
            "general_model": settings.ollama_general_model,
            "coder_model": settings.ollama_coder_model,
            "provider": settings.llm_provider,
        },
        "by_label": {
            label: {
                "n": len(rows),
                "passed": sum(1 for r in rows if r.get("passed")),
                "total_avg": round(sum(r["total"] for r in rows) / len(rows), 1) if rows else 0,
                "align_avg": round(sum(r["align"] for r in rows) / len(rows), 3) if rows else 0,
            }
            for label, rows in by_label.items()
        },
        "agent_avgs_uygun": agent_avgs,
        "failures": failures,
    }


def _init_sandbox_pool(*, pool_size: int, base_port: int, timeout_s: float) -> str:
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
                f"[e2e-soak] sandbox pool ready ({pool.available_count}/{len(pool._slots)} free)",
                flush=True,
            )
        return "pool"
    print("[e2e-soak] sandbox pool unavailable — simulation", flush=True)
    return "simulation"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=120)
    parser.add_argument("--pool", action="store_true")
    parser.add_argument("--pool-size", type=int, default=int(os.getenv("SANDBOX_POOL_SIZE", "3")))
    parser.add_argument("--pool-base-port", type=int, default=int(os.getenv("SANDBOX_POOL_BASE_PORT", "8181")))
    parser.add_argument("--pool-timeout", type=float, default=float(os.getenv("SANDBOX_POOL_TIMEOUT", "30")))
    args = parser.parse_args()

    _force_env()
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
        ok = summary["failed_cycles"] == 0 and summary["error_cycles"] == 0
        return 0 if ok else 1
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        if shutdown_pool is not None:
            shutdown_pool()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
