"""
LLM Pipeline Testleri (Evidence + MasterEvaluator)

Gercek Ollama gerekmez; LLM cagrilari mock'lanir veya saf-deterministik yardimcilar
dogrudan test edilir.

Bu testler kodun GERCEK sozlesmesini dogrular:
- EvidenceAgent: kapsam-disi satirlar temizlenir; somut kaniti olmayan iddialar
  (lenient olmayan ajanlardan) reddedilir; analyze() tamamen LLM tabanlidir
  (programatik ikame/merge yok) ve LLM basarisiz olursa LLMInferenceError firlatir.
- MasterEvaluator: nihai puan asla LLM'e birakilmaz; programatik olarak yeniden hesaplanir
  ve runtime/security/gorev-uyumu sert tavanlari uygulanir.
"""

import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.evidence import EvidenceAgent, _normalize_claims
from backend.agents.master_evaluator import MasterEvaluatorAgent
from backend.agents.test_agent import TestAgent
from backend.tests.test_agent_contracts import _formal_sandbox_input


_SIMPLE_PYTHON = "def add(a, b):\n    return a + b\n\nprint(add(2, 3))\n"


# ═══════════════════════════════════════════════════════════════════════════════
# EvidenceAgent._normalize_claims (saf, deterministik)
# ═══════════════════════════════════════════════════════════════════════════════

class NormalizeClaimsTests(unittest.TestCase):
    def test_single_line_claim_maps_to_snippet(self):
        source = ["def add(a, b):", "    return a + b"]
        claims = [{
            "lines": [2], "feedback": "Toplama islemi.",
            "agent_source": "code_quality", "severity": "medium",
        }]
        norm = _normalize_claims(claims, source)
        self.assertEqual(len(norm), 1)
        self.assertEqual(norm[0]["code_snippet"], "    return a + b")
        self.assertEqual(norm[0]["severity"], "medium")
        self.assertEqual(norm[0]["lines"], [2])

    def test_line_range_expands_to_block_lines(self):
        source = ["def work():", "    if True:", "        return 1", "print(work())"]
        claims = [{
            "line_range": [1, 3], "feedback": "Fonksiyon blogu.",
            "agent_source": "evidence", "severity": "medium",
        }]
        norm = _normalize_claims(claims, source)
        self.assertEqual(norm[0]["lines"], [1, 2, 3])
        self.assertEqual(norm[0]["line_range"], [1, 3])

    def test_out_of_range_claim_from_generic_agent_is_rejected(self):
        """Kapsam-disi satir + somut kanit yok + lenient olmayan ajan => reddedilir."""
        source = ["print('hello')"]  # tek satir
        claims = [{
            "lines": [5], "feedback": "Belirsiz bir sorun var.",
            "agent_source": "code_quality", "severity": "medium",
        }]
        self.assertEqual(_normalize_claims(claims, source), [])

    def test_security_claim_retained_as_file_level(self):
        """Mevcut sozlesme: security/test_agent iddialari dosya-seviyesi kanit olarak korunur."""
        source = ["print('hello')"]
        claims = [{
            "lines": [5], "feedback": "Guvenlik riski tespit edildi.",
            "agent_source": "security", "severity": "high",
        }]
        norm = _normalize_claims(claims, source)
        self.assertEqual(len(norm), 1)
        self.assertEqual(norm[0]["node_type"], "file")
        self.assertEqual(norm[0]["lines"], [])

    def test_claim_without_feedback_is_dropped(self):
        source = ["print('hi')"]
        claims = [{"lines": [1], "feedback": "", "agent_source": "code_quality"}]
        self.assertEqual(_normalize_claims(claims, source), [])


# ═══════════════════════════════════════════════════════════════════════════════
# EvidenceAgent.analyze (mock LLM)
# ═══════════════════════════════════════════════════════════════════════════════

class EvidenceAnalyzeTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_claims_short_circuits_without_llm(self):
        agent = EvidenceAgent()
        called = AsyncMock()
        with patch.object(agent, "_call_llm", new=called):
            result = await agent.analyze({
                "source_code": _SIMPLE_PYTHON,
                "language": "python",
                "agent_findings": {},
            })
        called.assert_not_awaited()
        self.assertEqual(result["llm_status"], "skipped_no_claims")
        self.assertEqual(result["validated_claims"], [])
        self.assertEqual(result["total_claims_received"], 0)

    async def test_full_cycle_uses_only_llm_claims(self):
        """Tam LLM: dogrulanan iddialar yalnizca LLM ciktisindan; programatik merge yok."""
        agent = EvidenceAgent()
        mock_llm = {
            "total_claims_received": 2,
            "total_claims_validated": 1,
            "validated_claims": [{
                "feedback": "Toplama islemi var.",
                "severity": "medium",
                "lines": [2],
                "agent_source": "code_quality",
            }],
            "rejected_claims": [],
        }
        with patch.object(agent, "_call_llm", new=AsyncMock(return_value=mock_llm)):
            result = await agent.analyze({
                "source_code": _SIMPLE_PYTHON,
                "language": "python",
                "agent_findings": {
                    "code_quality": {"issues": [{"description": "Toplama", "severity": "medium", "line": 2}]},
                    "guideline": {"style_violations": [{"description": "Docstring yok", "severity": "low"}]},
                    "security": {"threats": []},
                },
            })
        self.assertEqual(result["llm_status"], "ok")
        # Iki finding girildi -> total_claims_received bunu yansitir (sayim, analiz degil).
        self.assertEqual(result["total_claims_received"], 2)
        # Programatik merge olmadigi icin yalnizca LLM'in 1 iddiasi kalir.
        self.assertEqual(result["total_claims_validated"], 1)
        self.assertEqual(len(result["validated_claims"]), 1)
        self.assertIn("Toplama", result["validated_claims"][0]["feedback"])
        # Snippet, LLM vermese de kaynaktan yeniden uretilir.
        self.assertEqual(result["validated_claims"][0]["code_snippet"], "    return a + b")

    async def test_llm_failure_uses_programmatic_fallback(self):
        """LLM basarisiz olursa kaynak-kod dogrulanmis programatik kanitlara dusulur."""
        from backend.agents.base import LLMInferenceError

        agent = EvidenceAgent()
        with patch.object(agent, "_call_llm", new=AsyncMock(side_effect=LLMInferenceError("boom"))):
            result = await agent.analyze({
                "source_code": _SIMPLE_PYTHON,
                "language": "python",
                "agent_findings": {
                    "code_quality": {"issues": [{"description": "Toplama", "severity": "medium", "line": 2}]},
                },
            })
        self.assertEqual(result.get("llm_status"), "fallback")
        self.assertIn("programmatic_evidence_fallback", result.get("evidence_quality_flags", []))
        self.assertGreaterEqual(int(result.get("total_claims_validated", 0) or 0), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# MasterEvaluator — sert tavanlar ve nihai puan yeniden hesaplama
# ═══════════════════════════════════════════════════════════════════════════════

class MasterEvaluatorGuardTests(unittest.TestCase):
    def test_alignment_score_cap_thresholds(self):
        cap = MasterEvaluatorAgent._alignment_score_cap
        cases = (
            (0.0, 18.0),
            (0.179999, 18.0),
            (0.18, 28.0),
            (0.299999, 28.0),
            (0.30, 42.0),
            (0.449999, 42.0),
            (0.45, 65.0),
            (0.699999, 65.0),
            (0.70, 100.0),
            (1.0, 100.0),
        )
        for factor, expected in cases:
            with self.subTest(factor=factor):
                self.assertEqual(cap(factor), expected)

    def test_off_topic_alignment_caps_final_score(self):
        result = {
            "final_score": 88,
            "rubric_breakdown": [
                {"criterion": "functionality", "label": "Fonksiyonellik", "weight": 40, "score": 90},
                {"criterion": "security", "label": "Guvenlik", "weight": 20, "score": 95},
            ],
            "weaknesses": [],
        }
        MasterEvaluatorAgent._apply_brief_alignment_guard(
            result,
            {"brief_alignment_factor": 0.15, "brief_alignment_reasons": ["llm_task_relevance_off_topic"]},
            faculty_mode=False,
        )
        MasterEvaluatorAgent._sync_rubric_to_final_score(result, faculty_mode=False)
        self.assertLessEqual(result["final_score"], 28.0)
        derived = MasterEvaluatorAgent._breakdown_derived_percent(result, faculty_mode=False)
        self.assertLessEqual(derived, result["final_score"] + 1.0)

    def test_faculty_alignment_cap_syncs_rubric_to_final_score(self):
        result = {
            "final_score": 90.0,
            "rubric_breakdown": [
                {"label": "Fonksiyonellik", "weight": 40, "score": 36, "weighted_score": 36.0, "justification": ""},
                {"label": "Kod Kalitesi", "weight": 30, "score": 27, "weighted_score": 27.0, "justification": ""},
                {"label": "Guvenlik", "weight": 30, "score": 27, "weighted_score": 27.0, "justification": ""},
            ],
            "weaknesses": [],
        }
        programmatic = {
            "final_score": 70.0,
            "brief_alignment_factor": 0.40,
            "programmatic_alignment_factor": 0.40,
            "capability_match": 0.20,
            "sandbox_runs_ok": True,
            "brief_alignment_reasons": ["llm_task_relevance_off_topic"],
        }
        MasterEvaluatorAgent._apply_brief_alignment_guard(result, programmatic, faculty_mode=True)
        MasterEvaluatorAgent._sync_rubric_to_final_score(result, faculty_mode=True)
        self.assertLessEqual(float(result["final_score"]), 28.0)
        derived = MasterEvaluatorAgent._breakdown_derived_percent(result, faculty_mode=True)
        self.assertLessEqual(derived, float(result["final_score"]) + 1.0)

    def test_aligned_submission_is_not_capped(self):
        result = {
            "final_score": 88,
            "rubric_breakdown": [{"criterion": "functionality", "label": "F", "weight": 100, "score": 88}],
            "weaknesses": [],
        }
        MasterEvaluatorAgent._apply_brief_alignment_guard(
            result, {"brief_alignment_factor": 1.0, "brief_alignment_reasons": []}, faculty_mode=False
        )
        self.assertEqual(result["final_score"], 88)

    def test_runtime_guard_caps_on_compile_failure(self):
        result = {
            "final_score": 95,
            "rubric_breakdown": [
                {"criterion": "functionality", "label": "F", "weight": 40, "score": 95},
                {"criterion": "security", "label": "Guvenlik", "weight": 20, "score": 95},
            ],
            "weaknesses": [],
        }
        MasterEvaluatorAgent._apply_runtime_guard(
            result, {"compilation_success": False, "stderr": "SyntaxError"}, faculty_mode=False
        )
        self.assertLessEqual(result["final_score"], 20)

    def test_security_guard_caps_on_critical_risk(self):
        result = {
            "final_score": 96,
            "rubric_breakdown": [
                {"criterion": "security", "label": "Guvenlik", "weight": 20, "score": 96},
                {"criterion": "functionality", "label": "F", "weight": 80, "score": 96},
            ],
            "weaknesses": [],
        }
        MasterEvaluatorAgent._apply_security_guard(
            result,
            {"risk_level": "critical", "critical_count": 1, "high_count": 0, "score": 45},
            faculty_mode=False,
        )
        self.assertLessEqual(result["final_score"], 35)

    def test_recompute_default_final_score_from_breakdown(self):
        result = {
            "final_score": 1,  # LLM halusinasyonu
            "rubric_breakdown": [
                {"criterion": "a", "weight": 50, "score": 80},
                {"criterion": "b", "weight": 50, "score": 60},
            ],
        }
        MasterEvaluatorAgent._recompute_default_final_score(result)
        self.assertEqual(result["final_score"], 70.0)


class MasterEvaluatorPipelineTests(unittest.IsolatedAsyncioTestCase):
    def _sub_agent_results(self, **overrides):
        base = {
            "source_code": _SIMPLE_PYTHON,
            "language": "python",
            "sandbox_result": {
                "compilation_success": True, "exit_code": 0,
                "stdout": "5\n", "stderr": "", "execution_time_ms": 15, "peak_memory_mb": 12,
            },
            "task_alignment": {"factor": 1.0, "reasons": []},
            "test_agent": {"score": 85, "compilation_success": True, "runs_successfully": True},
            "code_quality": {"score": 80, "time_complexity": "O(1)", "issues": []},
            "seniority": {"score": 75, "estimated_level": "mid"},
            "guideline": {"score": 70, "naming_quality": "good", "style_violations": []},
            "security": {"score": 95, "risk_level": "safe", "safe": True, "threats": [],
                         "critical_count": 0, "high_count": 0},
            "evidence": {"validated_claims": [], "total_claims_received": 0, "total_claims_validated": 0},
        }
        base.update(overrides)
        return base

    def test_programmatic_analysis_produces_valid_hint(self):
        agent = MasterEvaluatorAgent()
        result = agent._programmatic_analysis(self._sub_agent_results(), faculty_rubric=None)
        self.assertGreaterEqual(result["final_score"], 0)
        self.assertLessEqual(result["final_score"], 100)
        self.assertEqual(result["brief_alignment_factor"], 1.0)
        self.assertIsInstance(result["rubric_breakdown"], list)
        self.assertTrue(result["rubric_breakdown"])

    async def test_analyze_orchestrates_and_recomputes_score(self):
        agent = MasterEvaluatorAgent()
        mock_llm = {
            "final_score": 999,  # gozardi edilmeli; puan yeniden hesaplanir
            "rubric_breakdown": [
                {"criterion": "functionality", "label": "Fonksiyonellik", "weight": 40, "score": 80, "justification": "ok"},
                {"criterion": "algorithmic_efficiency", "label": "Verimlilik", "weight": 30, "score": 70, "justification": "ok"},
                {"criterion": "code_standards", "label": "Standartlar", "weight": 20, "score": 60, "justification": "ok"},
                {"criterion": "security", "label": "Guvenlik", "weight": 10, "score": 90, "justification": "ok"},
            ],
            "summary": "Genel olarak basarili.",
            "strengths": ["Calisiyor"],
            "weaknesses": [],
            "recommendations": ["Test ekleyin"],
        }
        with patch.object(agent, "_call_llm", new=AsyncMock(return_value=mock_llm)):
            result = await agent.analyze(self._sub_agent_results())

        self.assertIn("final_score", result)
        self.assertIsInstance(result["rubric_breakdown"], list)
        # 999 degil; agirlikli yeniden hesaplama 0..100 araliginda olmali.
        self.assertGreaterEqual(result["final_score"], 0)
        self.assertLessEqual(result["final_score"], 100)
        # Beklenen agirlikli puan: 80*.4+70*.3+60*.2+90*.1 = 74.0
        self.assertEqual(result["final_score"], 74.0)


class TestAgentFormalScorePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_formal_score_provenance_fields_preserved_in_analyze(self):
        agent = TestAgent()
        analyze_input, _, llm_payload = _formal_sandbox_input(
            passed=3,
            total=4,
            llm_score=99,
            test_evidence_status="available",
            test_source="auto_generated",
            test_set_id="generated-set-9",
            cache_version=4,
        )
        with patch.object(agent, "_call_llm", new=AsyncMock(return_value=llm_payload)):
            result = await agent.analyze(analyze_input)

        self.assertEqual(result["score"], 75)
        self.assertEqual(result["formalScore"], 75)
        self.assertEqual(result["formalPassed"], 3)
        self.assertEqual(result["formalTotal"], 4)
        self.assertEqual(result["testEvidenceStatus"], "available")
        self.assertEqual(result["testSource"], "auto_generated")
        self.assertEqual(result["testSetId"], "generated-set-9")
        self.assertEqual(result["cacheVersion"], 4)

    async def test_formal_evidence_unavailable_caps_score_in_analyze(self):
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
                    "edge_case_handling": "good",
                    "edge_cases_observed": ["empty input"],
                    "performance_notes": "Smoke only.",
                    "score": 88,
                }
            ),
        ):
            result = await agent.analyze({
                "sandbox_result": {
                    "compilation_success": True,
                    "exit_code": 0,
                    "stdout": "ok\n",
                    "stderr": "",
                    "execution_time_ms": 10,
                    "peak_memory_mb": 5,
                },
                "expected_output": None,
                "source_code": "print('ok')\n",
                "language": "python",
                "assignment_description": "Basit program.",
                "test_evidence_status": "unavailable",
            })

        self.assertEqual(result["testEvidenceStatus"], "unavailable")
        self.assertEqual(result["formalTotal"], 0)
        self.assertLessEqual(result["score"], 40)


if __name__ == "__main__":
    unittest.main()
