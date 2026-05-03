from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_rubric_sanitizer() -> None:
    os.environ.setdefault("DEMO_MODE", "1")
    from frontend.backend.main import _sanitize_rubric_scope

    rows: list[dict[str, Any]] = [
        {
            "name": "Sunum Kalitesi",
            "description": "Slayt ve gorsel duzenini degerlendirir.",
            "max_score": 10,
        },
        {
            "name": "Genel Kalite",
            "description": "Genel olarak iyi olmalidir.",
            "max_score": 10,
        },
        {
            "name": "Genel Kalite",
            "description": "Kodun test, hata yonetimi ve okunabilirlik kanitlarini degerlendirir.",
            "max_score": 10,
        },
        {
            "name": "Test Durumu",
            "description": "Pytest ile tum fonksiyonlar icin birim test yazilmis olmalidir.",
            "max_score": 10,
        },
        {
            "name": "Gelistirme Sureci",
            "description": "Git commitleri ve versiyon kontrol sureci degerlendirilir.",
            "max_score": 10,
        },
        {
            "name": "Yikimlilik",
            "description": "Kodun yikimlilik ve gelistirme sureci acisindan durumu.",
            "max_score": 10,
        },
    ]
    cleaned = _sanitize_rubric_scope(
        rows,
        assignment_title="Ikili Arama Agaci",
        assignment_description="Ekleme, arama ve dolasim fonksiyonlari yazin.",
    )
    names = [str(row["name"]) for row in cleaned]
    lowered = [name.lower() for name in names]
    _assert(len(lowered) == len(set(lowered)), "Rubrikte duplicate kriter adi kaldi.")
    _assert(not any("sunum" in name for name in lowered), "Kod odevinde sunum kriteri kaldi.")
    _assert(
        all(str(row.get("description", "")).strip() for row in cleaned),
        "Tum rubrik satirlarinda aciklama olmali.",
    )
    _assert(
        not any("test" in name for name in lowered),
        "Test istemeyen odevde dedicated test kriteri kaldi.",
    )
    _assert(
        not any("gelistirme" in name or "yikimlilik" in name for name in lowered),
        "Kod kanitina dayanmayan surec/garip rubrik kriteri kaldi.",
    )


def test_task_relevance_capability_signal() -> None:
    from backend.agents.task_relevance import _capability_match_signal, merge_task_alignment

    brief = (
        "Python ile uc seviyeli ic ice listeleri tek boyutlu listeye donusturen, "
        "ortalama ve ozet istatistik ureten fonksiyonlar yazin. Kod test edilebilir olmalidir."
    )
    code = """
def flatten_3d(data):
    flat = []
    for matrix in data:
        for row in matrix:
            flat.extend(row)
    return flat

def average(data):
    flat = flatten_3d(data)
    return sum(flat) / len(flat) if flat else None
"""
    score = _capability_match_signal(brief, None, code)
    _assert(score >= 0.70, f"Liste/veri isleme odevinde capability sinyali dusuk: {score}")

    alignment = merge_task_alignment(
        1.0,
        [],
        {
            "skipped": False,
            "relevance_factor": 0.68,
            "off_topic": False,
            "student_fulfills_assignment": False,
            "explanation": "Teslim ayni CLI/API sekline sahip fakat bir alt teslim eksik gorunuyor.",
            "submission_domain_guess": "log analizi CLI",
            "task_domain_guess": "log ozetleme CLI",
            "capability_match": 0.925,
        },
    )
    _assert(alignment["factor"] >= 0.75, "Guclu capability eslesmesi gorev uyumu cap'ine donusmemeli.")
    _assert(
        "llm_task_not_fulfilled" not in alignment["reasons"],
        "Alakali ama eksik teslim, off-topic gorev uyumu uyarisi uretmemeli.",
    )


