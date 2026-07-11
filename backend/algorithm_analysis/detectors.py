from __future__ import annotations

import re
from dataclasses import dataclass

from backend.algorithm_analysis.ast_facts import PythonAstFacts
from backend.algorithm_analysis.complexity import normalize_complexity
from backend.algorithm_analysis.contracts import (
    AlgorithmDetection,
    AlgorithmEvidence,
    ComplexityEstimate,
    ComplexityFamily,
)

_HIGH_CONFIDENCE = 0.85
_MIN_DETECTION_CONFIDENCE = 0.75


@dataclass(frozen=True)
class _FamilyMatch:
    name: str
    confidence: float
    evidence: tuple[AlgorithmEvidence, ...]
    time_expression: str | None = None
    time_family: ComplexityFamily = "single_variable"


def _family_evidence(kind: str, line: int, detail: str) -> AlgorithmEvidence:
    return AlgorithmEvidence(
        kind=kind,
        line=line,
        detail=detail,
        confidence=_HIGH_CONFIDENCE,
    )


def _first_fact_evidence(
    facts: PythonAstFacts,
    kind: str,
    *,
    detail_contains: str | None = None,
) -> AlgorithmEvidence | None:
    for entry in facts.evidence:
        if entry.kind != kind:
            continue
        if detail_contains is not None and detail_contains not in entry.detail:
            continue
        return entry
    return None


def _all_fact_evidence(facts: PythonAstFacts, kind: str) -> tuple[AlgorithmEvidence, ...]:
    return tuple(entry for entry in facts.evidence if entry.kind == kind)


def _source_has_pop_zero(source: str) -> bool:
    return re.search(r"\.pop\s*\(\s*0\s*\)", source) is not None


def _membership_lookup_line(source: str) -> int | None:
    for index, line in enumerate(source.splitlines(), start=1):
        if re.search(r"\bin\s+[A-Za-z_]\w*\b", line):
            return index
    return None


def _direct_recursion_count(facts: PythonAstFacts, function: str) -> int:
    return sum(
        1
        for signal in facts.recursion_signals
        if signal.kind == "direct" and function in signal.functions
    )


def _detect_brute_force_nested_scan(facts: PythonAstFacts) -> _FamilyMatch | None:
    if facts.max_loop_depth < 2:
        return None
    if _first_fact_evidence(facts, "adjacency_traversal") is not None:
        return None
    nested = _first_fact_evidence(facts, "nested_loop")
    line = nested.line if nested is not None else facts.loops[0].line
    return _FamilyMatch(
        name="brute_force_nested_scan",
        confidence=_HIGH_CONFIDENCE,
        evidence=(
            nested
            or _family_evidence(
                "brute_force_nested_scan",
                line,
                f"nested loop depth {facts.max_loop_depth}",
            ),
        ),
        time_expression="O(n^2)",
    )


def _detect_hash_lookup(facts: PythonAstFacts, source: str) -> _FamilyMatch | None:
    if "dict" not in facts.data_structures and "set" not in facts.data_structures:
        return None
    lookup_lines = [row.line for row in facts.subscripts]
    membership_line = _membership_lookup_line(source)
    if membership_line is not None:
        lookup_lines.append(membership_line)
    if not lookup_lines:
        return None
    line = min(lookup_lines)
    structure = "dict" if "dict" in facts.data_structures else "set"
    return _FamilyMatch(
        name="hash_lookup",
        confidence=_HIGH_CONFIDENCE,
        evidence=(
            _family_evidence(
                "hash_lookup",
                line,
                f"{structure} membership or subscript lookup",
            ),
        ),
        time_expression="O(n)",
    )


def _detect_sorting(facts: PythonAstFacts) -> _FamilyMatch | None:
    sort_entries = _all_fact_evidence(facts, "sort_call")
    if not sort_entries:
        return None
    return _FamilyMatch(
        name="sorting",
        confidence=_HIGH_CONFIDENCE,
        evidence=sort_entries,
        time_expression="O(n log n)",
    )


def _detect_binary_search(facts: PythonAstFacts) -> _FamilyMatch | None:
    bound = _first_fact_evidence(facts, "binary_search_bound")
    if bound is None:
        return None
    return _FamilyMatch(
        name="binary_search",
        confidence=_HIGH_CONFIDENCE,
        evidence=(bound,),
        time_expression="O(log n)",
    )


def _detect_stack(facts: PythonAstFacts, source: str) -> _FamilyMatch | None:
    if "append" not in facts.call_names or "pop" not in facts.call_names:
        return None
    if _source_has_pop_zero(source):
        return None
    if facts.recursion_signals:
        return None
    pop_line = next(
        (entry.line for entry in facts.evidence if entry.kind == "rollback_mutation"),
        None,
    )
    if pop_line is None:
        pop_line = 1
    return _FamilyMatch(
        name="stack",
        confidence=_HIGH_CONFIDENCE,
        evidence=(
            _family_evidence("stack", pop_line, "append/pop LIFO stack pattern"),
        ),
        time_expression="O(n)",
    )


