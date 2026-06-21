from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MAIN_PATH = ROOT / "frontend" / "backend" / "main.py"
REPORT_PATH = ROOT / "artifacts" / "agent_calibration" / "latest_report.json"
DEFAULT_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class SubmissionCase:
    label: str
    file_path: str
    expected_relevant: bool
    expected_security_risky: bool = False
    min_score: float | None = None
    max_score: float | None = None
    min_alignment: float | None = None
    max_alignment: float | None = None


@dataclass(frozen=True)
class AssignmentScenario:
    key: str
    title: str
    description: str
    criterion_count: int
    submissions: list[SubmissionCase]


SCENARIOS: list[AssignmentScenario] = [
    AssignmentScenario(
        key="data_clean_api",
        title="Veri Guzellestirme ve Temizleme",
        description=(
            "SQLite tablosu olusturan, POST /clean ve PUT /beautify endpointleri sunan mini bir API "
            "gelistirin. Hata durumlarinda uygun mesajlar donmeli ve konsola log basilmali."
        ),
        criterion_count=10,
        submissions=[
            SubmissionCase("uygun", "samples/veri_guzellestirme_temizleme_uygun.py", True, min_score=65, min_alignment=0.55),
            SubmissionCase("alakasiz", "samples/veri_guzellestirme_temizleme_alakasiz.py", False, max_score=35, max_alignment=0.30),
        ],
    ),
    AssignmentScenario(
        key="library_oop",
        title="Kitap Kutuphanesi Sistemi",
        description=(
            "Kitap, uye ve kutuphane siniflariyla OOP tabanli bir odunc alma-iade sistemi yazin. "
            "Sinif sorumluluklari net ayrilmali, hata durumlari kontrollu ele alinmalidir."
        ),
        criterion_count=12,
        submissions=[
            SubmissionCase("uygun", "samples/library_system_uygun.py", True, min_score=65, min_alignment=0.55),
            SubmissionCase("alakasiz", "samples/library_system_alakasiz.py", False, max_score=35, max_alignment=0.30),
        ],
    ),
    AssignmentScenario(
        key="bst_assignment",
        title="Ikili Arama Agaci Uygulamasi",
        description=(
            "Ekleme, arama ve dolasim islemlerini (inorder, preorder, postorder) destekleyen "
            "bir ikili arama agaci sinifi yazin. Kose durumlari ele alinmalidir."
        ),
        criterion_count=10,
        submissions=[
            SubmissionCase("uygun", "samples/ornek_odev_ikili_agac.py", True, min_score=65, min_alignment=0.55),
            SubmissionCase("alakasiz", "samples/kitap_kutuphanesi_alakasiz.py", False, max_score=35, max_alignment=0.30),
        ],
    ),
    AssignmentScenario(
        key="log_summary_cli",
        title="Sistem Log Ozetleme Araci",
        description=(
            "Bir log dosyasini okuyup seviye bazli ozet cikaracak bir CLI araci gelistirin. "
            "Bozuk satirlari raporlayin, hata satirlarini ayri listede dondurun ve dosya hatalarini yonetin."
        ),
        criterion_count=10,
        submissions=[
            SubmissionCase("uygun", "samples/log_ozetleme_uygun.py", True, min_score=65, min_alignment=0.55),
            SubmissionCase(
                "guvensiz_ama_alakali",
                "samples/log_ozetleme_guvensiz.py",
                True,
                True,
                max_score=55,
                min_alignment=0.55,
            ),
            SubmissionCase("alakasiz", "samples/log_ozetleme_alakasiz.py", False, max_score=35, max_alignment=0.30),
        ],
    ),
    AssignmentScenario(
        key="api_config_client",
        title="API Konfigurasyon Istemcisi",
        description=(
            "Ortam degiskeninden API_URL okuyan, verilen path icin HTTP durum kodu alan "
            "ve gecersiz konfigurasyonu anlasilir hatayla reddeden kucuk bir API istemcisi yazin."
        ),
        criterion_count=10,
        submissions=[
            SubmissionCase("uygun", "samples/api_config_client_uygun.py", True, min_score=60, min_alignment=0.50),
            SubmissionCase("alakasiz", "samples/api_config_client_alakasiz.py", False, max_score=35, max_alignment=0.30),
        ],
    ),
    AssignmentScenario(
        key="report_export",
        title="CSV Rapor Export Araci",
        description=(
            "Ogrenci skorlarini alip gecme durumunu hesaplayan ve sonucu CSV rapor dosyasina "
            "yazan bir CLI araci gelistirin. Cikti dosyasi UTF-8 olmali ve klasor yoksa olusturulmalidir."
        ),
        criterion_count=10,
        submissions=[
            SubmissionCase("uygun", "samples/rapor_export_uygun.py", True, min_score=60, min_alignment=0.50),
            SubmissionCase(
                "guvensiz_ama_alakali",
                "samples/rapor_export_guvensiz.py",
                True,
                True,
                max_score=55,
                min_alignment=0.50,
            ),
            SubmissionCase("alakasiz", "samples/api_config_client_alakasiz.py", False, max_score=35, max_alignment=0.30),
        ],
    ),
]


