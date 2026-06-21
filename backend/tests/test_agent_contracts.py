import unittest
import tempfile
from unittest.mock import AsyncMock, patch

from backend.agents.assignment_alignment import compute_brief_code_alignment
from backend.agents.code_quality import CodeQualityAgent
from backend.agents.code_utils import get_code_metrics
from backend.agents.guideline import GuidelineAgent
from backend.agents.evidence import _normalize_claims, _normalize_rejected_claims
from backend.agents.master_evaluator import MasterEvaluatorAgent
from backend.agents.security import SecurityAgent
from backend.agents.seniority import SeniorityAgent
from backend.agents.task_relevance import (
    _capability_match_signal,
    _has_recognized_capability_requirement,
    assess_task_relevance_llm,
    deterministic_task_capability_match,
    merge_task_alignment,
)
from backend.core.config import settings
from backend.agents.test_agent import (
    TestAgent,
    _looks_like_cli_usage_error,
    _looks_like_service_program,
)
from backend.sandbox.executor import _simulate_sandbox
from frontend.backend.main import _build_agent_diagnostics, _build_agents_list, _build_line_evidence


class TaskRelevanceContractTests(unittest.TestCase):
    def test_capability_match_detects_cli_file_assignment(self):
        brief = "Python ile log dosyasi okuyup komut satiri argumaniyla seviye bazli ozet ureten CLI yazin."
        code = "import sys\nwith open(sys.argv[1]) as f:\n    print(f.read().splitlines())\n"

        self.assertGreaterEqual(_capability_match_signal(brief, None, code), 0.8)

    def test_capability_match_rejects_superficial_line_variable(self):
        brief = "Python ile log dosyasi okuyup komut satiri argumaniyla seviye bazli ozet ureten CLI yazin."
        code = 'api_key = "abcdefghijklmnopqrstuvwxyz123456"\ndef summarize(lines):\n    return {"INFO": len(lines)}\n'

        self.assertLess(_capability_match_signal(brief, None, code), 0.25)

    def test_capability_match_detects_react_frontend_assignment(self):
        brief = (
            "React ile gorev listesi uygulamasi gelistirin; useState ile form durumunu yonetin, "
            "gorev ekleme/silme ve tamamlandi filtresi olsun."
        )
        code = """
import React, { useState } from 'react';

export function TodoApp() {
  const [items, setItems] = useState([]);
  const [text, setText] = useState('');
  const addTask = () => setItems([...items, { text, done: false }]);
  const removeTask = (index) => setItems(items.filter((_, i) => i !== index));
  return <form onSubmit={addTask}><input value={text} onChange={e => setText(e.target.value)} /></form>;
}
"""

        self.assertGreaterEqual(_capability_match_signal(brief, None, code), 0.8)

    def test_capability_match_detects_plain_html_css_assignment(self):
        brief = (
            "HTML ve CSS ile responsive kisisel portfolyo sayfasi hazirlayin; "
            "header, proje kartlari ve mobil medya sorgusu bulunmali."
        )
        code = """
<!doctype html>
<html>
  <head>
    <style>
      header { display: flex; }
      .projects { display: grid; gap: 1rem; }
      @media (max-width: 640px) { .projects { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body><header>Ayse</header><section class="projects"><article>Proje</article></section></body>
</html>
"""

        self.assertGreaterEqual(_capability_match_signal(brief, None, code), 0.75)

    def test_capability_match_detects_cpp_vector_algorithm_assignment(self):
        brief = (
            "C++ ile vektor icindeki sayilari siralayan, en kucuk ve en buyuk degeri bulan "
            "fonksiyonlari yazin."
        )
        code = """
#include <algorithm>
#include <vector>

std::vector<int> sorted_values(std::vector<int> values) {
    std::sort(values.begin(), values.end());
    return values;
}

int min_value(const std::vector<int>& values) { return *std::min_element(values.begin(), values.end()); }
int max_value(const std::vector<int>& values) { return *std::max_element(values.begin(), values.end()); }
"""

        self.assertGreaterEqual(_capability_match_signal(brief, None, code), 0.75)

    def test_merge_downgrades_high_llm_score_when_capability_missing(self):
        merged = merge_task_alignment(
            1.0,
            [],
            {
                "relevance_factor": 0.9,
                "off_topic": False,
                "student_fulfills_assignment": True,
                "capability_match": 0.0,
                "explanation": "Model yanlis iyimser.",
            },
        )

        self.assertLessEqual(merged["factor"], 0.22)
        self.assertTrue(merged["llm_off_topic"])
        self.assertIn("llm_task_relevance_off_topic", merged["reasons"])

    def test_merge_softens_false_off_topic_when_capability_matches(self):
        merged = merge_task_alignment(
            1.0,
            [],
            {
                "relevance_factor": 0.15,
                "off_topic": True,
                "student_fulfills_assignment": False,
                "capability_match": 0.86,
                "explanation": "Model yanlis alakasiz dedi.",
            },
        )

        self.assertFalse(merged["llm_off_topic"])
        self.assertGreaterEqual(merged["factor"], 0.75)
        self.assertNotIn("llm_task_relevance_off_topic", merged["reasons"])

    def test_merge_rewrites_contradictory_explanation_after_softening_off_topic(self):
        merged = merge_task_alignment(
            1.0,
            [],
            {
                "relevance_factor": 0.15,
                "off_topic": True,
                "student_fulfills_assignment": False,
                "capability_match": 0.86,
                "explanation": "Odevle baglantisi yok; yanlis odev yuklenmis.",
                "submission_domain_guess": "log dosya isleme",
                "task_domain_guess": "log ozetleme CLI",
            },
        )

        self.assertFalse(merged["llm_off_topic"])
        self.assertNotIn("baglantisi yok", merged["llm_explanation"].lower())
        self.assertIn("kismi", merged["llm_explanation"].lower())

    def test_merge_flags_deterministic_fallback_mismatch_without_llm(self):
        merged = merge_task_alignment(
            1.0,
            [],
            {
                "skipped": False,
                "relevance_factor": 0.22,
                "off_topic": True,
                "student_fulfills_assignment": False,
                "capability_match": 0.0,
                "explanation": "Deterministik kontrol kodun istenen CLI/dosya kabiliyetlerini tasimadigini buldu.",
                "reason": "deterministic_capability_mismatch",
            },
        )

        self.assertLessEqual(merged["factor"], 0.22)
        self.assertTrue(merged["llm_off_topic"])
        self.assertIn("llm_task_relevance_off_topic", merged["reasons"])

    def test_capability_requirement_markers_do_not_match_word_fragments(self):
        false_positive_briefs = [
            "Tarih posteri tasarlayin ve kaynaklari listeleyin.",
            "Istatistik verisi uzerine kisa makale yazin.",
            "Minimum gereksinimleri aciklayan rapor hazirlayin.",
        ]

        for brief in false_positive_briefs:
            with self.subTest(brief=brief):
                self.assertFalse(_has_recognized_capability_requirement(brief))

    def test_capability_match_handles_short_explicit_api_brief(self):
        brief = "SQLite ogrenci kayit API yazin."
        unrelated = "def fibonacci(n):\n    return n if n < 2 else fibonacci(n - 1) + fibonacci(n - 2)\n"
        matching = """
import sqlite3
from fastapi import FastAPI

app = FastAPI()

@app.post("/students")
def create_student(name: str):
    conn = sqlite3.connect("students.db")
    conn.execute("CREATE TABLE IF NOT EXISTS students (name TEXT)")
    conn.execute("INSERT INTO students VALUES (?)", (name,))
    conn.commit()
    return {"name": name}
"""

        self.assertLess(_capability_match_signal(brief, None, unrelated), 0.25)
        self.assertGreaterEqual(_capability_match_signal(brief, None, matching), 0.75)

    def test_capability_match_detects_api_client_config_assignment(self):
        brief = (
            "Ortam degiskeninden API_URL okuyan, verilen path icin HTTP durum kodu alan "
            "ve gecersiz konfigurasyonu anlasilir hatayla reddeden API istemcisi yazin."
        )
        code = """
import os
import urllib.request

def base_url_from_env():
    return os.environ.get("API_URL", "https://example.com")

def fetch_status(path="/health"):
    with urllib.request.urlopen(base_url_from_env() + path, timeout=5) as response:
        return response.status
"""

        self.assertGreaterEqual(_capability_match_signal(brief, None, code), 0.75)

    def test_task_relevance_uses_rubric_to_support_short_grade_average_brief(self):
        brief = "Python ile ogrenci not ortalamasi hesaplayan ve gecme kalma durumunu yazdiran program."
        rubric = [
            {"name": "Ortalama hesaplama", "description": "Not listesinin ortalamasini dogru hesaplar."},
            {"name": "Gecme kalma", "description": "Ortalamaya gore gecme kalma durumunu raporlar."},
        ]
        code = """
def calculate_average(grades):
    if not grades:
        return 0
    return sum(grades) / len(grades)

status = "gecti" if calculate_average([80, 90, 100]) >= 60 else "kaldi"
print(status)
"""

        brief_only = _capability_match_signal(brief, None, code)
        with_rubric = _capability_match_signal(brief, rubric, code)

        self.assertLess(brief_only, 0.25)
        self.assertGreaterEqual(with_rubric, 0.75)
        self.assertGreaterEqual(
            deterministic_task_capability_match(brief, rubric, code),
            0.75,
        )