def test_test_agent_runtime_contracts() -> None:
    from backend.agents.test_agent import TestAgent
    from backend.sandbox.executor import _simulate_sandbox

    agent = TestAgent()

    runtime_code = "print(1 / 0)"
    runtime_sb = _simulate_sandbox(runtime_code)
    runtime_result = agent._programmatic_analysis(
        runtime_sb,
        "",
        runtime_code,
        "python",
        "Basit Python programi hatasiz calismalidir.",
        task_alignment={"factor": 1.0, "reasons": []},
    )
    _assert(runtime_result["failed_tests"] == 1, "Runtime hata test basarisizligi sayilmali.")
    _assert(runtime_result["score"] <= 35, "Runtime hata TestAgent skorunu 35 ustune cikarmamali.")

    cli_code = """
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("path")
args = parser.parse_args()
print(args.path)
"""
    cli_sb = _simulate_sandbox(cli_code)
    cli_result = agent._programmatic_analysis(
        cli_sb,
        "",
        cli_code,
        "python",
        "Bir dosya yolunu arguman olarak alan CLI araci yazin.",
        task_alignment={"factor": 1.0, "reasons": []},
    )
    _assert(cli_result["runs_successfully"] is True, "CLI usage mesaji runtime hatasi sayilmamali.")
    _assert(cli_result["score"] >= 50, "CLI usage smoke kapsami cok dusuk puanlanmamali.")


def test_master_guards() -> None:
    from backend.agents.master_evaluator import MasterEvaluatorAgent

    runtime_result = {
        "final_score": 95,
        "rubric_breakdown": [
            {
                "criterion": "functionality",
                "label": "Calisabilirlik",
                "weight": 40,
                "score": 38,
                "weighted_score": 38.0,
                "justification": "Ilk LLM yorumu.",
            }
        ],
        "weaknesses": [],
    }
    MasterEvaluatorAgent._apply_runtime_guard(
        runtime_result,
        {"compilation_success": True, "exit_code": 1, "stderr": "ZeroDivisionError"},
        source_code="print(1 / 0)",
        language="python",
        faculty_mode=True,
    )
    _assert(runtime_result["final_score"] <= 55, "Runtime guard final notu cap'lemeli.")

    security_result = {
        "final_score": 95,
        "rubric_breakdown": [
            {
                "criterion": "security",
                "label": "Guvenlik",
                "weight": 20,
                "score": 20,
                "weighted_score": 20.0,
                "justification": "Ilk LLM yorumu.",
            }
        ],
        "weaknesses": [],
    }
    MasterEvaluatorAgent._apply_security_guard(
        security_result,
        {"risk_level": "critical", "critical_count": 1, "high_count": 0, "score": 50},
        faculty_mode=True,
    )
    _assert(security_result["final_score"] <= 65, "Security guard final notu cap'lemeli.")

    faculty_low_result = {
        "final_score": 30,
        "rubric_breakdown": [
            {
                "criterion": f"criterion_{idx}",
                "label": label,
                "weight": 10,
                "score": 3,
                "weighted_score": 3.0,
                "justification": "LLM ilk puani.",
            }
            for idx, label in enumerate(
                [
                    "Dogruluk",
                    "Hata Yonetimi",
                    "Veri Modeli",
                    "Algoritmik Uygunluk",
                    "Kod Stili",
                    "Dokumantasyon",
                    "Gereksinimlere Uyum",
                    "CLI Akisi",
                    "Kenar Durumlar",
                    "Guvenlik",
                ]
            )
        ],
        "recommendations": [],
    }
    MasterEvaluatorAgent._apply_faculty_reasonableness_floor(
        faculty_low_result,
        {
            "final_score": 82,
            "brief_alignment_factor": 0.85,
            "brief_alignment_reasons": [],
        },
    )
    _assert(
        faculty_low_result["final_score"] >= 65,
        "Faculty Master asiri dusuk LLM puanini programatik tabana cekmeli.",
    )


def test_evidence_contracts() -> None:
    from backend.agents.evidence import EvidenceAgent, _build_ast_evidence_map, _normalize_claims

    code = """
def classify(x):
    if x > 10:
        return "big"
    else:
        return "small"
""".strip()
    findings = {
        "code_quality": {
            "issues": [
                {
                    "description": "classify() fonksiyonundaki if-else blogu return ile sadelestirilebilir.",
                    "severity": "medium",
                }
            ]
        },
        "seniority": {
            "immaturity_indicators": [
                "Hayali cache katmani ve olmayan concurrency mekanizmasi kullanilmis gibi yorum yapma."
            ]
        },
        "test_agent": {"runtime_errors": ["ZeroDivisionError: division by zero"]},
    }

    programmatic = EvidenceAgent()._programmatic_analysis(code, findings, "python")
    ast_blocks = _build_ast_evidence_map(code, "python").get("blocks", [])
    normalized = _normalize_claims(
        programmatic["validated_claims"],
        code.splitlines(),
        ast_blocks=ast_blocks,
    )

    block_claims = [claim for claim in normalized if claim.get("line_range")]
    file_claims = [claim for claim in normalized if claim.get("node_type") == "file"]
    _assert(block_claims, "Evidence yapisal iddialari AST blok kanitina baglamali.")
    _assert(file_claims, "Runtime/test log iddialari file-level kanit olarak korunmali.")
    _assert(
        any("somut kanit yok" in str(item) for item in programmatic["rejected_claims"]),
        "Kanitsiz soyut iddia reddedilmeli.",
    )


