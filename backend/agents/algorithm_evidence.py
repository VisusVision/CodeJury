from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.algorithm_analysis.ast_facts import extract_python_facts
from backend.algorithm_analysis.complexity import normalize_complexity
from backend.algorithm_analysis.contracts import (
    AlgorithmDetection,
    AlgorithmEvidence,
    ComplexityEstimate,
    GapResult,
)
from backend.algorithm_analysis.detectors import detect_algorithms
from backend.algorithm_analysis.gap import compare_expected_actual
from backend.algorithm_analysis.scoring import apply_algorithm_score_guardrail
from backend.agents.code_utils import enrich_issue_with_line
from backend.agents.json_output_schema import normalize_agent_severity

_COMPLEXITY_GAP_VALUES = frozenset(
    {"unknown", "worse_than_expected", "matches_expected", "better_than_expected"}
)
_LOW_CONFIDENCE_CPP_JAVA = 0.35
_PROGRAMMATIC_BASE_SCORE = 90


@dataclass(frozen=True)
class ResolvedExpectation:
    expected_complexity: ComplexityEstimate | None = None
    expected_approach: str = ""
    expected_families: tuple[str, ...] = ()
    expected_source: str = "unknown"
    expected_confidence: float = 0.0
    expectation_version: int | None = None


@dataclass(frozen=True)
class EvidenceAlgorithmResult:
    detected_algorithms: tuple[str, ...]
    data_structures: tuple[str, ...]
    time_complexity: ComplexityEstimate | None
    space_complexity: ComplexityEstimate | None
    actual_confidence: float
    evidence: tuple[AlgorithmEvidence, ...]
    gap: GapResult
    expected: ResolvedExpectation
    issues: tuple[dict[str, Any], ...]
    programmatic_base_score: int
    algorithm_analysis: str
    data_structure_analysis: str
    recommended_approach: str


def _safe_str_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out or list(fallback)


def _normalize_complexity_gap(value: Any) -> str:
    gap = str(value or "").strip()
    if gap in _COMPLEXITY_GAP_VALUES:
        return gap
    return "unknown"


def _complexity_from_mapping(value: Any, *, default_source: str) -> ComplexityEstimate | None:
    if value is None:
        return None
    if isinstance(value, ComplexityEstimate):
        return value
    if isinstance(value, str) and value.strip():
        return normalize_complexity(value.strip(), source=default_source, confidence=1.0)
    if isinstance(value, dict):
        expression = str(value.get("expression") or "").strip()
        if not expression:
            return None
        source = str(value.get("source") or default_source).strip() or default_source
        try:
            confidence = float(value.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        evidence_lines = value.get("evidence_lines")
        lines: tuple[int, ...] = ()
        if isinstance(evidence_lines, (list, tuple)):
            parsed: list[int] = []
            for item in evidence_lines:
                try:
                    parsed.append(int(item))
                except (TypeError, ValueError):
                    continue
            lines = tuple(parsed)
        return normalize_complexity(
            expression,
            source=source,  # type: ignore[arg-type]
            confidence=confidence,
            evidence_lines=lines,
        )
    return None


def _expected_complexity_from_brief(brief: str) -> ComplexityEstimate | None:
    lowered = (brief or "").lower()
    patterns = [
        (r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*n\s*\^\s*2\s*\)|o\(n2\)|quadratic|karesel)", "O(n^2)"),
        (r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*n\s*log\s*n\s*\)|n\s*log\s*n)", "O(n log n)"),
        (r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*log\s*n\s*\)|logaritmik)", "O(log n)"),
        (r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*n\s*\)|tek gecis|tek geçiş|linear|lineer)", "O(n)"),
        (r"(beklenen|expected|hedef|target|istenen|istenilen)[^.\n;]*(o\s*\(\s*1\s*\)|sabit zaman|constant)", "O(1)"),
        (r"o\s*\(\s*n\s*\^\s*2\s*\)|o\(n2\)|quadratic|karesel", "O(n^2)"),
        (r"o\s*\(\s*n\s*log\s*n\s*\)|n\s*log\s*n", "O(n log n)"),
        (r"o\s*\(\s*log\s*n\s*\)|logaritmik", "O(log n)"),
        (r"o\s*\(\s*n\s*\)|tek gecis|tek geçiş|linear|lineer", "O(n)"),
        (r"o\s*\(\s*1\s*\)|sabit zaman|constant", "O(1)"),
    ]
    for pattern, expression in patterns:
        if re.search(pattern, lowered):
            return normalize_complexity(
                expression,
                source="deterministic_fallback",
                confidence=0.8,
            )
    return None