class AgentDiagnosticsContractTests(unittest.TestCase):
    def test_diagnostics_are_safe_and_optional(self):
        diagnostics = _build_agent_diagnostics(
            {
                "code_quality": {
                    "score": 82,
                    "llm_status": "repaired",
                    "confidence": 0.7,
                    "guardrail_flags": ["json_schema_repair"],
                },
                "master": {"final_score": 78, "llm_status": "ok"},
            },
            task_alignment={
                "factor": 0.8,
                "llm_factor": 0.75,
                "llm_skipped": False,
                "llm_off_topic": False,
                "reasons": [],
            },
        )

        self.assertIn("agents", diagnostics)
        self.assertIn("taskAlignment", diagnostics)
        self.assertIn("lastLlmCall", diagnostics)
        self.assertNotIn("prompt", str(diagnostics).lower())
        self.assertEqual(diagnostics["agents"][0]["llm_status"], "repaired")

    def test_frontend_agent_findings_are_normalized_and_deduplicated(self):
        agents = _build_agents_list(
            {
                "time_complexity": "O(n)",
                "score": 80,
                "issues": [
                    {"description": "  Ayni bulgu  ", "severity": "HIGH", "line": 2},
                    {"description": "Ayni bulgu", "severity": "high", "line": 2},
                    {"description": "", "severity": "medium", "line": 3},
                ],
            },
            {"estimated_level": "mid", "score": 70, "immaturity_indicators": [], "maturity_indicators": []},
            {
                "naming_quality": "good",
                "score": 75,
                "style_violations": [
                    {"description": "Satir bosluk sorunu", "severity": "medium", "line_hint": "Satir 4"},
                ],
            },
            {"risk_level": "safe", "total_threats": 0, "score": 100, "threats": []},
            {
                "compilation_success": True,
                "runs_successfully": True,
                "passed_tests": 1,
                "failed_tests": 0,
                "score": 90,
            },
            {"total_claims_received": 0, "total_claims_validated": 0, "validated_claims": []},
        )

        quality = next(agent for agent in agents if agent["id"] == "quality")
        guideline = next(agent for agent in agents if agent["id"] == "guideline")
        self.assertEqual(len(quality["findings"]), 1)
        self.assertEqual(quality["findings"][0]["severity"], "error")
        self.assertEqual(quality["findings"][0]["message"], "Ayni bulgu")
        self.assertEqual(guideline["findings"][0]["line"], 4)

    def test_evidence_rejected_claims_stay_out_of_student_findings(self):
        agents = _build_agents_list(
            {"time_complexity": "O(n)", "score": 80, "issues": []},
            {"estimated_level": "mid", "score": 70, "immaturity_indicators": [], "maturity_indicators": []},
            {"naming_quality": "good", "score": 75, "style_violations": []},
            {"risk_level": "safe", "total_threats": 0, "score": 100, "threats": []},
            {
                "compilation_success": True,
                "runs_successfully": True,
                "passed_tests": 1,
                "failed_tests": 0,
                "score": 90,
            },
            {
                "total_claims_received": 2,
                "total_claims_validated": 1,
                "validated_claims": [
                    {
                        "feedback": "Somut bulgu",
                        "severity": "medium",
                        "lines": [1],
                        "agent_source": "code_quality",
                        "code_snippet": "print(1)",
                    }
                ],
                "rejected_claims": [
                    {"agent_source": "guideline", "claim": "Docstring yok", "reason": "Somut kanit yok"}
                ],
            },
        )

        evidence = next(agent for agent in agents if agent["id"] == "evidence")
        messages = [finding["message"] for finding in evidence["findings"]]
        self.assertEqual(messages, ["Somut bulgu"])
        self.assertIn("reddedilen: 1", evidence["summary"])

    def test_line_evidence_ignores_out_of_range_and_duplicate_findings(self):
        evidence = _build_line_evidence(
            {"issues": []},
            {"style_violations": []},
            {"threats": []},
            {
                "validated_claims": [
                    {"feedback": "Tekrar eden sorun", "severity": "high", "lines": [1]},
                    {"feedback": "Tekrar eden sorun", "severity": "high", "lines": [1]},
                    {"feedback": "Yok satir", "severity": "medium", "lines": [99]},
                ]
            },
            "print(1)\n",
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["line"], 1)
        self.assertEqual(evidence[0]["severity"], "error")

    def test_line_evidence_deduplicates_punctuation_variants(self):
        evidence = _build_line_evidence(
            {"issues": []},
            {"style_violations": []},
            {"threats": []},
            {
                "validated_claims": [
                    {"feedback": "Ayni bulgu", "severity": "high", "lines": [1]},
                    {"feedback": "Ayni bulgu.", "severity": "high", "lines": [1]},
                ]
            },
            "print(1)\n",
        )

        self.assertEqual(len(evidence), 1)

    def test_line_evidence_deduplicates_same_semantic_issue_across_agents(self):
        evidence = _build_line_evidence(
            {"issues": []},
            {"style_violations": []},
            {"threats": []},
            {
                "validated_claims": [
                    {
                        "feedback": "Satir 2: Bare 'except:' kullanilmis.",
                        "severity": "high",
                        "lines": [2],
                        "agent_source": "code_quality",
                    },
                    {
                        "feedback": "Anti-pattern: Bare 'except:' kullanilmis (satir 2).",
                        "severity": "medium",
                        "lines": [2],
                        "agent_source": "seniority",
                    },
                    {
                        "feedback": "Satir 4: len(rows) ile bolme yapiliyor; rows bos ise ZeroDivisionError olusabilir.",
                        "severity": "high",
                        "lines": [4],
                        "agent_source": "code_quality",
                    },
                    {
                        "feedback": "Anti-pattern: len(rows) ile bolme yapiliyor; rows bos ise ZeroDivisionError olusabilir.",
                        "severity": "medium",
                        "lines": [4],
                        "agent_source": "guideline",
                    },
                    {
                        "feedback": "run_report() fonksiyonu iki ic ice dongu icerir ve O(n^2) karmasikliga sahip.",
                        "severity": "high",
                        "lines": [5],
                        "agent_source": "code_quality",
                    },
                    {
                        "feedback": "run_report() fonksiyonu iki ic ice dongu icerir ve O(n^2) karmasikliga sahip olabilir.",
                        "severity": "high",
                        "lines": [5],
                        "agent_source": "code_quality",
                    },
                ]
            },
            "try:\nexcept:\nrows = []\nreturn total / len(rows)\ndef run_report():\n",
        )

        self.assertEqual(len(evidence), 3)
        self.assertEqual([item["line"] for item in evidence], [2, 4, 5])

    def test_line_evidence_removes_wrong_sql_tail_from_shell_and_eval_messages(self):
        code = "os.system('cat ' + path)\nvalue = eval(expr)\n"
        evidence = _build_line_evidence(
            {"issues": []},
            {"style_violations": []},
            {"threats": []},
            {
                "validated_claims": [
                    {
                        "feedback": "Shell komutu calistiriyor. SQL injection saldirilarina acik olabilir.",
                        "severity": "critical",
                        "lines": [1],
                        "agent_source": "security",
                    },
                    {
                        "feedback": "Rastgele kod calistiriyor. SQL injection saldirilarina acik olabilir.",
                        "severity": "critical",
                        "lines": [2],
                        "agent_source": "security",
                    },
                ]
            },
            code,
        )

        self.assertEqual(len(evidence), 2)
        self.assertNotIn("SQL injection", evidence[0]["message"])
        self.assertNotIn("SQL injection", evidence[1]["message"])

    def test_line_evidence_excludes_unvalidated_raw_agent_findings(self):
        evidence = _build_line_evidence(
            {
                "issues": [
                    {"description": "Kanitsiz ham bulgu", "severity": "high", "line": 1},
                ]
            },
            {
                "style_violations": [
                    {"description": "Kanitsiz stil bulgusu", "severity": "medium", "line_hint": "Satir 1"},
                ]
            },
            {
                "threats": [
                    {"description": "Kanitsiz guvenlik bulgusu", "severity": "high", "line": 1},
                ]
            },
            {"validated_claims": []},
            "print(1)\n",
        )

        self.assertEqual(evidence, [])