def _detect_queue(facts: PythonAstFacts, source: str) -> _FamilyMatch | None:
    if "append" not in facts.call_names or "pop" not in facts.call_names:
        return None
    if not _source_has_pop_zero(source):
        return None
    line = next(
        (
            index
            for index, row in enumerate(source.splitlines(), start=1)
            if re.search(r"\.pop\s*\(\s*0\s*\)", row)
        ),
        1,
    )
    return _FamilyMatch(
        name="queue",
        confidence=_HIGH_CONFIDENCE,
        evidence=(_family_evidence("queue", line, "append/pop(0) FIFO queue pattern"),),
        time_expression="O(n^2)",
    )


def _detect_deque(facts: PythonAstFacts) -> _FamilyMatch | None:
    if "deque" not in facts.data_structures:
        return None
    entry = _first_fact_evidence(facts, "data_structure", detail_contains="deque")
    line = entry.line if entry is not None else 1
    return _FamilyMatch(
        name="deque",
        confidence=_HIGH_CONFIDENCE,
        evidence=(
            entry
            or _family_evidence("deque", line, "collections.deque usage"),
        ),
        time_expression="O(n)",
    )


def _detect_heap(facts: PythonAstFacts) -> _FamilyMatch | None:
    if "heapq" not in facts.data_structures:
        return None
    entry = _first_fact_evidence(facts, "data_structure", detail_contains="heapq")
    line = entry.line if entry is not None else 1
    return _FamilyMatch(
        name="heap",
        confidence=_HIGH_CONFIDENCE,
        evidence=(
            entry or _family_evidence("heap", line, "heapq priority queue usage"),
        ),
        time_expression="O(n log n)",
    )


def _detect_recursion(facts: PythonAstFacts) -> _FamilyMatch | None:
    direct = _all_fact_evidence(facts, "direct_recursion")
    if not direct:
        return None
    branching_functions = {
        signal.functions[0]
        for signal in facts.recursion_signals
        if signal.kind == "direct" and _direct_recursion_count(facts, signal.functions[0]) >= 2
    }
    if branching_functions:
        direct = tuple(
            entry
            for entry in direct
            if not any(name in entry.detail for name in branching_functions)
        )
        if not direct:
            return None
    return _FamilyMatch(
        name="recursion",
        confidence=_HIGH_CONFIDENCE,
        evidence=direct,
        time_expression="O(n)",
    )


def _detect_branching_recursion(facts: PythonAstFacts) -> _FamilyMatch | None:
    branching: list[AlgorithmEvidence] = []
    seen: set[str] = set()
    for signal in facts.recursion_signals:
        if signal.kind != "direct":
            continue
        function = signal.functions[0]
        if function in seen:
            continue
        if _direct_recursion_count(facts, function) < 2:
            continue
        seen.add(function)
        entry = _first_fact_evidence(facts, "direct_recursion", detail_contains=function)
        branching.append(
            entry
            or _family_evidence(
                "branching_recursion",
                signal.line,
                f"{function} makes multiple recursive calls",
            )
        )
    if not branching:
        return None
    return _FamilyMatch(
        name="branching_recursion",
        confidence=_HIGH_CONFIDENCE,
        evidence=tuple(branching),
        time_expression="O(2^n)",
    )


def _detect_backtracking(facts: PythonAstFacts) -> _FamilyMatch | None:
    rollback = _first_fact_evidence(facts, "rollback_mutation")
    recursion = _first_fact_evidence(facts, "direct_recursion")
    if rollback is None or recursion is None:
        return None
    return _FamilyMatch(
        name="backtracking",
        confidence=_HIGH_CONFIDENCE,
        evidence=(rollback, recursion),
        time_expression="O(2^n)",
    )


def _detect_bfs(facts: PythonAstFacts) -> _FamilyMatch | None:
    if "popleft" not in facts.call_names:
        return None
    if "deque" not in facts.data_structures:
        return None
    adjacency = _first_fact_evidence(facts, "adjacency_traversal")
    popleft_line = next(
        (index for index, name in enumerate(facts.call_names, start=1) if name == "popleft"),
        1,
    )
    for entry in facts.evidence:
        if entry.kind == "data_structure" and "deque" in entry.detail:
            popleft_line = entry.line
            break
    evidence = [
        _family_evidence("bfs", popleft_line, "deque popleft breadth-first traversal"),
    ]
    if adjacency is not None:
        evidence.append(adjacency)
    return _FamilyMatch(
        name="bfs",
        confidence=_HIGH_CONFIDENCE,
        evidence=tuple(evidence),
        time_expression="O(V+E)",
        time_family="graph",
    )