def test_agent_quality_benchmark() -> None:
    from backend.agents.code_quality import CodeQualityAgent
    from backend.agents.guideline import GuidelineAgent
    from backend.agents.seniority import SeniorityAgent

    nested_code = """
def pair_products(items):
    result = []
    for left in items:
        for right in items:
            result.append((left, right))
    return result
""".strip()
    quality = CodeQualityAgent()._programmatic_analysis(nested_code, "python")
    _assert(quality["time_complexity"] == "O(n^2)", "Quality Agent O(n^2) karmasikligi yakalamali.")
    _assert(
        any(issue["type"] == "high_complexity" for issue in quality["issues"]),
        "Quality Agent ic ice dongu icin high_complexity bulgusu uretmeli.",
    )

    modern_code = """
from dataclasses import dataclass

@dataclass(frozen=True)
class User:
    name: str

def names(users: list[User]) -> list[str]:
    return [user.name for user in users]
""".strip()
    seniority = SeniorityAgent()._programmatic_analysis(modern_code, "python")
    _assert(seniority["score"] >= 70, "Seniority Agent modern Python sinyallerini odullendirmeli.")
    _assert(
        any("dataclass" in item.lower() for item in seniority["maturity_indicators"]),
        "Seniority Agent dataclass kullanimini somut olgunluk sinyali saymali.",
    )

    style_code = """
def BadFunction(X):
    y=1
    if X:
        print(X)
    return y
""".strip()
    guideline = GuidelineAgent()._programmatic_analysis(style_code, "python")
    _assert(guideline["naming_quality"] == "poor", "Guideline Agent kotu isimlendirmeyi yakalamali.")
    _assert(
        any("Fonksiyon isimlendirme" in item["rule"] for item in guideline["style_violations"]),
        "Guideline Agent isimlendirme ihlalini somut bulguya cevirmeli.",
    )