class EvidenceNormalizationContractTests(unittest.TestCase):
    def test_validated_claim_snippet_is_rebuilt_from_source(self):
        source = ["def add(a, b):", "    return a + b"]
        claims = [
            {
                "lines": [2],
                "code_snippet": "print('hallucinated')",
                "feedback": "```Kodda toplama islemi var.```",
                "agent_source": "code_quality",
                "severity": "HIGH",
            }
        ]

        normalized = _normalize_claims(claims, source)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["code_snippet"], "    return a + b")
        self.assertEqual(normalized[0]["feedback"], "Kodda toplama islemi var.")
        self.assertEqual(normalized[0]["severity"], "high")

    def test_validated_claim_prefers_line_mentioned_in_feedback(self):
        source = [
            "def run_report(user_name, path):",
            "    query = \"SELECT * FROM students WHERE name = '\" + user_name + \"'\"",
            "    cur.execute(query)",
            "    rows = cur.fetchall()",
        ]
        claims = [
            {
                "lines": [4],
                "feedback": "Satir 2: SQL sorgusunda kullanıcı girdisi string olarak kullanılmıştır.",
                "agent_source": "code_quality",
                "severity": "high",
            }
        ]

        normalized = _normalize_claims(claims, source)

        self.assertEqual(normalized[0]["lines"], [2])
        self.assertIn("SELECT", normalized[0]["code_snippet"])

    def test_validated_claim_rejects_quoted_literal_on_wrong_mentioned_line(self):
        source = [
            "conn = sqlite3.connect(\"grades.db\")",
            "cur = conn.cursor()",
            "cur.execute(query)",
            "return total / len(rows)",
        ]
        claims = [
            {
                "lines": [3],
                "feedback": "Satir 3: 'grades.db' adinda sabit bir dizi kullanilmistir.",
                "agent_source": "code_quality",
                "severity": "low",
            }
        ]

        normalized = _normalize_claims(claims, source)

        self.assertEqual(normalized, [])

    def test_validated_claim_moves_quoted_literal_to_matching_line_in_block(self):
        source = [
            "try:",
            "    risky()",
            "except:",
            "    pass",
        ]
        claims = [
            {
                "lines": [1],
                "line_range": [1, 4],
                "feedback": "Bu blokta 'except:' kullanilmis.",
                "agent_source": "code_quality",
                "severity": "high",
            }
        ]

        normalized = _normalize_claims(claims, source)

        self.assertEqual(normalized[0]["lines"], [3])
        self.assertIn("except:", normalized[0]["code_snippet"])

    def test_block_claim_lines_are_kept_inside_range(self):
        source = [
            "def work():",
            "    if True:",
            "        return 1",
            "print(work())",
        ]
        claims = [
            {
                "lines": [4],
                "line_range": [1, 3],
                "feedback": "Fonksiyon blogu dogrulandi.",
                "agent_source": "evidence",
                "severity": "medium",
            }
        ]

        normalized = _normalize_claims(claims, source)

        self.assertEqual(normalized[0]["lines"], [1, 2, 3])
        self.assertIn("def work", normalized[0]["code_snippet"])

    def test_rejected_claims_are_structured(self):
        rejected = [
            "[guideline] 'Docstring yok' -- somut kanit yok",
            {"agent_source": "security", "claim": "Tehdit var", "reason": "Kodda ilgili satir yok"},
        ]

        normalized = _normalize_rejected_claims(rejected, ["def f(): pass"])

        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["agent_source"], "guideline")
        self.assertIn("Docstring", normalized[0]["claim"])
        self.assertTrue(normalized[0]["reason"])


