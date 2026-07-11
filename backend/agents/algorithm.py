from __future__ import annotations

import json
from typing import Any

from backend.agents.algorithm_evidence import (
    build_evidence_algorithm_result,
    build_programmatic_algorithm_result,
    evidence_result_to_output,
    merge_algorithm_results,
    resolve_expectation_input,
)
from backend.agents.algorithm_evidence import _normalize_complexity_gap as normalize_complexity_gap
from backend.agents.algorithm_evidence import _safe_str_list as safe_str_list
from backend.agents.base import BaseAgent, LLMInferenceError, build_llm_user_suffix, format_assignment_context_for_prompt
from backend.agents.json_output_schema import ALGORITHM_OUTPUT_SCHEMA

# Backward-compatible aliases for tests and adapters.
_build_programmatic_algorithm_result = build_programmatic_algorithm_result
_merge_algorithm_results = merge_algorithm_results

_ALGORITHM_SYSTEM_PROMPT = """
You are an algorithm analysis agent for programming assignments.
Return only JSON. Explain the submitted code's algorithmic approach using the provided
deterministic evidence as authoritative facts. You may enrich names and narrative, but you
must not contradict proven complexity, verified expectations, or evidence line numbers.
Be concrete and code-grounded. Do not over-credit inefficient code.
"""

_ALGORITHM_REQUIRED_KEYS = [
    "detected_algorithms",
    "data_structures",
    "time_complexity",
    "space_complexity",
    "expected_complexity",
    "complexity_gap",
    "algorithm_analysis",
    "data_structure_analysis",
    "recommended_approach",
    "issues",
    "score",
]


def _task_alignment_prompt_hint(input_data: dict[str, Any]) -> str:
    task = input_data.get("task_alignment")
    if not isinstance(task, dict):
        return ""
    compact = {
        "factor": task.get("factor"),
        "llm_off_topic": task.get("llm_off_topic"),
        "capability_match": task.get("capability_match"),
        "reasons": (task.get("reasons") or [])[:4],
        "llm_explanation": str(task.get("llm_explanation") or "")[:240],
    }
    return (
        "Task relevance hints (non-binding; adjust score/issues if submission is off-topic):\n"
        f"{json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}\n"
    )


def _normalize_algorithm_issues(issues: Any) -> list[dict[str, Any]]:
    from backend.agents.algorithm_evidence import _normalize_algorithm_issues as normalize_issues

    return normalize_issues(issues)


class AlgorithmAgent(BaseAgent):
    name = "algorithm"
    description = "Algoritma, veri yapisi ve karmasiklik analizi"

    def _pre_schema_normalize(self, result: dict, output_json_schema: dict | None) -> dict:
        if not isinstance(result, dict):
            return result
        normalized = dict(result)
        normalized["complexity_gap"] = normalize_complexity_gap(normalized.get("complexity_gap"))
        normalized["issues"] = _normalize_algorithm_issues(normalized.get("issues"))
        normalized["detected_algorithms"] = safe_str_list(
            normalized.get("detected_algorithms"),
            ["general_iteration"],
        )
        normalized["data_structures"] = safe_str_list(
            normalized.get("data_structures"),
            [],
        )
        return normalized

    async def analyze(self, input_data: dict[str, Any]) -> dict[str, Any]:
        source = str(input_data.get("source_code") or "")
        language = str(input_data.get("language") or "python")
        brief = str(input_data.get("assignment_description") or "")
        algorithm_expectation = input_data.get("algorithm_expectation")

        evidence = build_evidence_algorithm_result(
            source,
            language,
            algorithm_expectation=algorithm_expectation,
            brief=brief,
        )
        programmatic = evidence_result_to_output(evidence)
        from backend.algorithm_analysis.scoring import apply_algorithm_score_guardrail

        decision = apply_algorithm_score_guardrail(
            evidence.programmatic_base_score,
            evidence.programmatic_base_score,
            evidence.gap,
            evidence.evidence,
        )
        programmatic["score"] = decision.score
        programmatic["guardrail_flags"] = list(decision.guardrail_flags)
        source_lines = source.splitlines()
        if source_lines:
            from backend.agents.code_utils import enrich_issue_with_line

            programmatic["issues"] = [
                enrich_issue_with_line(dict(issue), source_lines)
                for issue in programmatic.get("issues", [])
                if isinstance(issue, dict)
            ]

        resolved = resolve_expectation_input(algorithm_expectation, brief=brief)
        expectation_hint = {
            "expected_complexity": (
                resolved.expected_complexity.expression if resolved.expected_complexity else ""
            ),
            "expected_approach": resolved.expected_approach,
            "expected_families": list(resolved.expected_families),
            "expected_source": resolved.expected_source,
        }
        user_prompt = (
            "Analyze this submission's algorithmic behavior.\n"
            f"{format_assignment_context_for_prompt(brief)}\n"
            f"{_task_alignment_prompt_hint(input_data)}"
            f"Language: {language}\n"
            f"Authoritative deterministic evidence (do not contradict): "
            f"{json.dumps(programmatic, ensure_ascii=False)}\n"
            f"Resolved expectation (authoritative when verified): "
            f"{json.dumps(expectation_hint, ensure_ascii=False)}\n"
            "Source code:\n"
            f"{source[:12000]}\n\n"
            "Return JSON with detected_algorithms, data_structures, time_complexity, space_complexity, "
            "expected_complexity, complexity_gap, algorithm_analysis, data_structure_analysis, "
            "recommended_approach, issues, score. Use deterministic evidence for complexity and gap; "
            "provide explanation only.\n"
            f"{build_llm_user_suffix(report_language=str(input_data.get('report_language') or 'tr'))}"
        )
        try:
            llm_result = await self._call_llm(
                system_prompt=_ALGORITHM_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                required_keys=_ALGORITHM_REQUIRED_KEYS,
                output_json_schema=ALGORITHM_OUTPUT_SCHEMA,
            )
        except LLMInferenceError as exc:
            fallback = {**programmatic, "llm_error": str(exc)[:300]}
            return self._with_contract_metadata(
                fallback,
                llm_status="fallback",
                guardrail_flags=["llm_inference_fallback"],
            )

        merged = merge_algorithm_results(
            programmatic,
            llm_result,
            source=source,
            evidence=evidence,
        )
        return self._with_contract_metadata(
            merged,
            llm_status=str(llm_result.get("llm_status") or "ok"),
            guardrail_flags=list(merged.get("guardrail_flags") or []),
            schema_repair_count=int(llm_result.get("schema_repair_count") or 0),
        )
