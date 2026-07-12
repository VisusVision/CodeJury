"""Task 10: student-safe algorithmResult projection sentinel tests."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from backend.reporting.student_projection import project_student_result
from frontend.backend import main

SENTINEL_EXPECTATION_ID = "SENTINEL_EXPECTATION_ID_TASK10"
SENTINEL_CACHE_KEY = "SENTINEL_CACHE_KEY_TASK10_UNIQUE"
SENTINEL_VERSION = 424242
SENTINEL_EXTRACTOR_PROVIDER = "SENTINEL_EXTRACTOR_PROVIDER_TASK10"
SENTINEL_EXTRACTOR_MODEL = "SENTINEL_EXTRACTOR_MODEL_TASK10"
SENTINEL_VERIFIER_REASON = "SENTINEL_VERIFIER_REASON_TASK10"
SENTINEL_EXTRACTOR_PROMPT = "SENTINEL_EXTRACTOR_PROMPT_TASK10"
SENTINEL_EVIDENCE_CONFIDENCE = 0.7777777
SENTINEL_RAW_EVIDENCE_DETAIL = "SENTINEL_RAW_EVIDENCE_DETAIL_TASK10 pseudo-code leak"

ALLOWED_ALGORITHM_RESULT_KEYS = frozenset({
    "detectedAlgorithms",
    "dataStructures",
    "timeComplexity",
    "spaceComplexity",
    "actualFamily",
    "actualConfidence",
    "expectedComplexity",
    "expectedApproach",
    "complexityGap",
    "gapSteps",
    "gapExplanation",
    "recommendedApproach",
    "evidence",
})

PRIVATE_ALGORITHM_SENTINELS = (
    SENTINEL_EXPECTATION_ID,
    SENTINEL_CACHE_KEY,
    str(SENTINEL_VERSION),
    SENTINEL_EXTRACTOR_PROVIDER,
    SENTINEL_EXTRACTOR_MODEL,
    SENTINEL_VERIFIER_REASON,
    SENTINEL_EXTRACTOR_PROMPT,
    str(SENTINEL_EVIDENCE_CONFIDENCE),
    SENTINEL_RAW_EVIDENCE_DETAIL,
)


def _private_algorithm_agent(*, include_snake_case: bool = False) -> dict[str, Any]:
    algorithm_result = {
        "detectedAlgorithms": ["hash_lookup"],
        "dataStructures": ["dict"],
        "timeComplexity": "O(n)",
        "spaceComplexity": "O(n)",
        "actualFamily": "single_variable",
        "actualConfidence": 0.95,
        "expectedComplexity": "O(n)",
        "expectedApproach": "hash lookup",
        "expectedFamilies": ["hash_lookup"],
        "expectedSource": "verified_expectation",
        "expectedConfidence": 0.92,
        "expectationVersion": SENTINEL_VERSION,
        "expectationId": SENTINEL_EXPECTATION_ID,
        "cacheKey": SENTINEL_CACHE_KEY,
        "extractorProvider": SENTINEL_EXTRACTOR_PROVIDER,
        "extractorModel": SENTINEL_EXTRACTOR_MODEL,
        "extractorPromptVersion": SENTINEL_EXTRACTOR_PROMPT,
        "verificationReason": SENTINEL_VERIFIER_REASON,
        "complexityGap": "matches_expected",
        "gapSteps": 0,
        "gapExplanation": "Karmasiklik beklentiyle uyumlu.",
        "recommendedApproach": "Tek geciste hash map kullanin.",
        "evidence": [
            {
                "line": 4,
                "kind": "hash_lookup",
                "detail": "dict membership check",
                "confidence": SENTINEL_EVIDENCE_CONFIDENCE,
            },
            {
                "line": 9,
                "kind": "nested_loop",
                "detail": SENTINEL_RAW_EVIDENCE_DETAIL,
                "confidence": 0.1,
            },
        ],
    }
    agent: dict[str, Any] = {
        "id": "algorithm",
        "name": "Algoritma Ajani",
        "summary": "Karmasiklik: O(n), Beklenen: O(n), Durum: matches_expected",
        "score": 88,
        "maxScore": 100,
        "findings": [],
        "algorithmResult": algorithm_result,
        "llm_status": "ok",
        "confidence": 0.9,
        "guardrail_flags": [],
    }
    if include_snake_case:
        agent.update({
            "detected_algorithms": ["ignored_snake"],
            "expectation_version": 999,
            "cache_key": "ignored_cache",
        })
    return agent


def _private_result_with_algorithm(**agent_kwargs: Any) -> dict[str, Any]:
    return {
        "totalScore": 88,
        "maxScore": 100,
        "rubric": {},
        "agents": [_private_algorithm_agent(**agent_kwargs)],
        "fileName": "solution.py",
        "executionTimeMs": 100,
        "memoryUsageMb": 1.0,
        "peakMemoryMb": 1.0,
        "analysisEngine": "agentgrade-v1",
        "summary": "Algorithm summary",
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "taskAlignment": {},
        "reportStatus": "ready",
    }


def _algorithm_agent(projected: dict[str, Any]) -> dict[str, Any]:
    for agent in projected.get("agents", []):
        if agent.get("id") == "algorithm":
            return agent
    raise AssertionError("algorithm agent missing")


class Phase3AlgorithmProjectionTests(unittest.TestCase):
    def test_student_projection_keeps_allowlisted_algorithm_fields(self):
        private = _private_result_with_algorithm()
        projected = project_student_result(private)
        result = _algorithm_agent(projected)["algorithmResult"]

        self.assertEqual(set(result.keys()), ALLOWED_ALGORITHM_RESULT_KEYS)
        self.assertEqual(result["detectedAlgorithms"], ["hash_lookup"])
        self.assertEqual(result["dataStructures"], ["dict"])
        self.assertEqual(result["timeComplexity"], "O(n)")
        self.assertEqual(result["spaceComplexity"], "O(n)")
        self.assertEqual(result["actualFamily"], "single_variable")
        self.assertEqual(result["actualConfidence"], 0.95)
        self.assertEqual(result["expectedComplexity"], "O(n)")
        self.assertEqual(result["expectedApproach"], "hash lookup")
        self.assertEqual(result["complexityGap"], "matches_expected")
        self.assertEqual(result["gapSteps"], 0)
        self.assertEqual(result["gapExplanation"], "Karmasiklik beklentiyle uyumlu.")
        self.assertEqual(result["recommendedApproach"], "Tek geciste hash map kullanin.")
        self.assertEqual(
            result["evidence"],
            [{"line": 4, "kind": "hash_lookup", "detail": "dict membership check"}],
        )

    def test_student_projection_strips_algorithm_provenance_sentinels(self):
        private = _private_result_with_algorithm()
        projected = project_student_result(private)
        serialized = json.dumps(projected)

        for sentinel in PRIVATE_ALGORITHM_SENTINELS:
            self.assertNotIn(sentinel, serialized)

    def test_student_projection_scrubs_provenance_embedded_in_explanation_text(self):
        private = _private_result_with_algorithm()
        algorithm_result = _algorithm_agent(private)["algorithmResult"]
        algorithm_result["gapExplanation"] = (
            f"Beklenti surumu {SENTINEL_VERSION} ve id {SENTINEL_EXPECTATION_ID} "
            f"ile uyumlu; confidence {SENTINEL_EVIDENCE_CONFIDENCE}."
        )
        algorithm_result["recommendedApproach"] = (
            f"Yaklasim {SENTINEL_CACHE_KEY} / {SENTINEL_VERIFIER_REASON}"
        )

        projected = project_student_result(private)
        result = _algorithm_agent(projected)["algorithmResult"]
        serialized = json.dumps(projected)

        for sentinel in (
            SENTINEL_EXPECTATION_ID,
            SENTINEL_CACHE_KEY,
            SENTINEL_VERIFIER_REASON,
        ):
            self.assertNotIn(sentinel, serialized)
            self.assertNotIn(sentinel, str(result.get("gapExplanation", "")))
            self.assertNotIn(sentinel, str(result.get("recommendedApproach", "")))
        # Distinctive low-entropy markers must not remain in student narratives;
        # unsafe fields are dropped rather than substring-mangled.
        self.assertNotIn(str(SENTINEL_VERSION), serialized)
        self.assertNotIn(str(SENTINEL_EVIDENCE_CONFIDENCE), serialized)

    def test_student_projection_does_not_mangle_o1_or_algorithm_names_via_low_entropy_scrub(
        self,
    ):
        private = _private_result_with_algorithm()
        algorithm_result = _algorithm_agent(private)["algorithmResult"]
        algorithm_result["expectationVersion"] = 1
        algorithm_result["expectedConfidence"] = 0.5
        algorithm_result["expectedFamilies"] = ["hash_lookup"]
        algorithm_result["timeComplexity"] = "O(1)"
        algorithm_result["expectedComplexity"] = "O(1)"
        algorithm_result["spaceComplexity"] = "O(1)"
        algorithm_result["recommendedApproach"] = "Use hash_lookup with O(1) access"
        algorithm_result["gapExplanation"] = "Constant-time O(1) hash_lookup matches expectation."

        projected = project_student_result(private)
        result = _algorithm_agent(projected)["algorithmResult"]

        self.assertEqual(result["timeComplexity"], "O(1)")
        self.assertEqual(result["expectedComplexity"], "O(1)")
        self.assertEqual(result["spaceComplexity"], "O(1)")
        self.assertEqual(result["recommendedApproach"], "Use hash_lookup with O(1) access")
        self.assertEqual(
            result["gapExplanation"],
            "Constant-time O(1) hash_lookup matches expectation.",
        )
        self.assertNotIn("expectationVersion", result)
        self.assertNotIn("expectedFamilies", result)

    def test_student_projection_drops_narrative_for_short_provenance_token_hits(
        self,
    ):
        """Short provider/reason values must not substring-mangle student text."""
        private = _private_result_with_algorithm()
        algorithm_result = _algorithm_agent(private)["algorithmResult"]
        algorithm_result["extractorProvider"] = "nim"
        algorithm_result["verificationReason"] = "ok"
        algorithm_result["expectationId"] = "LONG_EXPECTATION_ID_SENTINEL_UNIQUE"
        algorithm_result["cacheKey"] = "LONG_CACHE_KEY_SENTINEL_UNIQUE"
        algorithm_result["recommendedApproach"] = "Use hash_lookup with minimum comparisons"
        algorithm_result["gapExplanation"] = "hash_lookup remains the minimum viable approach"
        algorithm_result["timeComplexity"] = "O(1)"
        algorithm_result["expectedComplexity"] = "O(1)"

        projected = project_student_result(private)
        result = _algorithm_agent(projected)["algorithmResult"]
        serialized = json.dumps(projected)

        self.assertEqual(result["timeComplexity"], "O(1)")
        self.assertEqual(result["expectedComplexity"], "O(1)")
        # No token-boundary hit for ok/nim inside these words → keep intact.
        self.assertEqual(
            result["recommendedApproach"],
            "Use hash_lookup with minimum comparisons",
        )
        self.assertEqual(
            result["gapExplanation"],
            "hash_lookup remains the minimum viable approach",
        )
        self.assertNotIn("hash_loup", serialized)
        self.assertNotIn('"mium"', serialized)
        self.assertNotRegex(serialized, r"(?<![\w])ok(?![\w])")
        self.assertNotRegex(serialized, r"(?<![\w])nim(?![\w])")

    def test_student_projection_drops_field_when_short_provenance_is_whole_token(self):
        private = _private_result_with_algorithm()
        algorithm_result = _algorithm_agent(private)["algorithmResult"]
        algorithm_result["extractorProvider"] = "nim"
        algorithm_result["verificationReason"] = "ok"
        algorithm_result["gapExplanation"] = "Verifier said ok via nim provider."
        algorithm_result["recommendedApproach"] = "Prefer nim when ok."

        projected = project_student_result(private)
        result = _algorithm_agent(projected)["algorithmResult"]

        self.assertNotIn("gapExplanation", result)
        self.assertNotIn("recommendedApproach", result)

    def test_student_projection_does_not_substring_scrub_verified_reason(self):
        private = _private_result_with_algorithm()
        algorithm_result = _algorithm_agent(private)["algorithmResult"]
        algorithm_result["verificationReason"] = "verified"
        algorithm_result["extractorProvider"] = "openai-compatible"
        algorithm_result["extractorModel"] = "gpt-test-model"
        algorithm_result["gapExplanation"] = "This verified approach is fine"
        algorithm_result["recommendedApproach"] = "verified method with hash_lookup"
        algorithm_result["timeComplexity"] = "O(1)"
        algorithm_result["expectedComplexity"] = "O(1)"

        projected = project_student_result(private)
        result = _algorithm_agent(projected)["algorithmResult"]
        serialized = json.dumps(projected)

        self.assertEqual(result["timeComplexity"], "O(1)")
        # Token hit on reason/provider/model → drop narrative; never mangle mid-sentence.
        self.assertNotIn("gapExplanation", result)
        self.assertNotIn("recommendedApproach", result)
        self.assertNotIn("This approach", serialized)
        self.assertNotIn("This  approach", serialized)

    def test_student_projection_does_not_mutate_private_result(self):
        private = _private_result_with_algorithm()
        before = copy.deepcopy(private)
        project_student_result(private)
        self.assertEqual(private, before)

    def test_teacher_private_result_retains_algorithm_provenance(self):
        private = _private_result_with_algorithm()
        algorithm_result = _algorithm_agent(private)["algorithmResult"]
        self.assertIn("expectationId", algorithm_result)
        self.assertIn("cacheKey", algorithm_result)
        self.assertIn("extractorProvider", algorithm_result)
        self.assertEqual(algorithm_result["evidence"][0]["confidence"], SENTINEL_EVIDENCE_CONFIDENCE)

    def test_build_agents_list_attaches_algorithm_result_adapter(self):
        alg = {
            "detected_algorithms": ["hash_lookup"],
            "data_structures": ["dict"],
            "time_complexity": "O(n)",
            "space_complexity": "O(n)",
            "actual_family": "single_variable",
            "actual_confidence": 0.95,
            "expected_complexity": "O(n)",
            "expected_approach": "hash lookup",
            "expected_families": ["hash_lookup"],
            "expected_source": "verified_expectation",
            "expected_confidence": 0.92,
            "expectation_version": 3,
            "complexity_gap": "matches_expected",
            "gap_steps": 0,
            "gap_explanation": "Uyumlu.",
            "recommended_approach": "Hash map kullan.",
            "evidence": [{"line": 2, "kind": "hash_lookup", "detail": "dict use", "confidence": 0.8}],
            "issues": [],
            "score": 90,
            "llm_status": "ok",
            "confidence": 0.9,
            "guardrail_flags": [],
        }
        agents = main._build_agents_list({}, {}, {}, {}, {}, {}, alg, None)
        algorithm = next(agent for agent in agents if agent["id"] == "algorithm")
        result = algorithm["algorithmResult"]
        self.assertEqual(result["detectedAlgorithms"], ["hash_lookup"])
        self.assertEqual(result["timeComplexity"], "O(n)")
        self.assertEqual(result["expectedFamilies"], ["hash_lookup"])
        self.assertEqual(result["expectationVersion"], 3)
        self.assertEqual(result["evidence"][0]["confidence"], 0.8)

    def test_algorithm_result_from_output_preserves_programmatic_base_score(self):
        alg = {
            "detected_algorithms": ["hash_lookup"],
            "data_structures": ["dict"],
            "time_complexity": "O(n^2)",
            "space_complexity": "O(1)",
            "expected_complexity": "O(n)",
            "complexity_gap": "worse_than_expected",
            "gap_steps": 2,
            "gap_explanation": "Two steps worse.",
            "recommended_approach": "Hash map.",
            "evidence": [],
            "score": 45,
            "programmatic_base_score": 90,
        }
        result = main._algorithm_result_from_output(alg)
        self.assertEqual(result["programmatic_base_score"], 90)

    def test_algorithm_result_from_output_omits_programmatic_base_score_when_invalid(self):
        alg = {
            "detected_algorithms": ["hash_lookup"],
            "time_complexity": "O(n)",
            "space_complexity": "O(1)",
            "expected_complexity": "O(n)",
            "complexity_gap": "matches_expected",
            "gap_steps": 0,
            "gap_explanation": "",
            "recommended_approach": "",
            "evidence": [],
            "score": 90,
            "programmatic_base_score": True,
        }
        result = main._algorithm_result_from_output(alg)
        self.assertNotIn("programmatic_base_score", result)


if __name__ == "__main__":
    unittest.main()