class CodeComplexityContractTests(unittest.TestCase):
    def test_sequential_loops_and_sorted_are_not_quadratic(self):
        code = """
def print_report(category_revenue, invalid_rows):
    for category, revenue in sorted(category_revenue.items()):
        print(category, revenue)
    for item in invalid_rows:
        print(item)
"""

        metrics = get_code_metrics(code, "python")
        by_name = {fn.name: fn for fn in metrics.functions}

        self.assertEqual(by_name["print_report"].complexity, "O(n log n)")

    def test_division_by_len_without_empty_guard_is_antipattern(self):
        code = """
def average(rows):
    total = sum(rows)
    return total / len(rows)
"""

        metrics = get_code_metrics(code, "python")
        antipatterns = {item["type"]: item for item in metrics.antipatterns}

        self.assertIn("division_by_len_without_empty_guard", antipatterns)
        self.assertEqual(antipatterns["division_by_len_without_empty_guard"]["line"], 4)


class GuidelineContractTests(unittest.TestCase):
    def test_filters_contradictory_snake_case_warning(self):
        merged = GuidelineAgent._merge_llm_with_programmatic(
            {
                "naming_quality": "poor",
                "documentation_quality": "poor",
                "clean_code_score": 50,
                "style_guide_compliance": "PEP8",
                "style_violations": [
                    {
                        "rule": "Naming",
                        "description": "Fonksiyon isimlerinde snake_case kullanılmıştır. Örneğin, 'fibonacci' yerine 'calculate_fibonacci' kullanılması daha uygun olacaktır.",
                        "line_hint": "",
                        "severity": "medium",
                    }
                ],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 40,
            },
            {
                "naming_quality": "good",
                "documentation_quality": "poor",
                "clean_code_score": 70,
                "style_guide_compliance": "PEP8",
                "style_violations": [],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 70,
            },
        )

        self.assertEqual(merged["style_violations"], [])

    def test_filters_file_path_and_valid_snake_case_naming_warnings(self):
        merged = GuidelineAgent._merge_llm_with_programmatic(
            {
                "naming_quality": "fair",
                "documentation_quality": "fair",
                "clean_code_score": 70,
                "style_guide_compliance": "PEP8",
                "style_violations": [
                    {
                        "rule": "Naming",
                        "description": "'rapor.csv' dosya adi PascalCase kullanilmis; snake_case tercih edilmeli.",
                        "line_hint": "15",
                        "severity": "low",
                    },
                    {
                        "rule": "Naming",
                        "description": "export_report fonksiyonu icin snake_case kullanin.",
                        "line_hint": "8",
                        "severity": "medium",
                    },
                    {
                        "rule": "PEP8",
                        "description": "Satir 12 cok uzun (120 karakter).",
                        "line_hint": "12",
                        "severity": "low",
                    },
                ],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 70,
            },
            {
                "naming_quality": "good",
                "documentation_quality": "fair",
                "clean_code_score": 75,
                "style_guide_compliance": "PEP8",
                "style_violations": [],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 75,
            },
        )

        rules = [v["rule"] for v in merged["style_violations"]]
        self.assertEqual(rules, ["PEP8"])

    def test_filters_camelcase_recommendation_for_python_snake_case_function(self):
        merged = GuidelineAgent._merge_llm_with_programmatic(
            {
                "naming_quality": "poor",
                "documentation_quality": "poor",
                "clean_code_score": 40,
                "style_guide_compliance": "PEP8",
                "style_violations": [
                    {
                        "rule": "Naming",
                        "description": "Fonksiyon 'export_report' camelCase kullanmalidir.",
                        "line_hint": "10",
                        "severity": "warning",
                    },
                    {
                        "rule": "PEP257",
                        "description": "Fonksiyon 'export_report' icin docstring yaziniz.",
                        "line_hint": "10",
                        "severity": "warning",
                    },
                ],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 40,
            },
            {
                "naming_quality": "good",
                "documentation_quality": "poor",
                "clean_code_score": 70,
                "style_guide_compliance": "PEP8",
                "style_violations": [],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 70,
            },
            language="python",
        )

        rules = [v["rule"] for v in merged["style_violations"]]
        self.assertEqual(rules, ["PEP257"])

    def test_filters_false_uppercase_claim_for_snake_case_function(self):
        merged = GuidelineAgent._merge_llm_with_programmatic(
            {
                "naming_quality": "poor",
                "documentation_quality": "poor",
                "clean_code_score": 30,
                "style_guide_compliance": "PEP8",
                "style_violations": [
                    {
                        "rule": "Naming",
                        "description": (
                            "Fonksiyon 'count_words' büyük harfle başlıyor. Bunun yerine "
                            "'count_words' gibi küçük harfle başlayan isimler kullanilmalidir."
                        ),
                        "line_hint": "10",
                        "severity": "warning",
                    },
                    {
                        "rule": "PEP257",
                        "description": "Fonksiyon 'count_words' icin docstring yok.",
                        "line_hint": "10",
                        "severity": "error",
                    },
                ],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 30,
            },
            {
                "naming_quality": "good",
                "documentation_quality": "poor",
                "clean_code_score": 60,
                "style_guide_compliance": "PEP8",
                "style_violations": [],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 60,
            },
            language="python",
        )

        rules = [v["rule"] for v in merged["style_violations"]]
        self.assertEqual(rules, ["PEP257"])

    def test_filters_source_file_name_casing_warning(self):
        merged = GuidelineAgent._merge_llm_with_programmatic(
            {
                "naming_quality": "fair",
                "documentation_quality": "fair",
                "clean_code_score": 50,
                "style_guide_compliance": "PEP8",
                "style_violations": [
                    {
                        "rule": "Naming",
                        "description": "Dosya 'main.py' PascalCase olarak yazilmistir. Bu PEP 8 onerisine aykiridir.",
                        "line_hint": "1",
                        "severity": "warning",
                    },
                    {
                        "rule": "PEP257",
                        "description": "Fonksiyon 'export_report' icin docstring yaziniz.",
                        "line_hint": "10",
                        "severity": "warning",
                    },
                ],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 50,
            },
            {
                "naming_quality": "good",
                "documentation_quality": "poor",
                "clean_code_score": 70,
                "style_guide_compliance": "PEP8",
                "style_violations": [],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 70,
            },
            language="python",
        )

        rules = [v["rule"] for v in merged["style_violations"]]
        self.assertEqual(rules, ["PEP257"])

    def test_keeps_camelcase_recommendation_for_javascript(self):
        merged = GuidelineAgent._merge_llm_with_programmatic(
            {
                "naming_quality": "poor",
                "documentation_quality": "fair",
                "clean_code_score": 60,
                "style_guide_compliance": "Airbnb",
                "style_violations": [
                    {
                        "rule": "Naming",
                        "description": "Function 'export_report' should use camelCase.",
                        "line_hint": "10",
                        "severity": "warning",
                    }
                ],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 60,
            },
            {
                "naming_quality": "fair",
                "documentation_quality": "fair",
                "clean_code_score": 65,
                "style_guide_compliance": "Airbnb",
                "style_violations": [],
                "has_docstrings": False,
                "has_type_hints": False,
                "function_length_ok": True,
                "nesting_depth_ok": True,
                "dry_violations": [],
                "score": 65,
            },
            language="javascript",
        )

        rules = [v["rule"] for v in merged["style_violations"]]
        self.assertEqual(rules, ["Naming"])

    def test_capability_match_keeps_unsafe_file_export_relevant(self):
        brief = "Ogrenci skorlarini CSV rapor dosyasina yazan CLI export araci gelistirin."
        code = """
import os

def export_report(path, text):
    os.system("echo " + text + " > " + path)
"""

        self.assertGreaterEqual(_capability_match_signal(brief, None, code), 0.50)

    def test_capability_match_does_not_match_marker_fragments(self):
        brief = "Minimum gereksinimleri aciklayan rapor hazirlayin."
        code = "print('rapor')\n"

        self.assertLess(_capability_match_signal(brief, None, code), 0.25)


class TaskRelevanceFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_disabled_uses_deterministic_capability_mismatch(self):
        brief = "Python ile log dosyasi okuyup komut satiri argumaniyla seviye bazli ozet ureten CLI yazin."
        code = "def fibonacci(n):\n    return n if n < 2 else fibonacci(n - 1) + fibonacci(n - 2)\n"

        with patch.object(settings, "ollama_enabled", False):
            result = await assess_task_relevance_llm(
                assignment_description=brief,
                source_code=code,
                rubric_criteria=None,
                report_language="tr",
            )

        self.assertFalse(result["skipped"])
        self.assertTrue(result["off_topic"])
        self.assertLessEqual(result["relevance_factor"], 0.24)
        self.assertEqual(result["reason"], "deterministic_capability_mismatch")


class AlignmentContractTests(unittest.TestCase):
    def test_empty_or_placeholder_submission_is_penalized(self):
        factor, reasons = compute_brief_code_alignment(
            "Binary search tree ekleme, arama ve inorder dolasim fonksiyonlarini yazin.",
            "print('hello')\n",
        )

        self.assertLess(factor, 0.7)
        self.assertTrue(reasons)


class TestAgentContractTests(unittest.TestCase):
    def test_cli_usage_error_is_not_runtime_failure(self):
        code = "import sys\nif len(sys.argv) < 2:\n    raise SystemExit('usage: app FILE')\nprint(sys.argv[1])\n"
        result = TestAgent()._programmatic_analysis(
            {
                "compilation_success": True,
                "exit_code": 2,
                "stderr": "usage: app FILE",
                "stdout": "",
            },
            expected=None,
            source_code=code,
            language="python",
            assignment_description="Komut satiri argumani alan CLI uygulamasi yazin.",
        )

        self.assertTrue(_looks_like_cli_usage_error("usage: app FILE"))
        self.assertTrue(result["runs_successfully"])
        self.assertEqual(result["failed_tests"], 0)
        self.assertGreaterEqual(result["score"], 70)

    def test_cli_usage_summary_is_clear_for_argument_driven_programs(self):
        agents = _build_agents_list(
            {"time_complexity": "O(n)", "score": 80, "issues": []},
            {"estimated_level": "mid", "score": 70, "immaturity_indicators": [], "maturity_indicators": []},
            {"naming_quality": "good", "score": 75, "style_violations": []},
            {"risk_level": "safe", "total_threats": 0, "score": 100, "threats": []},
            {
                "compilation_success": True,
                "runs_successfully": True,
                "passed_tests": 1,
                "failed_tests": 0,
                "score": 72,
                "performance_notes": (
                    "CLI tipi program arguman bekliyor; formal test girdisi verilmedigi icin "
                    "kullanim mesaji runtime hatasi sayilmadi."
                ),
                "edge_case_handling": "fair",
            },
            {"total_claims_received": 0, "total_claims_validated": 0, "validated_claims": []},
        )

        testing = next(agent for agent in agents if agent["id"] == "testing")
        self.assertIn("CLI arguman bekliyor", testing["summary"])
        self.assertNotIn("Uç durum: fair", testing["summary"])

    def test_service_timeout_is_not_failure_for_server_assignment(self):
        code = "from http.server import HTTPServer, BaseHTTPRequestHandler\nHTTPServer(('127.0.0.1', 8000), BaseHTTPRequestHandler).serve_forever()\n"
        result = TestAgent()._programmatic_analysis(
            {
                "compilation_success": True,
                "exit_code": 124,
                "timed_out": True,
                "execution_time_ms": 30000,
            },
            expected=None,
            source_code=code,
            language="python",
            assignment_description="HTTP API server endpointleri gelistirin.",
        )

        self.assertTrue(_looks_like_service_program(code, "python"))
        self.assertTrue(result["runs_successfully"])
        self.assertGreaterEqual(result["score"], 60)


class TestAgentLLMContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_passing_aligned_smoke_run_keeps_programmatic_score_floor_when_llm_is_pessimistic(self):
        code = "def add(a, b):\n    return a + b\n\nprint(add(2, 3))\n"
        agent = TestAgent()

        with patch.object(
            agent,
            "_call_llm",
            new=AsyncMock(
                return_value={
                    "compilation_success": True,
                    "runs_successfully": True,
                    "passed_tests": 1,
                    "failed_tests": 0,
                    "test_failures": [],
                    "runtime_errors": [],
                    "edge_case_handling": "poor",
                    "edge_cases_observed": [],
                    "performance_notes": "Calisti ancak formal test yok.",
                    "score": 40,
                }
            ),
        ):
            result = await agent.analyze({
                "sandbox_result": {
                    "compilation_success": True,
                    "exit_code": 0,
                    "stdout": "5\n",
                    "stderr": "",
                    "execution_time_ms": 15,
                    "peak_memory_mb": 12,
                },
                "expected_output": "",
                "source_code": code,
                "language": "python",
                "assignment_description": "Python ile iki sayiyi toplayan ve sonucu yazdiran basit bir fonksiyon yazin.",
                "task_alignment": {"factor": 1.0, "reasons": []},
            })

        self.assertGreaterEqual(result["score"], 80)

    async def test_service_timeout_keeps_programmatic_success_when_llm_is_pessimistic(self):
        code = "from http.server import HTTPServer, BaseHTTPRequestHandler\nHTTPServer(('127.0.0.1', 8000), BaseHTTPRequestHandler).serve_forever()\n"
        agent = TestAgent()

        with patch.object(
            agent,
            "_call_llm",
            new=AsyncMock(
                return_value={
                    "compilation_success": True,
                    "runs_successfully": False,
                    "passed_tests": 0,
                    "failed_tests": 1,
                    "test_failures": [{"test_name": "timeout", "reason": "timeout"}],
                    "runtime_errors": ["Timeout"],
                    "edge_case_handling": "poor",
                    "edge_cases_observed": [],
                    "performance_notes": "timeout",
                    "score": 25,
                }
            ),
        ):
            result = await agent.analyze(
                {
                    "sandbox_result": {
                        "compilation_success": True,
                        "exit_code": 124,
                        "timed_out": True,
                        "execution_time_ms": 30000,
                    },
                    "expected_output": None,
                    "source_code": code,
                    "language": "python",
                    "assignment_description": "HTTP API server endpointleri gelistirin.",
                }
            )

        self.assertTrue(result["runs_successfully"])
        self.assertEqual(result["failed_tests"], 0)
        self.assertGreaterEqual(result["score"], 60)