def _families_from_brief(brief: str) -> tuple[str, ...]:
    lowered = (brief or "").lower()
    if "binary search" in lowered or "ikili arama" in lowered:
        return ("binary_search",)
    if "hash" in lowered or "dict" in lowered or "set" in lowered:
        return ("hash_lookup",)
    if "stack" in lowered:
        return ("stack",)
    return ()


def resolve_expectation_input(
    algorithm_expectation: Any,
    *,
    brief: str = "",
) -> ResolvedExpectation:
    if algorithm_expectation is None:
        fallback = _expected_complexity_from_brief(brief)
        if fallback is None:
            return ResolvedExpectation()
        return ResolvedExpectation(
            expected_complexity=fallback,
            expected_families=_families_from_brief(brief),
            expected_source="deterministic_fallback",
            expected_confidence=fallback.confidence,
        )

    payload = algorithm_expectation
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    elif not isinstance(payload, dict) and hasattr(payload, "__dict__"):
        payload = vars(payload)

    if not isinstance(payload, dict):
        return ResolvedExpectation()

    expected = _complexity_from_mapping(
        payload.get("expected_complexity"),
        default_source="verified_expectation",
    )
    families_raw = payload.get("algorithm_families") or ()
    families = tuple(str(item).strip() for item in families_raw if str(item).strip())
    approach = str(payload.get("expected_approach") or "").strip()
    version = payload.get("version")
    try:
        expectation_version = int(version) if version is not None else None
    except (TypeError, ValueError):
        expectation_version = None

    if expected is None:
        return ResolvedExpectation(expectation_version=expectation_version)

    source = str(expected.source or "verified_expectation")
    if payload.get("verification_status") == "verified":
        source = "verified_expectation"
    return ResolvedExpectation(
        expected_complexity=expected,
        expected_approach=approach,
        expected_families=families,
        expected_source=source,
        expected_confidence=expected.confidence,
        expectation_version=expectation_version,
    )


def _unknown_complexity(source: str, confidence: float) -> ComplexityEstimate:
    return ComplexityEstimate(
        expression="unknown",
        family="unknown",
        rank=None,
        confidence=confidence,
        source=source,  # type: ignore[arg-type]
    )


def _space_complexity_for_detection(detection: AlgorithmDetection) -> ComplexityEstimate:
    if detection.data_structures:
        return normalize_complexity("O(n)", source="python_ast", confidence=0.8)
    return normalize_complexity("O(1)", source="python_ast", confidence=0.8)


def _loop_lower_bound_complexity(
    facts: Any,
) -> ComplexityEstimate:
    """Derive a conservative time lower-bound only when input dependence is proven."""
    loops = tuple(getattr(facts, "loops", ()) or ())
    if not loops:
        return ComplexityEstimate(
            expression="unknown",
            family="unknown",
            rank=None,
            confidence=0.3,
            source="python_ast",
            evidence_lines=(),
        )

    kinds = tuple(getattr(row, "iteration_kind", "unknown") for row in loops)
    # Any unclassified loop (e.g. while) means we cannot prove input complexity.
    if any(kind == "unknown" for kind in kinds):
        return ComplexityEstimate(
            expression="unknown",
            family="unknown",
            rank=None,
            confidence=0.3,
            source="python_ast",
            evidence_lines=(),
        )

    input_loops = tuple(row for row, kind in zip(loops, kinds) if kind == "input_dependent")
    if not input_loops:
        # Proven constant bounds only (e.g. range(10)).
        return normalize_complexity(
            "O(1)",
            source="python_ast",
            confidence=0.7,
            evidence_lines=tuple(int(row.line) for row in loops if getattr(row, "line", 0)),
        )

    # Mixed constant + input-dependent nesting is ambiguous for depth ranking.
    if any(kind == "constant" for kind in kinds):
        return ComplexityEstimate(
            expression="unknown",
            family="unknown",
            rank=None,
            confidence=0.3,
            source="python_ast",
            evidence_lines=(),
        )

    depth = max(int(getattr(row, "depth", 0) or 0) for row in input_loops)
    loop_lines = tuple(int(row.line) for row in input_loops if getattr(row, "line", 0))
    if depth >= 3:
        expression = "O(n^3)"
    elif depth == 2:
        expression = "O(n^2)"
    elif depth == 1:
        expression = "O(n)"
    else:
        return ComplexityEstimate(
            expression="unknown",
            family="unknown",
            rank=None,
            confidence=0.3,
            source="python_ast",
            evidence_lines=(),
        )
    return normalize_complexity(
        expression,
        source="python_ast",
        confidence=0.6,
        evidence_lines=loop_lines,
    )


