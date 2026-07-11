"""RED-phase tests for the Python AST fact engine (Gate 3.1 / Task 2).

Expected contract for GREEN implementer (`backend/algorithm_analysis/ast_facts.py`):

- `extract_python_facts(source: str) -> PythonAstFacts`
- Models use `StrictFrozenModel` style from `backend.algorithm_analysis.contracts`
  (`extra="forbid"`, `frozen=True`, tuple fields).

`PythonAstFacts` fields:
- `loops: tuple[LoopFact, ...]` — each `LoopFact` has `line: int`, `depth: int`
- `max_loop_depth: int`
- `recursion_signals: tuple[RecursionSignal, ...]` — `kind` is `"direct"` or `"mutual"`,
  plus `line: int` and `functions: tuple[str, ...]`
- `call_names: tuple[str, ...]` — bare function/method names seen in calls
- `assignments: tuple[AssignmentFact, ...]` — `line: int`, `target: str`
- `subscripts: tuple[SubscriptFact, ...]` — `line: int`, `base: str`
- `data_structures: tuple[str, ...]` — e.g. `"dict"`, `"set"`, `"deque"`, `"heapq"`
- `evidence: tuple[AlgorithmEvidence, ...]` — reuse `AlgorithmEvidence` from contracts
- `syntax_error: str | None` — set on parse failure; all fact tuples empty, depth 0
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.algorithm_analysis.ast_facts import (
    AssignmentFact,
    LoopFact,
    PythonAstFacts,
    RecursionSignal,
    SubscriptFact,
    extract_python_facts,
)
from backend.algorithm_analysis.contracts import AlgorithmEvidence, StrictFrozenModel


def test_nested_loops_record_exact_outer_and_inner_lines() -> None:
    source = "for i in xs:\n    for j in ys:\n        print(i, j)\n"
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert facts.max_loop_depth == 2
    assert tuple(row.line for row in facts.loops) == (1, 2)
    assert tuple(row.depth for row in facts.loops) == (1, 2)
    assert any(
        entry.kind == "nested_loop" and entry.line in {1, 2}
        for entry in facts.evidence
    )


def test_triple_nested_loop_updates_max_depth() -> None:
    source = (
        "for a in xs:\n"
        "    for b in ys:\n"
        "        for c in zs:\n"
        "            pass\n"
    )
    facts = extract_python_facts(source)

    assert facts.max_loop_depth == 3
    assert tuple(row.line for row in facts.loops) == (1, 2, 3)
    assert tuple(row.depth for row in facts.loops) == (1, 2, 3)


def test_direct_recursion_signal() -> None:
    source = (
        "def factorial(n):\n"
        "    if n <= 1:\n"
        "        return 1\n"
        "    return n * factorial(n - 1)\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert any(signal.kind == "direct" for signal in facts.recursion_signals)
    direct = next(s for s in facts.recursion_signals if s.kind == "direct")
    assert direct.functions == ("factorial",)
    assert direct.line == 4
    assert "factorial" in facts.call_names
    assert any(entry.kind == "direct_recursion" for entry in facts.evidence)


def test_mutual_recursion_signal() -> None:
    source = (
        "def is_even(n):\n"
        "    if n == 0:\n"
        "        return True\n"
        "    return is_odd(n - 1)\n"
        "\n"
        "def is_odd(n):\n"
        "    if n == 0:\n"
        "        return False\n"
        "    return is_even(n - 1)\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert any(signal.kind == "mutual" for signal in facts.recursion_signals)
    mutual = next(s for s in facts.recursion_signals if s.kind == "mutual")
    assert set(mutual.functions) == {"is_even", "is_odd"}
    assert mutual.line in {4, 9}
    assert "is_even" in facts.call_names
    assert "is_odd" in facts.call_names
    assert any(entry.kind == "mutual_recursion" for entry in facts.evidence)


def test_dict_set_deque_and_heapq_data_structures() -> None:
    source = (
        "from collections import deque\n"
        "import heapq\n"
        "\n"
        "def build():\n"
        "    mapping = {}\n"
        "    seen = set()\n"
        "    queue = deque()\n"
        "    heapq.heappush(queue, 1)\n"
        "    return mapping, seen, queue\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert "dict" in facts.data_structures
    assert "set" in facts.data_structures
    assert "deque" in facts.data_structures
    assert "heapq" in facts.data_structures
    assert "heappush" in facts.call_names
    assert any(entry.kind == "data_structure" for entry in facts.evidence)


def test_sort_calls_are_recorded() -> None:
    source = (
        "def sort_items(items):\n"
        "    ordered = sorted(items)\n"
        "    items.sort()\n"
        "    return ordered\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert "sorted" in facts.call_names
    assert "sort" in facts.call_names
    assert any(entry.kind == "sort_call" for entry in facts.evidence)


def test_binary_search_bound_updates_are_detected() -> None:
    source = (
        "def search(arr, target):\n"
        "    lo, hi = 0, len(arr)\n"
        "    while lo < hi:\n"
        "        mid = (lo + hi) // 2\n"
        "        if arr[mid] < target:\n"
        "            lo = mid + 1\n"
        "        else:\n"
        "            hi = mid\n"
        "    return lo\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    lo_targets = {row.target for row in facts.assignments if row.target in {"lo", "hi"}}
    assert lo_targets == {"lo", "hi"}
    assert any(entry.kind == "binary_search_bound" for entry in facts.evidence)


def test_adjacency_list_traversal_is_detected() -> None:
    source = (
        "def walk(adj, start):\n"
        "    for neighbor in adj[start]:\n"
        "        print(neighbor)\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert any(row.base == "adj" for row in facts.subscripts)
    assert any(entry.kind == "adjacency_traversal" for entry in facts.evidence)


def test_dp_memo_access_is_detected() -> None:
    source = (
        "def solve(n, memo):\n"
        "    if n in memo:\n"
        "        return memo[n]\n"
        "    memo[n] = n\n"
        "    return memo[n]\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert any(row.base == "memo" for row in facts.subscripts)
    assert any(entry.kind == "dp_memo" for entry in facts.evidence)


def test_dp_table_subscript_access_is_detected() -> None:
    source = (
        "def fill():\n"
        "    dp = [[0] * 3 for _ in range(3)]\n"
        "    dp[1][2] = 7\n"
        "    return dp[1][2]\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert any(row.base == "dp" for row in facts.subscripts)
    assert any(entry.kind == "dp_table" for entry in facts.evidence)


def test_rollback_mutation_pattern_is_detected() -> None:
    source = (
        "def backtrack(path, choices):\n"
        "    path.append(choices[0])\n"
        "    backtrack(path, choices[1:])\n"
        "    path.pop()\n"
    )
    facts = extract_python_facts(source)

    assert facts.syntax_error is None
    assert "append" in facts.call_names
    assert "pop" in facts.call_names
    assert any(entry.kind == "rollback_mutation" for entry in facts.evidence)


def test_syntax_error_returns_empty_facts_without_raising() -> None:
    source = "def broken(\n"
    facts = extract_python_facts(source)

    assert facts.syntax_error is not None
    assert facts.max_loop_depth == 0
    assert facts.loops == ()
    assert facts.recursion_signals == ()
    assert facts.call_names == ()
    assert facts.assignments == ()
    assert facts.subscripts == ()
    assert facts.data_structures == ()
    assert facts.evidence == ()


def test_python_ast_facts_is_strict_frozen_model() -> None:
    assert issubclass(PythonAstFacts, StrictFrozenModel)
    assert issubclass(LoopFact, StrictFrozenModel)
    assert issubclass(RecursionSignal, StrictFrozenModel)
    assert issubclass(AssignmentFact, StrictFrozenModel)
    assert issubclass(SubscriptFact, StrictFrozenModel)

    facts = PythonAstFacts()
    with pytest.raises(ValidationError):
        facts.max_loop_depth = 1
    with pytest.raises(ValidationError):
        PythonAstFacts(unexpected="x")


def test_loop_fact_is_frozen_and_rejects_extra_fields() -> None:
    loop = LoopFact(line=4, depth=2)
    with pytest.raises(ValidationError):
        loop.line = 5
    with pytest.raises(ValidationError):
        LoopFact(line=4, depth=2, unexpected="x")


def test_evidence_entries_use_algorithm_evidence_contract() -> None:
    source = "for i in range(3):\n    pass\n"
    facts = extract_python_facts(source)

    assert facts.evidence
    entry = facts.evidence[0]
    assert isinstance(entry, AlgorithmEvidence)
    assert entry.kind
    assert entry.line >= 1
    assert entry.detail
    assert 0.0 <= entry.confidence <= 1.0