class MasterEvaluatorContractTests(unittest.TestCase):
    def test_service_timeout_does_not_cap_programmatic_functionality(self):
        code = "from http.server import HTTPServer, BaseHTTPRequestHandler\nHTTPServer(('127.0.0.1', 8000), BaseHTTPRequestHandler).serve_forever()\n"
        result = MasterEvaluatorAgent()._programmatic_analysis(
            {
                "source_code": code,
                "language": "python",
                "assignment_description": "HTTP API server endpointleri gelistirin.",
                "sandbox_result": {
                    "compilation_success": True,
                    "exit_code": 124,
                    "timed_out": True,
                    "execution_time_ms": 30000,
                },
                "task_alignment": {"factor": 1.0, "reasons": []},
                "test_agent": {"score": 68},
                "code_quality": {"score": 80},
                "seniority": {"score": 75},
                "guideline": {"score": 70},
                "security": {"score": 93},
                "evidence": {"validated_claims": []},
            },
            faculty_rubric=[
                {"name": "API", "description": "Endpoint davranisi", "max_score": 10},
                {"name": "Kod Kalitesi", "description": "Okunabilirlik", "max_score": 10},
            ],
        )

        functionality = next(row for row in result["rubric_breakdown"] if row["criterion"] == "functionality")
        self.assertEqual(functionality["score"], 68)
        self.assertGreaterEqual(result["final_score"], 65)

    def test_sandbox_fallback_uses_system_tempdir(self):
        real_tempdir = tempfile.TemporaryDirectory
        calls = []

        def tracking_tempdir(*args, **kwargs):
            calls.append((args, kwargs))
            return real_tempdir(*args, **kwargs)

        with patch("tempfile.TemporaryDirectory", side_effect=tracking_tempdir):
            result = _simulate_sandbox("print(1)\n")

        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"].strip(), "1")
        self.assertTrue(calls)


class SecurityAgentContractTests(unittest.TestCase):
    def test_hardcoded_secret_is_critical(self):
        result = SecurityAgent()._programmatic_analysis('api_key = "abcdefghijklmnopqrstuvwxyz"\n', "python")

        self.assertEqual(result["risk_level"], "critical")
        self.assertGreaterEqual(result["critical_count"], 1)
        self.assertLessEqual(result["score"], 70)

    def test_expected_http_server_network_use_is_calibrated(self):
        threats = [
            {
                "type": "network_access",
                "severity": "high",
                "description": "http server",
                "detail": "httpserver",
            }
        ]
        calibrated = SecurityAgent._calibrate_coursework_threats(
            threats,
            source_code="from http.server import HTTPServer\n",
            assignment_description="HTTP API server endpointleri gelistirin.",
        )

        self.assertEqual(calibrated[0]["severity"], "medium")
        self.assertIn("odev baglaminda", calibrated[0]["description"])

    def test_constant_getattr_for_coursework_model_is_low_risk(self):
        code = """
class User:
    def __init__(self):
        self.name = "Ada"

def display(user):
    return getattr(user, "name", "unknown")
"""
        result = SecurityAgent()._programmatic_analysis(code, "python")

        self.assertTrue(result["safe"])
        self.assertLessEqual(result["risk_level"], "low")
        self.assertGreaterEqual(result["score"], 95)

    def test_read_only_file_io_is_safe_for_file_processing_assignment(self):
        code = """
from pathlib import Path

def summarize(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return {"lines": len(lines)}
"""
        result = SecurityAgent()._programmatic_analysis(
            code,
            "python",
            assignment_description="Log dosyasini okuyup satir sayisi ve ozet istatistik ureten CLI yazin.",
        )

        self.assertTrue(result["safe"])
        self.assertLessEqual(result["risk_level"], "low")
        self.assertGreaterEqual(result["score"], 90)

    def test_command_execution_stays_critical_even_in_cli_assignment(self):
        code = """
import os

def run(path):
    os.system("cat " + path)
"""
        result = SecurityAgent()._programmatic_analysis(
            code,
            "python",
            assignment_description="Dosya yolu alan CLI araci yazin.",
        )

        self.assertEqual(result["risk_level"], "critical")
        self.assertFalse(result["safe"])
        descriptions = "\n".join(threat["description"] for threat in result["threats"]).lower()
        self.assertIn("os.system", descriptions)
        self.assertNotIn("import os", descriptions)

    def test_expected_http_client_use_is_calibrated(self):
        code = """
import requests

def fetch_status(url):
    response = requests.get(url, timeout=5)
    return response.status_code
"""
        result = SecurityAgent()._programmatic_analysis(
            code,
            "python",
            assignment_description="HTTP API istemcisi yazin; verilen URL icin durum kodu dondursun.",
        )

        self.assertTrue(result["safe"])
        self.assertLessEqual(result["risk_level"], "low")
        self.assertGreaterEqual(result["score"], 90)


class QualityGuidelineSeniorityContractTests(unittest.TestCase):
    def test_code_quality_flags_unexpected_quadratic_nested_loops(self):
        code = "def has_pair(xs):\n    for a in xs:\n        for b in xs:\n            if a + b == 10:\n                return True\n    return False\n"
        result = CodeQualityAgent()._programmatic_analysis(code, "python")

        self.assertTrue(any(issue["type"] == "high_complexity" for issue in result["issues"]))
        self.assertLess(result["score"], 90)

    def test_guideline_flags_bad_naming_and_flat_script(self):
        code = "\n".join([f"X{i}=i" for i in range(12)]) + "\n"
        result = GuidelineAgent()._programmatic_analysis(code, "python")

        self.assertTrue(any("Kod organizasyonu" in v["rule"] for v in result["style_violations"]))
        self.assertLess(result["score"], 80)

    def test_seniority_rewards_typed_documented_oop_code(self):
        code = '''
class Counter:
    """Counts values."""
    def __init__(self) -> None:
        self.total = 0

    def add(self, value: int) -> int:
        """Add a value and return total."""
        self.total += value
        return self.total

if __name__ == "__main__":
    print(Counter().add(3))
'''
        result = SeniorityAgent()._programmatic_analysis(code, "python")

        self.assertIn(result["estimated_level"], {"mid", "senior"})
        self.assertGreaterEqual(result["score"], 60)
        self.assertTrue(result["design_patterns"])