def _load_api_main():
    spec = importlib.util.spec_from_file_location("agentgrade_api_main", MAIN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"main.py yuklenemedi: {MAIN_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_text(rel_path: str) -> str:
    p = ROOT / rel_path
    return p.read_text(encoding="utf-8")


def _build_brief(title: str, description: str) -> str:
    return f"{title}\n\n{description}".strip()


def _extract_security_agent(report: dict[str, Any]) -> dict[str, Any]:
    agents = report.get("agents", [])
    if not isinstance(agents, list):
        return {}
    for agent in agents:
        if isinstance(agent, dict) and agent.get("id") == "security":
            return agent
    return {}


def _language_for_path(path: str) -> str:
    lower = path.lower()
    if lower.endswith((".c", ".cpp", ".h", ".hpp")):
        return "c++"
    if lower.endswith(".java"):
        return "java"
    if lower.endswith((".js", ".jsx", ".ts", ".tsx")):
        return "javascript"
    return "python"


def _programmatic_pipeline_report(brief: str, file_path: str, code: str) -> dict[str, Any]:
    from backend.agents.code_quality import CodeQualityAgent
    from backend.agents.security import SecurityAgent
    from backend.agents.task_relevance import _capability_match_signal
    from backend.agents.test_agent import TestAgent
    from backend.sandbox.executor import _simulate_sandbox
    from backend.sandbox.fixtures import infer_sandbox_files

    language = _language_for_path(file_path)
    capability = _capability_match_signal(brief, None, code)
    off_topic = capability <= 0.24

    security = SecurityAgent()._programmatic_analysis(
        code,
        language,
        assignment_description=brief,
    )
    if language == "python":
        sandbox_files = infer_sandbox_files(assignment_brief=brief, source_code=code)
        sandbox = _simulate_sandbox(code, files=sandbox_files or None)
    else:
        sandbox = {
            "compilation_success": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }
    testing = TestAgent()._programmatic_analysis(
        sandbox,
        None,
        code,
        language,
        brief,
        task_alignment={"factor": max(0.05, capability), "reasons": [] if not off_topic else ["capability_mismatch"]},
    )
    quality = CodeQualityAgent()._programmatic_analysis(code, language)

    if off_topic:
        total_score = min(35.0, round(100.0 * max(0.05, capability), 1))
    else:
        total_score = round(
            (100.0 * max(0.05, capability) * 0.35)
            + (float(testing.get("score", 0) or 0) * 0.25)
            + (float(security.get("score", 0) or 0) * 0.25)
            + (float(quality.get("score", 0) or 0) * 0.15),
            1,
        )
        if not security.get("safe", True):
            total_score = min(total_score, 55.0 if security.get("risk_level") == "critical" else 70.0)

    return {
        "totalScore": total_score,
        "taskAlignment": {
            "factor": max(0.05, min(1.0, capability)),
            "llm_off_topic": off_topic,
        },
        "relevanceScoreWarning": "Programmatic capability mismatch." if off_topic else "",
        "agents": [
            {
                "id": "security",
                "score": security.get("score", 0),
                "summary": (
                    f"Risk: {str(security.get('risk_level', 'safe')).upper()}, "
                    f"{security.get('total_threats', 0)} tehdit, Skor: {security.get('score', 0)}/100"
                ),
            },
            {"id": "testing", "score": testing.get("score", 0)},
            {"id": "code_quality", "score": quality.get("score", 0)},
        ],
    }


def _evaluate_case(case: SubmissionCase, report: dict[str, Any]) -> dict[str, Any]:
    align = report.get("taskAlignment", {}) if isinstance(report.get("taskAlignment"), dict) else {}
    align_factor = float(align.get("factor", 1.0) or 1.0)
    llm_off_topic = bool(align.get("llm_off_topic"))
    relevance_warning = bool(report.get("relevanceScoreWarning"))
    total_score = float(report.get("totalScore", 0) or 0)

    sec = _extract_security_agent(report)
    sec_score = float(sec.get("score", 0) or 0)
    sec_summary = str(sec.get("summary", ""))
    sec_risky_pred = ("HIGH" in sec_summary or "CRITICAL" in sec_summary or sec_score < 70)

    if case.expected_relevant:
        relevance_ok = align_factor >= 0.55 and not llm_off_topic
    else:
        relevance_ok = (align_factor <= 0.30 or llm_off_topic or relevance_warning) and total_score <= 50

    if case.expected_security_risky:
        security_ok = sec_risky_pred
    else:
        security_ok = sec_score >= 70

    score_min_ok = case.min_score is None or total_score >= case.min_score
    score_max_ok = case.max_score is None or total_score <= case.max_score
    align_min_ok = case.min_alignment is None or align_factor >= case.min_alignment
    align_max_ok = case.max_alignment is None or align_factor <= case.max_alignment

    return {
        "total_score": round(total_score, 1),
        "alignment_factor": round(align_factor, 3),
        "llm_off_topic": llm_off_topic,
        "relevance_warning": relevance_warning,
        "pipeline_timeout": bool(report.get("calibrationTimeout")),
        "security_score": round(sec_score, 1),
        "security_summary": sec_summary,
        "relevance_expectation_ok": relevance_ok,
        "security_expectation_ok": security_ok,
        "score_min_ok": bool(score_min_ok),
        "score_max_ok": bool(score_max_ok),
        "alignment_min_ok": bool(align_min_ok),
        "alignment_max_ok": bool(align_max_ok),
        "case_passed": bool(
            relevance_ok
            and security_ok
            and score_min_ok
            and score_max_ok
            and align_min_ok
            and align_max_ok
        ),
    }


async def run_programmatic_suite(
    *,
    scenario_keys: list[str] | None = None,
    max_scenarios: int | None = None,
    max_cases_per_scenario: int | None = None,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    selected = list(SCENARIOS)
    if scenario_keys:
        wanted = {k.strip() for k in scenario_keys if str(k).strip()}
        selected = [s for s in selected if s.key in wanted]
    if max_scenarios and max_scenarios > 0:
        selected = selected[:max_scenarios]

    results: list[dict[str, Any]] = []
    total_cases = 0
    passed_cases = 0

    for scenario in selected:
        brief = _build_brief(scenario.title, scenario.description)
        scenario_rows: list[dict[str, Any]] = []
        submissions = list(scenario.submissions)
        if max_cases_per_scenario and max_cases_per_scenario > 0:
            submissions = submissions[:max_cases_per_scenario]

        for case in submissions:
            code = _read_text(case.file_path)
            report = _programmatic_pipeline_report(brief, case.file_path, code)
            check = _evaluate_case(case, report)
            total_cases += 1
            if check["case_passed"]:
                passed_cases += 1
            scenario_rows.append(
                {
                    "label": case.label,
                    "file_path": case.file_path,
                    "expected_relevant": case.expected_relevant,
                    "expected_security_risky": case.expected_security_risky,
                    "expected_min_score": case.min_score,
                    "expected_max_score": case.max_score,
                    "expected_min_alignment": case.min_alignment,
                    "expected_max_alignment": case.max_alignment,
                    "result": check,
                }
            )

        results.append(
            {
                "scenario_key": scenario.key,
                "assignment_title": scenario.title,
                "criterion_count": scenario.criterion_count,
                "rubric_source": "programmatic",
                "rubric": [],
                "created_assignment": None,
                "cases": scenario_rows,
            }
        )

    pass_rate = round((passed_cases / total_cases) * 100, 1) if total_cases else 0.0
    report = {
        "summary": {
            "total_scenarios": len(selected),
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "pass_rate": pass_rate,
        },
        "scenarios": results,
    }
    if checkpoint_path is not None:
        _write_checkpoint(report, checkpoint_path)
    return report


async def _suggest_rubric(module: Any, scenario: AssignmentScenario) -> list[dict[str, Any]]:
    req = module.RubricSuggestionRequest(
        assignment_title=scenario.title,
        assignment_description=scenario.description,
        criterion_count=scenario.criterion_count,
    )
    out = await asyncio.wait_for(module.suggest_rubric(req), timeout=DEFAULT_TIMEOUT_SECONDS)
    criteria = out.get("criteria", []) if isinstance(out, dict) else []
    if not isinstance(criteria, list) or not criteria:
        raise RuntimeError(f"Rubrik uretilemedi: {scenario.key}")
    return criteria


def _fallback_rubric(module: Any, scenario: AssignmentScenario) -> list[dict[str, Any]]:
    weights = module._rubric_weights_for_count(int(scenario.criterion_count))
    out: list[dict[str, Any]] = []
    for i, w in enumerate(weights):
        name = module._RUBRIC_FALLBACK_NAMES[i % len(module._RUBRIC_FALLBACK_NAMES)]
        out.append(
            {
                "name": name,
                "description": (
                    f"{name} kriteri, {scenario.title} odevinin gereksinimlerini ne kadar "
                    "dogru ve kaliteli karsiladigini olcer."
                ),
                "max_score": int(w),
            }
        )
    return out


async def _maybe_create_demo_assignment(
    module: Any,
    *,
    scenario: AssignmentScenario,
    rubric: list[dict[str, Any]],
    enabled: bool,
) -> dict[str, Any] | None:
    if not enabled:
        return None

    course_id = "44444444-4444-4444-8444-444444444444"
    assignment_req = module.AssignmentCreateRequest(
        course_id=course_id,
        name=f"Kalibrasyon - {scenario.title}",
        description=scenario.description,
        due_date="2026-05-25 23:59",
    )
    assignment = await module.create_assignment(assignment_req)
    assign_id = str(assignment.get("id", "")).strip()
    if not assign_id:
        raise RuntimeError(f"Odev kaydi olusmadi: {scenario.key}")

    upsert_req = module.RubricUpsertRequest(
        assignment_id=assign_id,
        criteria=rubric,
        status="approved",
        created_by="11111111-1111-4111-8111-111111111111",
    )
    await module.upsert_rubric(upsert_req)
    return assignment


async def run_suite(
    *,
    persist_demo_assignments: bool,
    scenario_keys: list[str] | None = None,
    max_scenarios: int | None = None,
    max_cases_per_scenario: int | None = None,
    checkpoint_path: Path | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    os.environ.setdefault("DEMO_MODE", "1")
    module = _load_api_main()

    selected = list(SCENARIOS)
    if scenario_keys:
        wanted = {k.strip() for k in scenario_keys if str(k).strip()}
        selected = [s for s in selected if s.key in wanted]
    if max_scenarios and max_scenarios > 0:
        selected = selected[:max_scenarios]

    results: list[dict[str, Any]] = []
    total_cases = 0
    passed_cases = 0

    for scenario in selected:
        try:
            rubric = await _suggest_rubric(module, scenario)
            rubric_source = "llm"
        except Exception:
            rubric = _fallback_rubric(module, scenario)
            rubric_source = "fallback"
        created_assignment = await _maybe_create_demo_assignment(
            module,
            scenario=scenario,
            rubric=rubric,
            enabled=persist_demo_assignments,
        )

        brief = _build_brief(scenario.title, scenario.description)
        scenario_rows: list[dict[str, Any]] = []

        submissions = list(scenario.submissions)
        if max_cases_per_scenario and max_cases_per_scenario > 0:
            submissions = submissions[:max_cases_per_scenario]

        for case in submissions:
            code = _read_text(case.file_path)
            try:
                report = await asyncio.wait_for(
                    module.run_analysis_pipeline(
                        Path(case.file_path).name,
                        code,
                        assignment_brief=brief,
                        faculty_rubric_criteria=rubric,
                    ),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                report = {
                    "totalScore": 0,
                    "taskAlignment": {"factor": 0.05, "llm_off_topic": False},
                    "relevanceScoreWarning": f"Pipeline timeout after {timeout_seconds}s.",
                    "agents": [],
                    "calibrationTimeout": True,
                }
            check = _evaluate_case(case, report)
            total_cases += 1
            if check["case_passed"]:
                passed_cases += 1

            scenario_rows.append(
                {
                    "label": case.label,
                    "file_path": case.file_path,
                    "expected_relevant": case.expected_relevant,
                    "expected_security_risky": case.expected_security_risky,
                    "expected_min_score": case.min_score,
                    "expected_max_score": case.max_score,
                    "expected_min_alignment": case.min_alignment,
                    "expected_max_alignment": case.max_alignment,
                    "result": check,
                }
            )

        results.append(
            {
                "scenario_key": scenario.key,
                "assignment_title": scenario.title,
                "criterion_count": len(rubric),
                "rubric_source": rubric_source,
                "rubric": rubric,
                "created_assignment": created_assignment,
                "cases": scenario_rows,
            }
        )
        interim = {
            "summary": {
                "total_scenarios": len(selected),
                "total_cases": total_cases,
                "passed_cases": passed_cases,
                "pass_rate": round((passed_cases / total_cases) * 100, 1) if total_cases else 0.0,
            },
            "scenarios": results,
        }
        if checkpoint_path is not None:
            _write_checkpoint(interim, checkpoint_path)

    pass_rate = round((passed_cases / total_cases) * 100, 1) if total_cases else 0.0
    return {
        "summary": {
            "total_scenarios": len(selected),
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "pass_rate": pass_rate,
        },
        "scenarios": results,
    }


def _write_checkpoint(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_console_report(data: dict[str, Any]) -> None:
    summary = data.get("summary", {})
    print("\n=== Agent Calibration Suite ===")
    print(
        "Scenarios: {0}, Cases: {1}, Passed: {2}, Pass Rate: {3}%".format(
            summary.get("total_scenarios", 0),
            summary.get("total_cases", 0),
            summary.get("passed_cases", 0),
            summary.get("pass_rate", 0),
        )
    )
    for scenario in data.get("scenarios", []):
        print(f"\n[{scenario.get('scenario_key')}] {scenario.get('assignment_title')}")
        print(f"Rubric rows: {scenario.get('criterion_count')}")
        for case in scenario.get("cases", []):
            res = case.get("result", {})
            marker = "PASS" if res.get("case_passed") else "FAIL"
            print(
                "- {0:>4} | {1:<22} | score={2:>5} | align={3:>5} | off_topic={4} | sec={5:>5}".format(
                    marker,
                    case.get("label", "?"),
                    res.get("total_score"),
                    res.get("alignment_factor"),
                    res.get("llm_off_topic"),
                    res.get("security_score"),
                )
            )
            if not res.get("case_passed"):
                failed_checks = [
                    name
                    for name in (
                        "relevance_expectation_ok",
                        "security_expectation_ok",
                        "score_min_ok",
                        "score_max_ok",
                        "alignment_min_ok",
                        "alignment_max_ok",
                    )
                    if res.get(name) is False
                ]
                if res.get("pipeline_timeout"):
                    failed_checks.insert(0, "pipeline_timeout")
                print(f"       failed checks: {', '.join(failed_checks) or 'unknown'}")


async def _amain(args: argparse.Namespace) -> int:
    if args.programmatic_only:
        report = await run_programmatic_suite(
            scenario_keys=list(args.scenario or []),
            max_scenarios=args.max_scenarios,
            max_cases_per_scenario=args.max_cases_per_scenario,
            checkpoint_path=REPORT_PATH,
        )
    else:
        report = await run_suite(
            persist_demo_assignments=args.persist_demo_assignments,
            scenario_keys=list(args.scenario or []),
            max_scenarios=args.max_scenarios,
            max_cases_per_scenario=args.max_cases_per_scenario,
            checkpoint_path=REPORT_PATH,
            timeout_seconds=max(30, int(args.timeout_seconds)),
        )
    _write_checkpoint(report, REPORT_PATH)
    _print_console_report(report)
    print(f"\nRapor dosyasi: {REPORT_PATH}")
    summary = report.get("summary", {})
    if summary.get("passed_cases", 0) != summary.get("total_cases", 0):
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentGrade ajan kalibrasyon suite")
    parser.add_argument(
        "--persist-demo-assignments",
        action="store_true",
        help="Demo store'a odev + rubrik kaydi da acar.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Sadece verilen scenario key'ini calistir (birden fazla kez verilebilir).",
    )
    parser.add_argument(
        "--max-scenarios",
        type=int,
        default=None,
        help="Calistirilacak maksimum senaryo sayisi.",
    )
    parser.add_argument(
        "--max-cases-per-scenario",
        type=int,
        default=None,
        help="Her senaryoda calistirilacak maksimum case sayisi.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Tek pipeline case'i icin maksimum bekleme suresi.",
    )
    parser.add_argument(
        "--programmatic-only",
        action="store_true",
        help="LLM pipeline yerine hizli deterministik ajan sinyalleriyle matrisi kos.",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