def test_assignment_assistant_long_hint_contracts() -> None:
    os.environ.setdefault("DEMO_MODE", "1")
    from backend.core.config import settings
    from frontend.backend import main as api_main
    from frontend.backend.main import (
        AssignmentAssistantSuggestionsRequest,
        HTTPException,
        _assignment_focus_extra,
        _direct_assignment_suggestion_from_hint,
        _is_detailed_assignment_hint,
        _strip_course_context_from_hint,
    )

    long_hint = (
        "Programlama II (PRG201), 2.sinif, Baslik: Log Dosyasi Ozetleme Araci. "
        "Ogrenciler Python ile komut satirindan bir log dosyasi yolu alan, satirlari seviye bazli "
        "sayip ERROR ve CRITICAL mesajlarini ayri listeleyen bir CLI uygulamasi gelistirsin. "
        "Bozuk satirlari raporlasin, dosya yoksa anlasilir hata mesaji versin, parse fonksiyonlarini "
        "test edilebilir yazsin ve en az uc ornek girdi/cikti senaryosu teslim etsin."
    )
    stripped = _strip_course_context_from_hint(long_hint)
    _assert(stripped.startswith("Baslik:"), "Ders baglami uzun ipucundan ayrilmali.")
    _assert(_is_detailed_assignment_hint(long_hint), "Uzun odev aciklamasi detayli brief sayilmali.")
    direct = _direct_assignment_suggestion_from_hint(long_hint)
    _assert(direct is not None, "Uzun brief dogrudan odev taslagina donusmeli.")
    assert direct is not None
    _assert("Log Dosyasi" in direct["title"], "Taslak basligi egitmen metninden cikmali.")
    _assert("ERROR" in direct["description"], "Taslak aciklamasi kritik teslim kosullarini korumali.")

    short_hint = "agac"
    _assert(
        not _is_detailed_assignment_hint(short_hint),
        "Kisa konu ipucu dogrudan brief olarak yorumlanmamali.",
    )

    original_ollama = settings.ollama_enabled
    try:
        settings.ollama_enabled = False
        response = asyncio.run(
            api_main.assignment_assistant_suggestions(
                AssignmentAssistantSuggestionsRequest(
                    course_hint=long_hint,
                    count=3,
                    difficulty="medium",
                )
            )
        )
    finally:
        settings.ollama_enabled = original_ollama
    suggestions = response.get("suggestions", [])
    _assert(len(suggestions) == 1, "LLM kapaliyken yalnizca uzun brief taslagi korunmali.")
    _assert(
        suggestions[0]["title"] == direct["title"],
        "Uzun brief LLM kapaliyken ilk taslak olarak korunmali.",
    )

    original_ollama = settings.ollama_enabled
    try:
        settings.ollama_enabled = False
        try:
            asyncio.run(
                api_main.assignment_assistant_suggestions(
                    AssignmentAssistantSuggestionsRequest(
                        course_hint="kimya laboratuvar titrasyon verileri icin odev oner",
                        count=3,
                        difficulty="medium",
                    )
                )
            )
        except HTTPException as exc:
            _assert(exc.status_code == 503, "Kisa ipucu LLM kapaliyken programatik odev uretmemeli.")
        else:
            raise AssertionError("Kisa ipucu LLM kapaliyken 503 dondurmeli.")
    finally:
        settings.ollama_enabled = original_ollama

    focus = _assignment_focus_extra("kimya laboratuvar titrasyon verileri icin rapor araci")
    _assert("kimya laboratuvar" in focus, "Serbest konu LLM promptuna korunarak tasinmali.")
    _assert("sabit kategori" in focus.lower(), "Focus metni programatik kategoriye sikismamayi soylemeli.")

    original_ollama = settings.ollama_enabled
    original_chat_json = api_main.chat_json
    calls: list[str] = []

    async def fake_chat_json(**kwargs):
        calls.append(str(kwargs.get("user_prompt", "")))
        if len(calls) == 1:
            return {
                "suggestions": [
                    {
                        "title": "Sera sensor veri okuma",
                        "summary": "Sera sensor CSV verisini okuyan kucuk Python odevi.",
                        "description": "Ogrenciler sera sicaklik ve nem sensor verilerini CSV dosyasindan okuyup temel aralik kontrollerini raporlar.",
                    }
                ]
            }
        return {
            "suggestions": [
                {
                    "title": "Sera sulama karar raporu",
                    "summary": "Sera sensor verilerinden sulama onerisi ureten rapor.",
                    "description": "Ogrenciler sicaklik ve nem esiklerine gore sulama onerisi uretir, hatali satirlari ayirir ve kisa rapor verir.",
                },
                {
                    "title": "Sera nem uyarisi servisi",
                    "summary": "Nem dusuk veya yuksek oldugunda uyari ureten mini servis.",
                    "description": "Ogrenciler sensor girdilerini dogrulayan ve riskli nem araliklari icin JSON uyari donduren kucuk bir servis tasarlar.",
                },
                {
                    "title": "Sera sensor test senaryolari",
                    "summary": "Sensor verisi icin normal, eksik ve aykiri deger testleri.",
                    "description": "Ogrenciler veri okuma fonksiyonlarini ayirir, eksik alan ve aykiri sicaklik gibi kenar durumlari icin test senaryolari yazar.",
                },
            ]
        }

    try:
        settings.ollama_enabled = True
        api_main.chat_json = fake_chat_json
        response = asyncio.run(
            api_main.assignment_assistant_suggestions(
                AssignmentAssistantSuggestionsRequest(
                    course_hint="Tarim teknolojileri: sera sicaklik ve nem sensor verilerinden sulama onerisi",
                    count=4,
                    difficulty="medium",
                )
            )
        )
    finally:
        api_main.chat_json = original_chat_json
        settings.ollama_enabled = original_ollama
    retry_suggestions = response.get("suggestions", [])
    _assert(len(calls) == 2, "Eksik LLM oneri sayisi ikinci LLM denemesi tetiklemeli.")
    _assert(len(retry_suggestions) == 4, "Ilk ve retry LLM onerileri benzersiz sekilde birlesmeli.")


def main() -> int:
    tests = [
        test_rubric_sanitizer,
        test_task_relevance_capability_signal,
        test_test_agent_runtime_contracts,
        test_master_guards,
        test_evidence_contracts,
        test_agent_quality_benchmark,
        test_assignment_assistant_long_hint_contracts,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