def _detect_dfs(facts: PythonAstFacts) -> _FamilyMatch | None:
    if "popleft" in facts.call_names and "deque" in facts.data_structures:
        return None
    adjacency = _first_fact_evidence(facts, "adjacency_traversal")
    recursion = _first_fact_evidence(facts, "direct_recursion")
    if adjacency is None or recursion is None:
        return None
    return _FamilyMatch(
        name="dfs",
        confidence=_HIGH_CONFIDENCE,
        evidence=(adjacency, recursion),
        time_expression="O(V+E)",
        time_family="graph",
    )


def _detect_greedy(facts: PythonAstFacts) -> _FamilyMatch | None:
    sort_entry = _first_fact_evidence(facts, "sort_call")
    if sort_entry is None:
        return None
    if facts.max_loop_depth < 1:
        return None
    if facts.max_loop_depth >= 2:
        return None
    loop_line = facts.loops[0].line if facts.loops else sort_entry.line
    return _FamilyMatch(
        name="greedy",
        confidence=_HIGH_CONFIDENCE,
        evidence=(
            sort_entry,
            _family_evidence("greedy", loop_line, "sort then single-pass selection"),
        ),
        time_expression="O(n log n)",
    )


def _detect_dynamic_programming(facts: PythonAstFacts) -> _FamilyMatch | None:
    memo = _first_fact_evidence(facts, "dp_memo")
    table = _first_fact_evidence(facts, "dp_table")
    entry = memo or table
    if entry is None:
        return None
    return _FamilyMatch(
        name="dynamic_programming",
        confidence=_HIGH_CONFIDENCE,
        evidence=(entry,),
        time_expression="O(n)",
    )


def _aggregate_time_complexity(
    matches: tuple[_FamilyMatch, ...],
    evidence_lines: tuple[int, ...],
) -> ComplexityEstimate | None:
    estimates: list[ComplexityEstimate] = []
    for match in matches:
        if match.time_expression is None:
            continue
        estimates.append(
            normalize_complexity(
                match.time_expression,
                source="python_ast",
                confidence=match.confidence,
                evidence_lines=evidence_lines,
            )
        )
    if not estimates:
        return None

    names = {match.name for match in matches}
    if "bfs" in names or "dfs" in names:
        graph_estimates = [item for item in estimates if item.family == "graph"]
        if graph_estimates:
            return max(graph_estimates, key=lambda item: item.rank or 0)

    by_family: dict[ComplexityFamily, ComplexityEstimate] = {}
    for estimate in estimates:
        current = by_family.get(estimate.family)
        if current is None:
            by_family[estimate.family] = estimate
            continue
        if estimate.rank is not None and current.rank is not None and estimate.rank > current.rank:
            by_family[estimate.family] = estimate

    if len(by_family) == 1:
        return next(iter(by_family.values()))

    ranked = [item for item in by_family.values() if item.rank is not None]
    if not ranked:
        return estimates[0]
    return max(ranked, key=lambda item: item.rank or 0)


def detect_algorithms(facts: PythonAstFacts, source: str) -> AlgorithmDetection:
    if facts.syntax_error is not None:
        return AlgorithmDetection()

    detectors = (
        _detect_brute_force_nested_scan(facts),
        _detect_hash_lookup(facts, source),
        _detect_sorting(facts),
        _detect_binary_search(facts),
        _detect_stack(facts, source),
        _detect_queue(facts, source),
        _detect_deque(facts),
        _detect_heap(facts),
        _detect_branching_recursion(facts),
        _detect_recursion(facts),
        _detect_backtracking(facts),
        _detect_bfs(facts),
        _detect_dfs(facts),
        _detect_greedy(facts),
        _detect_dynamic_programming(facts),
    )
    matches = tuple(match for match in detectors if match is not None)
    if not matches:
        return AlgorithmDetection()

    evidence: list[AlgorithmEvidence] = []
    seen_evidence: set[tuple[str, int, str]] = set()
    for match in matches:
        for entry in match.evidence:
            key = (entry.kind, entry.line, entry.detail)
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            evidence.append(entry)

    evidence_lines = tuple(sorted({entry.line for entry in evidence if entry.line >= 1}))
    time_complexity = _aggregate_time_complexity(matches, evidence_lines)
    confidence = max(match.confidence for match in matches)

    if confidence < _MIN_DETECTION_CONFIDENCE:
        return AlgorithmDetection()

    return AlgorithmDetection(
        names=tuple(sorted({match.name for match in matches})),
        data_structures=facts.data_structures,
        evidence=tuple(evidence),
        time_complexity=time_complexity,
        confidence=confidence,
    )