class MasterEvaluatorGuardTests(unittest.TestCase):
    def test_runtime_guard_caps_compile_failure(self):
        result = {
            "final_score": 95,
            "rubric_breakdown": [
                {"criterion": "functionality", "label": "Calisabilirlik", "weight": 40, "score": 95},
                {"criterion": "security", "label": "Guvenlik", "weight": 20, "score": 95},
            ],
            "weaknesses": [],
        }

        MasterEvaluatorAgent._apply_runtime_guard(
            result,
            {"compilation_success": False, "stderr": "SyntaxError"},
            faculty_mode=False,
        )

        self.assertLessEqual(result["final_score"], 20)
        self.assertIn("Derleme basarisiz", result["weaknesses"][0])

    def test_security_guard_caps_critical_risk(self):
        result = {
            "final_score": 96,
            "rubric_breakdown": [
                {"criterion": "security", "label": "Guvenlik", "weight": 20, "score": 96},
                {"criterion": "functionality", "label": "Fonksiyonellik", "weight": 80, "score": 96},
            ],
            "weaknesses": [],
        }

        MasterEvaluatorAgent._apply_security_guard(
            result,
            {"risk_level": "critical", "critical_count": 1, "high_count": 0, "score": 45},
            faculty_mode=False,
        )

        self.assertLessEqual(result["final_score"], 55)
        self.assertIn("Kritik guvenlik", result["weaknesses"][0])

    def test_faculty_security_floor_raises_clean_security_row(self):
        result = {
            "final_score": 50,
            "rubric_breakdown": [
                {"criterion": "criterion_0", "label": "Guvenlik", "weight": 8, "score": 1, "weighted_score": 1},
                {"criterion": "criterion_1", "label": "Fonksiyonellik", "weight": 12, "score": 9, "weighted_score": 9},
            ],
        }

        MasterEvaluatorAgent._apply_faculty_security_floor(
            result,
            {"risk_level": "safe", "critical_count": 0, "high_count": 0, "score": 100},
        )

        by_label = {row["label"]: row for row in result["rubric_breakdown"]}
        self.assertEqual(by_label["Guvenlik"]["score"], 8)
        self.assertEqual(result["final_score"], 85.0)

    def test_faculty_security_floor_does_not_raise_high_risk_row(self):
        result = {
            "final_score": 50,
            "rubric_breakdown": [
                {"criterion": "criterion_0", "label": "Guvenlik", "weight": 8, "score": 1, "weighted_score": 1},
            ],
        }

        MasterEvaluatorAgent._apply_faculty_security_floor(
            result,
            {"risk_level": "critical", "critical_count": 1, "high_count": 0, "score": 55},
        )

        self.assertEqual(result["rubric_breakdown"][0]["score"], 1)

    def test_faculty_rubric_output_keeps_order_and_recomputes_score(self):
        faculty = [
            {"name": "Fonksiyonellik", "description": "Calisir", "max_score": 40},
            {"name": "Guvenlik", "description": "Risk yok", "max_score": 20},
        ]
        result = {
            "rubric_breakdown": [
                {"criterion": "wrong", "score": 50, "justification": "iyi"},
                {"criterion": "wrong2", "score": 100, "justification": "tam"},
            ]
        }

        MasterEvaluatorAgent._finalize_faculty_rubric_output(result, faculty)

        self.assertEqual([r["label"] for r in result["rubric_breakdown"]], ["Fonksiyonellik", "Guvenlik"])
        self.assertEqual([r["criterion"] for r in result["rubric_breakdown"]], ["criterion_0", "criterion_1"])
        self.assertEqual(result["rubric_breakdown"][0]["score"], 20)
        self.assertEqual(result["rubric_breakdown"][1]["score"], 20)
        self.assertEqual(result["final_score"], 66.7)

    def test_faculty_output_caps_missing_pdf_and_graph_deliverables(self):
        faculty = [
            {"name": "PDF Raporu", "description": "PDF formatinda rapor uretir.", "max_score": 10},
            {"name": "Grafik Oluşturma", "description": "matplotlib ile grafik olusturur.", "max_score": 10},
            {"name": "CSV Okuma", "description": "CSV okur.", "max_score": 10},
        ]
        result = {
            "rubric_breakdown": [
                {"label": "PDF Raporu", "weight": 10, "score": 8, "weighted_score": 8, "justification": "PDF iyi."},
                {"label": "Grafik Oluşturma", "weight": 10, "score": 8, "weighted_score": 8, "justification": "Grafik iyi."},
                {"label": "CSV Okuma", "weight": 10, "score": 8, "weighted_score": 8, "justification": "CSV var."},
            ],
            "weaknesses": [],
        }

        MasterEvaluatorAgent._finalize_faculty_rubric_output(result, faculty)
        MasterEvaluatorAgent._apply_missing_deliverable_caps(
            result,
            source_code="import csv\nprint('Kategori bazli gelir')\n",
            faculty=faculty,
        )

        by_label = {row["label"]: row for row in result["rubric_breakdown"]}
        self.assertLessEqual(by_label["PDF Raporu"]["score"], 2)
        self.assertLessEqual(by_label["Grafik Oluşturma"]["score"], 2)
        self.assertEqual(by_label["CSV Okuma"]["score"], 8)


if __name__ == "__main__":
    unittest.main()
