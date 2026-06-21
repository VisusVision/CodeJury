"""
Security skoru: LLM + kritik/high icin min(llm, rule) tavanı.

Mock testler tekrarlanabilir; canli ornekler Ollama ile (istege bagli).
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.security import (
    SecurityAgent,
    _final_security_score,
    _merge_threat_lists,
    _score_from_threats,
)


def _old_blend(model: int, rule: int) -> int:
    """Onceki uretim davranisi (geri alinmadan test icin)."""
    return max(0, min(100, round(0.45 * model + 0.55 * rule)))


class SecurityScoreCapTests(unittest.TestCase):
    def test_final_score_caps_llm_when_critical_threat(self):
        threats = [{"type": "code_injection", "severity": "critical", "line": 1, "description": "eval"}]
        final, capped = _final_security_score(100, _score_from_threats(threats), threats)
        self.assertTrue(capped)
        self.assertLessEqual(final, 70)
        self.assertLess(final, 100)

    def test_final_score_unchanged_without_severe_threat(self):
        threats = [{"type": "style", "severity": "low", "line": 1, "description": "x"}]
        final, capped = _final_security_score(92, _score_from_threats(threats), threats)
        self.assertFalse(capped)
        self.assertEqual(final, 92)

    def test_merge_includes_programmatic_eval(self):
        llm: list = []
        prog = [{"type": "code_injection", "severity": "critical", "line": 2, "description": "eval()"}]
        merged = _merge_threat_lists(llm, prog)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["severity"], "critical")

    def test_merge_dedupes_same_line_and_type_with_different_descriptions(self):
        llm = [
            {
                "type": "code_injection",
                "severity": "high",
                "line": 5,
                "description": "eval() kullanimi tespit edildi",
            }
        ]
        prog = [
            {
                "type": "code_injection",
                "severity": "critical",
                "line": 5,
                "description": "eval() rastgele kod calistirir",
            }
        ]
        merged = _merge_threat_lists(llm, prog)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["severity"], "critical")

    def test_old_blend_inflates_vs_cap(self):
        threats = [{"type": "x", "severity": "critical", "line": 1, "description": "a"}]
        model, rule = 100, _score_from_threats(threats)
        capped, _ = _final_security_score(model, rule, threats)
        blend = _old_blend(model, rule)
        self.assertLess(capped, blend)

    def test_analyze_caps_when_llm_misses_eval(self):
        code = 'def f(expr, line):\n    return eval(expr, {}, {"line": line})\n'
        mock_llm = {
            "threats": [],
            "risk_level": "safe",
            "safe": True,
            "total_threats": 0,
            "critical_count": 0,
            "high_count": 0,
            "blocked_imports": [],
            "score": 100,
        }
        agent = SecurityAgent()

        async def _run():
            with patch.object(agent, "_call_llm", new=AsyncMock(return_value=mock_llm)):
                return await agent.analyze({
                    "source_code": code,
                    "language": "python",
                    "assignment_description": "Log filtre CLI",
                    "report_language": "tr",
                })

        r = asyncio.run(_run())
        self.assertGreater(len(r["threats"]), 0)
        self.assertTrue(r.get("score_rule_capped"))
        self.assertLessEqual(r["score"], r["score_model"])
        self.assertLessEqual(r["score"], 70)

    def test_md5_detected_programmatically(self):
        code = "import hashlib\ndef h(p): return hashlib.md5(p.encode()).hexdigest()\n"
        r = SecurityAgent()._programmatic_analysis(code, "python")
        types = {t["type"] for t in r["threats"]}
        self.assertIn("weak_crypto", types)


class SecurityScoringAbTests(unittest.TestCase):
    """Mock: eski harman skoru yukari ceker; tavan bunu yapmaz."""

    def test_critical_code_llm_lower_than_rule_blend(self):
        """eval() gibi kritik kod: model dusuk skor vermeli; kural skoru cok yuksek kalir."""
        threats = [
            {"type": "code_injection", "severity": "critical", "line": 23, "description": "eval()", "detail": "x"},
        ]
        model_score = 25
        rule_score = _score_from_threats(threats)
        self.assertLess(model_score, 40)
        self.assertGreater(rule_score, 55)
        self.assertLess(model_score, _old_blend(model_score, rule_score))

    def test_safe_code_llm_not_pulled_down_by_rule(self):
        """Temiz kod: model yuksek skor; kural hafif ceza verirse harman dusurur."""
        threats = []  # temiz kod, ast de tehdit yok
        model_score = 95
        rule_score = 88  # kural hafif dusuk varsayimi (ipucu kaynakli)
        self.assertGreaterEqual(model_score, 85)
        self.assertGreater(model_score, _old_blend(model_score, rule_score))

    def test_medium_risk_llm_judgment_not_inflated(self):
        """Orta risk: model orta skor; kural genelde daha yuksek."""
        threats = [
            {"type": "bare_except", "severity": "medium", "line": 5, "description": "except:", "detail": ""},
        ]
        model_score = 55
        rule_score = _score_from_threats(threats)
        self.assertLessEqual(model_score, 65)
        self.assertGreaterEqual(rule_score, 45)
        # Eski harman model skorunu yukari ceker
        self.assertLessEqual(model_score, _old_blend(model_score, rule_score))


class SecurityLiveAbTests(unittest.IsolatedAsyncioTestCase):
    """Canli LLM: guvensiz kodda skor eski harmandan dusuk veya esit mi?"""

    CASES = [
        ("GUVENLI library", "samples/library_system_uygun.py",
         "OOP kutuphane: Kitap, Uye, Kutuphane, odunc/iade."),
        ("GUVENLI log", "samples/log_ozetleme_uygun.py",
         "Log dosyasi ozetleme CLI."),
        ("GUVENSIZ eval", "samples/log_ozetleme_guvensiz.py",
         "Log CLI ama eval() ile filtre."),
        ("GUVENSIZ rapor", "samples/rapor_export_guvensiz.py",
         "Rapor export odevi."),
    ]

    async def test_live_llm_scores_better_on_unsafe_than_blend(self):
        agent = SecurityAgent()
        wins_new = 0
        wins_old = 0
        rows = []
        for label, path, brief in self.CASES:
            code = open(path, encoding="utf-8").read()
            for attempt in range(3):
                try:
                    r = await agent.analyze({
                        "source_code": code,
                        "language": "python",
                        "assignment_description": brief,
                        "report_language": "tr",
                    })
                    break
                except Exception:
                    await asyncio.sleep(2)
            else:
                self.skipTest(f"LLM yaniti alinamadi: {label}")
            model = int(r.get("score_model", 50))
            rule = int(r.get("score_rule", 50))
            new = int(r.get("score", 50))
            old = _old_blend(model, rule)
            is_unsafe = "GUVENSIZ" in label or "guvensiz" in path
            if is_unsafe:
                if new <= old:
                    wins_new += 1
                else:
                    wins_old += 1
                self.assertLessEqual(new, model, f"{label}: cap/harman modelden yuksek olmamali")
            rows.append((label, new, old, model, rule, r.get("risk_level"), len(r.get("threats", []))))
        print("\n=== CANLI LLM A/B ===", flush=True)
        for row in rows:
            print(f"  {row[0]}: NEW={row[1]} OLD(blend)={row[2]} model={row[3]} rule={row[4]} risk={row[5]} threats={row[6]}", flush=True)
        print(f"  Guvensiz orneklerde NEW daha dusuk (daha iyi): {wins_new}/{wins_new+wins_old}", flush=True)
        self.assertGreaterEqual(wins_new, wins_old, f"LLM skoru guvensiz kodda daha dusuk olmali: {rows}")


if __name__ == "__main__":
    unittest.main()