def _build_issues(
    *,
    gap: GapResult,
    evidence: tuple[AlgorithmEvidence, ...],
    expected: ResolvedExpectation,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    nested = next((item for item in evidence if item.kind == "nested_loop"), None)
    if gap.status == "worse_than_expected" and expected.expected_complexity is not None:
        gap_issue: dict[str, Any] = {
            "type": "complexity_gap",
            "description": gap.explanation[:300],
            "severity": "high",
            "suggested_fix": "Algoritmayi beklenen karmasiklik sinirina indirin.",
        }
        if nested is not None:
            gap_issue["line"] = nested.line
        issues.append(gap_issue)
    elif gap.approach_mismatch:
        issues.append(
            {
                "type": "approach_mismatch",
                "description": gap.explanation[:300],
                "severity": "medium",
                "suggested_fix": "Odevde istenen algoritma ailesini kullanin.",
            }
        )

    if nested is not None:
        issues.append(
            {
                "type": "nested_loop",
                "description": "Ic ice dongu karmasikligi artiriyor.",
                "severity": "medium",
                "suggested_fix": "Lookup veya indeksleme icin uygun veri yapisi kullanin.",
                "line": nested.line,
            }
        )
    return issues


def _analysis_text(detection: AlgorithmDetection, time_expression: str) -> str:
    names = ", ".join(detection.names) if detection.names else "general_iteration"
    return (
        f"Tespit edilen yaklasim: {names}. "
        f"Programatik karmasiklik tahmini {time_expression}."
    )


def _data_structure_text(data_structures: tuple[str, ...]) -> str:
    if data_structures:
        return f"Kullanilan veri yapilari: {', '.join(data_structures)}."
    return "Belirgin ek veri yapisi kullanimi tespit edilmedi."


def build_evidence_algorithm_result(
    source: str,
    language: str,
    *,
    algorithm_expectation: Any = None,
    brief: str = "",
) -> EvidenceAlgorithmResult:
    expected = resolve_expectation_input(algorithm_expectation, brief=brief)
    lang = str(language or "python").strip().lower()

    if lang not in {"python", "py"}:
        unknown = _unknown_complexity("unknown", _LOW_CONFIDENCE_CPP_JAVA)
        gap = GapResult(
            status="unknown",
            steps=None,
            approach_mismatch=False,
            explanation="C++/Java submissions use low-confidence algorithm analysis without gap penalty.",
        )
        return EvidenceAlgorithmResult(
            detected_algorithms=(),
            data_structures=(),
            time_complexity=unknown,
            space_complexity=unknown,
            actual_confidence=_LOW_CONFIDENCE_CPP_JAVA,
            evidence=(),
            gap=gap,
            expected=expected,
            issues=(),
            programmatic_base_score=_PROGRAMMATIC_BASE_SCORE,
            algorithm_analysis="C++/Java icin dusuk guvenilirlikte algoritma analizi.",
            data_structure_analysis="AST tabanli ayrintili veri yapisi tespiti Python ile sinirlidir.",
            recommended_approach=expected.expected_approach,
        )

    facts = extract_python_facts(source)
    detection = detect_algorithms(facts, source)
    actual_time = detection.time_complexity
    if actual_time is None:
        actual_time = _loop_lower_bound_complexity(facts)
    actual_space = _space_complexity_for_detection(detection)

    if (
        expected.expected_complexity is None
        or actual_time.family == "unknown"
        or actual_time.rank is None
    ):
        gap = GapResult(
            status="unknown",
            steps=None,
            approach_mismatch=False,
            explanation=(
                "Expected complexity is unknown; gap comparison skipped."
                if expected.expected_complexity is None
                else "Actual complexity lacks a reliable ranked estimate; gap comparison skipped."
            ),
        )
    else:
        gap = compare_expected_actual(
            actual_time,
            expected.expected_complexity,
            actual_approaches=detection.names,
            expected_approaches=expected.expected_families,
        )

    evidence = detection.evidence
    issues = tuple(_build_issues(gap=gap, evidence=evidence, expected=expected))
    time_expression = actual_time.expression
    actual_confidence = (
        detection.confidence if detection.names else float(actual_time.confidence)
    )
    return EvidenceAlgorithmResult(
        detected_algorithms=detection.names,
        data_structures=detection.data_structures,
        time_complexity=actual_time,
        space_complexity=actual_space,
        actual_confidence=actual_confidence,
        evidence=evidence,
        gap=gap,
        expected=expected,
        issues=issues,
        programmatic_base_score=_PROGRAMMATIC_BASE_SCORE,
        algorithm_analysis=_analysis_text(detection, time_expression),
        data_structure_analysis=_data_structure_text(detection.data_structures),
        recommended_approach=expected.expected_approach,
    )


def _normalize_algorithm_issues(issues: Any) -> list[dict[str, Any]]:
    if not isinstance(issues, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw in issues:
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description") or raw.get("message") or "").strip()
        suggested_fix = str(raw.get("suggested_fix") or raw.get("suggestion") or "").strip()
        if not description:
            continue
        issue = {
            "type": str(raw.get("type") or "algorithm_observation").strip() or "algorithm_observation",
            "description": description[:300],
            "severity": normalize_agent_severity(raw.get("severity")),
            "suggested_fix": suggested_fix[:300]
            or "Algoritma secimini ve karmasiklik hedefini odev beklentisine gore iyilestirin.",
        }
        line = raw.get("line")
        if isinstance(line, int) and line > 0:
            issue["line"] = line
        line_hint = raw.get("line_hint")
        if "line" not in issue and isinstance(line_hint, int) and line_hint > 0:
            issue["line"] = line_hint
        normalized.append(issue)
        if len(normalized) >= 8:
            break
    return normalized


def _dedupe_algorithm_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    for issue in issues:
        issue_type = str(issue.get("type") or "algorithm_observation").strip()
        line = issue.get("line")
        if issue_type in {"complexity_gap", "nested_loop", "approach_mismatch"}:
            key = (issue_type, line if isinstance(line, int) else None)
        else:
            description = str(issue.get("description") or "").strip().lower()
            key = (issue_type, description[:120])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _allowed_evidence_lines(evidence: tuple[AlgorithmEvidence, ...]) -> set[int]:
    return {item.line for item in evidence if isinstance(item.line, int) and item.line > 0}


def _filter_llm_issues(
    issues: list[dict[str, Any]],
    *,
    allowed_lines: set[int],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for issue in issues:
        line = issue.get("line")
        if isinstance(line, int) and line > 0 and allowed_lines and line not in allowed_lines:
            continue
        filtered.append(issue)
    return filtered


def _evidence_payload(evidence: tuple[AlgorithmEvidence, ...]) -> list[dict[str, Any]]:
    return [
        {
            "kind": item.kind,
            "line": item.line,
            "detail": item.detail,
            "confidence": item.confidence,
        }
        for item in evidence
    ]


def _coerce_llm_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = 50
    return max(0, min(100, score))


def evidence_result_to_output(evidence: EvidenceAlgorithmResult) -> dict[str, Any]:
    expected_expression = (
        evidence.expected.expected_complexity.expression
        if evidence.expected.expected_complexity is not None
        else ""
    )
    return {
        "detected_algorithms": list(evidence.detected_algorithms) or ["general_iteration"],
        "data_structures": list(evidence.data_structures),
        "time_complexity": evidence.time_complexity.expression if evidence.time_complexity else "unknown",
        "space_complexity": evidence.space_complexity.expression if evidence.space_complexity else "O(1)",
        "expected_complexity": expected_expression,
        "complexity_gap": evidence.gap.status,
        "algorithm_analysis": evidence.algorithm_analysis,
        "data_structure_analysis": evidence.data_structure_analysis,
        "issues": [dict(item) for item in evidence.issues],
        "score": evidence.programmatic_base_score,
        "programmatic_base_score": evidence.programmatic_base_score,
        "actual_family": evidence.time_complexity.family if evidence.time_complexity else "unknown",
        "actual_confidence": evidence.actual_confidence,
        "expected_approach": evidence.expected.expected_approach,
        "expected_families": list(evidence.expected.expected_families),
        "expected_source": evidence.expected.expected_source,
        "expected_confidence": evidence.expected.expected_confidence,
        "expectation_version": evidence.expected.expectation_version,
        "gap_steps": evidence.gap.steps,
        "gap_explanation": evidence.gap.explanation,
        "recommended_approach": evidence.recommended_approach,
        "evidence": _evidence_payload(evidence.evidence),
    }


def build_programmatic_algorithm_result(
    source: str,
    language: str,
    brief: str,
    *,
    algorithm_expectation: Any = None,
) -> dict[str, Any]:
    evidence = build_evidence_algorithm_result(
        source,
        language,
        algorithm_expectation=algorithm_expectation,
        brief=brief,
    )
    output = evidence_result_to_output(evidence)
    decision = apply_algorithm_score_guardrail(
        evidence.programmatic_base_score,
        evidence.programmatic_base_score,
        evidence.gap,
        evidence.evidence,
    )
    output["score"] = decision.score
    output["guardrail_flags"] = list(decision.guardrail_flags)
    source_lines = source.splitlines()
    if source_lines:
        output["issues"] = [
            enrich_issue_with_line(dict(issue), source_lines)
            for issue in output.get("issues", [])
            if isinstance(issue, dict)
        ]
    return output


def _merge_recommended_approach(
    *,
    evidence: EvidenceAlgorithmResult,
    programmatic: dict[str, Any],
    llm_result: dict[str, Any],
    expected_expression: str,
) -> str:
    """Prefer verified expectation; never let LLM override when expectation is present."""
    from_evidence = str(evidence.recommended_approach or "").strip()
    if from_evidence:
        return from_evidence
    from_programmatic = str(programmatic.get("recommended_approach") or "").strip()
    if from_programmatic:
        return from_programmatic
    has_verified_expectation = evidence.expected.expected_complexity is not None
    if has_verified_expectation:
        expression = expected_expression.strip() or "unknown"
        return f"Beklenen yaklasim: {expression} karmasiklikli bir cozum."
    return str(llm_result.get("recommended_approach") or "").strip()


def merge_algorithm_results(
    programmatic: dict[str, Any],
    llm_result: dict[str, Any],
    *,
    source: str = "",
    evidence: EvidenceAlgorithmResult,
) -> dict[str, Any]:
    actual_time = evidence.time_complexity
    actual_expression = actual_time.expression if actual_time else str(programmatic.get("time_complexity") or "O(1)")
    expected_expression = (
        evidence.expected.expected_complexity.expression
        if evidence.expected.expected_complexity is not None
        else str(programmatic.get("expected_complexity") or "")
    )

    llm_issues = _filter_llm_issues(
        _normalize_algorithm_issues(llm_result.get("issues")),
        allowed_lines=_allowed_evidence_lines(evidence.evidence),
    )
    programmatic_issues = _normalize_algorithm_issues(programmatic.get("issues"))

    llm_score = _coerce_llm_score(llm_result.get("score"))
    base_score = int(programmatic.get("programmatic_base_score") or evidence.programmatic_base_score)
    decision = apply_algorithm_score_guardrail(
        base_score,
        llm_score,
        evidence.gap,
        evidence.evidence,
    )

    merged = dict(programmatic)
    merged.update(
        {
            "detected_algorithms": list(evidence.detected_algorithms) or ["general_iteration"],
            "data_structures": list(evidence.data_structures),
            "time_complexity": actual_expression,
            "space_complexity": evidence.space_complexity.expression if evidence.space_complexity else "O(1)",
            "expected_complexity": expected_expression,
            "complexity_gap": evidence.gap.status,
            "gap_steps": evidence.gap.steps,
            "gap_explanation": evidence.gap.explanation,
            "algorithm_analysis": str(
                llm_result.get("algorithm_analysis") or programmatic.get("algorithm_analysis") or ""
            ).strip(),
            "data_structure_analysis": str(
                llm_result.get("data_structure_analysis") or programmatic.get("data_structure_analysis") or ""
            ).strip(),
            "recommended_approach": _merge_recommended_approach(
                evidence=evidence,
                programmatic=programmatic,
                llm_result=llm_result,
                expected_expression=expected_expression,
            ),
            "issues": _dedupe_algorithm_issues(programmatic_issues + llm_issues)[:10],
            "score": decision.score,
            "programmatic_base_score": base_score,
            "actual_family": actual_time.family if actual_time else "unknown",
            "actual_confidence": evidence.actual_confidence,
            "expected_approach": evidence.expected.expected_approach,
            "expected_families": list(evidence.expected.expected_families),
            "expected_source": evidence.expected.expected_source,
            "expected_confidence": evidence.expected.expected_confidence,
            "expectation_version": evidence.expected.expectation_version,
            "evidence": _evidence_payload(evidence.evidence),
        }
    )

    flags = list(programmatic.get("guardrail_flags") or [])
    for flag in decision.guardrail_flags:
        if flag not in flags:
            flags.append(flag)
    merged["guardrail_flags"] = flags

    source_lines = source.splitlines()
    if source_lines:
        merged["issues"] = [
            enrich_issue_with_line(dict(issue), source_lines)
            for issue in merged.get("issues", [])
            if isinstance(issue, dict)
        ]
    return merged
