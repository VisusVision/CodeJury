"""RED-phase tests for algorithm-family detectors (Gate 3.1 / Task 3).

Expected contract for GREEN implementer (`backend/algorithm_analysis/detectors.py`):

- `detect_algorithms(facts: PythonAstFacts, source: str) -> AlgorithmDetection`
- Stable snake_case family names in `AlgorithmDetection.names`
- High-confidence detections include `AlgorithmEvidence` entries with line numbers
- Aggregate time/space complexity via `normalize_complexity` when applicable
"""

from __future__ import annotations

import pytest

from backend.algorithm_analysis.ast_facts import extract_python_facts
from backend.algorithm_analysis.contracts import AlgorithmDetection, AlgorithmEvidence
from backend.algorithm_analysis.detectors import detect_algorithms

REQUIRED_FAMILIES = (
    "brute_force_nested_scan",
    "hash_lookup",
    "sorting",
    "binary_search",
    "stack",
    "queue",
    "deque",
    "heap",
    "recursion",
    "branching_recursion",
    "backtracking",
    "bfs",
    "dfs",
    "greedy",
    "dynamic_programming",
)

_POSITIVE_EXAMPLES: tuple[tuple[str, str], ...] = (
    (
        "brute_force_nested_scan",
        (
            "def has_pair(xs, ys, target):\n"
            "    for x in xs:\n"
            "        for y in ys:\n"
            "            if x + y == target:\n"
            "                return True\n"
            "    return False\n"
        ),
    ),
    (
        "hash_lookup",
        (
            "def two_sum(nums, target):\n"
            "    seen = {}\n"
            "    for i, value in enumerate(nums):\n"
            "        need = target - value\n"
            "        if need in seen:\n"
            "            return [seen[need], i]\n"
            "        seen[value] = i\n"
            "    return []\n"
        ),
    ),
    (
        "sorting",
        (
            "def order_items(items):\n"
            "    ordered = sorted(items)\n"
            "    items.sort()\n"
            "    return ordered\n"
        ),
    ),
    (
        "binary_search",
        (
            "def search(arr, target):\n"
            "    lo, hi = 0, len(arr)\n"
            "    while lo < hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if arr[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid\n"
            "    return lo\n"
        ),
    ),
    (
        "stack",
        (
            "def reverse_chars(text):\n"
            "    stack = []\n"
            "    for ch in text:\n"
            "        stack.append(ch)\n"
            "    out = []\n"
            "    while stack:\n"
            "        out.append(stack.pop())\n"
            "    return ''.join(out)\n"
        ),
    ),
    (
        "queue",
        (
            "def drain(items):\n"
            "    queue = []\n"
            "    for item in items:\n"
            "        queue.append(item)\n"
            "    while queue:\n"
            "        queue.pop(0)\n"
        ),
    ),
    (
        "deque",
        (
            "from collections import deque\n"
            "\n"
            "def rotate_left(items, k):\n"
            "    window = deque(items)\n"
            "    window.rotate(-k)\n"
            "    return list(window)\n"
        ),
    ),
    (
        "heap",
        (
            "import heapq\n"
            "\n"
            "def top_k(values, k):\n"
            "    heap = []\n"
            "    for value in values:\n"
            "        heapq.heappush(heap, value)\n"
            "    return [heapq.heappop(heap) for _ in range(k)]\n"
        ),
    ),
    (
        "recursion",
        (
            "def factorial(n):\n"
            "    if n <= 1:\n"
            "        return 1\n"
            "    return n * factorial(n - 1)\n"
        ),
    ),
    (
        "branching_recursion",
        (
            "def fib(n):\n"
            "    if n <= 1:\n"
            "        return n\n"
            "    return fib(n - 1) + fib(n - 2)\n"
        ),
    ),
    (
        "backtracking",
        (
            "def choose(path, options):\n"
            "    if not options:\n"
            "        return path\n"
            "    path.append(options[0])\n"
            "    choose(path, options[1:])\n"
            "    path.pop()\n"
            "    return path\n"
        ),
    ),
    (
        "bfs",
        (
            "from collections import deque\n"
            "\n"
            "def bfs(adj, start):\n"
            "    q = deque([start])\n"
            "    seen = {start}\n"
            "    while q:\n"
            "        node = q.popleft()\n"
            "        for nbr in adj[node]:\n"
            "            if nbr not in seen:\n"
            "                seen.add(nbr)\n"
            "                q.append(nbr)\n"
        ),
    ),
    (
        "dfs",
        (
            "def dfs(adj, node, seen):\n"
            "    seen.add(node)\n"
            "    for nbr in adj[node]:\n"
            "        if nbr not in seen:\n"
            "            dfs(adj, nbr, seen)\n"
        ),
    ),
    (
        "greedy",
        (
            "def max_non_overlapping(intervals):\n"
            "    intervals.sort(key=lambda pair: pair[1])\n"
            "    count = 0\n"
            "    end = float('-inf')\n"
            "    for start, finish in intervals:\n"
            "        if start >= end:\n"
            "            count += 1\n"
            "            end = finish\n"
            "    return count\n"
        ),
    ),
    (
        "dynamic_programming",
        (
            "def coin_change(amount, coins, memo):\n"
            "    if amount in memo:\n"
            "        return memo[amount]\n"
            "    if amount == 0:\n"
            "        return 0\n"
            "    best = float('inf')\n"
            "    for coin in coins:\n"
            "        if coin <= amount:\n"
            "            best = min(best, 1 + coin_change(amount - coin, coins, memo))\n"
            "    memo[amount] = best\n"
            "    return memo[amount]\n"
        ),
    ),
)


def _detect(source: str) -> AlgorithmDetection:
    facts = extract_python_facts(source)
    assert facts.syntax_error is None, facts.syntax_error
    return detect_algorithms(facts, source)


def _assert_family_detected(
    source: str,
    family: str,
    *,
    min_confidence: float = 0.75,
) -> AlgorithmDetection:
    detection = _detect(source)
    assert family in detection.names, f"expected {family!r} in {detection.names!r}"
    assert detection.confidence >= min_confidence
    high_confidence = [
        entry for entry in detection.evidence if entry.confidence >= min_confidence
    ]
    assert high_confidence, "high-confidence detection must include evidence"
    assert all(entry.line >= 1 for entry in high_confidence)
    assert all(entry.detail for entry in high_confidence)
    return detection


@pytest.mark.parametrize(("family", "source"), _POSITIVE_EXAMPLES, ids=[row[0] for row in _POSITIVE_EXAMPLES])
def test_detect_algorithms_positive_family_examples(family: str, source: str) -> None:
    _assert_family_detected(source, family)


def test_required_detector_families_are_covered_by_positive_matrix() -> None:
    covered = {family for family, _ in _POSITIVE_EXAMPLES}
    assert covered == set(REQUIRED_FAMILIES)


def test_single_direct_recursion_is_not_branching_recursion() -> None:
    source = (
        "def factorial(n):\n"
        "    if n <= 1:\n"
        "        return 1\n"
        "    return n * factorial(n - 1)\n"
    )
    detection = _detect(source)

    assert "recursion" in detection.names
    assert "branching_recursion" not in detection.names


def test_comment_membership_with_dict_is_not_hash_lookup() -> None:
    source = (
        "def demo(xs):\n"
        "    # if x in seen:\n"
        "    seen = {}\n"
        "    return seen\n"
    )
    detection = _detect(source)

    assert "hash_lookup" not in detection.names


def test_list_allocation_without_table_access_is_not_dynamic_programming() -> None:
    source = (
        "def running_total(n):\n"
        "    dp = [0] * n\n"
        "    total = 0\n"
        "    for i in range(n):\n"
        "        total += i\n"
        "    return total\n"
    )
    detection = _detect(source)

    assert "dynamic_programming" not in detection.names


@pytest.mark.parametrize(
    ("label", "source"),
    (
        (
            "binary_search_name_only",
            (
                "def binary_search(items, target):\n"
                "    # classic binary search\n"
                "    for value in items:\n"
                "        if value == target:\n"
                "            return True\n"
                "    return False\n"
            ),
        ),
        (
            "bfs_comment_only",
            (
                "def walk_graph(adj, start):\n"
                "    # breadth-first search over adjacency list\n"
                "    for neighbor in adj[start]:\n"
                "        print(neighbor)\n"
            ),
        ),
        (
            "dp_name_and_comment_only",
            (
                "def dynamic_programming_fib(n):\n"
                "    # bottom-up DP table would go here\n"
                "    a, b = 0, 1\n"
                "    for _ in range(n):\n"
                "        a, b = b, a + b\n"
                "    return a\n"
            ),
        ),
    ),
)
def test_names_and_comments_alone_do_not_trigger_binary_search_bfs_or_dp(
    label: str,
    source: str,
) -> None:
    detection = _detect(source)

    assert "binary_search" not in detection.names, label
    assert "bfs" not in detection.names, label
    assert "dynamic_programming" not in detection.names, label


def test_high_confidence_evidence_uses_algorithm_evidence_contract() -> None:
    source = _POSITIVE_EXAMPLES[0][1]
    detection = _assert_family_detected(source, "brute_force_nested_scan")

    assert detection.evidence
    entry = detection.evidence[0]
    assert isinstance(entry, AlgorithmEvidence)
    assert entry.kind
    assert entry.line >= 1
    assert entry.detail
    assert 0.0 <= entry.confidence <= 1.0


def test_sorting_reports_n_log_n_time_complexity() -> None:
    source = next(source for family, source in _POSITIVE_EXAMPLES if family == "sorting")
    detection = _detect(source)

    assert detection.time_complexity is not None
    assert detection.time_complexity.expression == "O(n log n)"


def test_brute_force_nested_scan_reports_quadratic_time_complexity() -> None:
    source = _POSITIVE_EXAMPLES[0][1]
    detection = _detect(source)

    assert detection.time_complexity is not None
    assert detection.time_complexity.expression == "O(n^2)"
    assert detection.time_complexity.family == "single_variable"
    assert detection.time_complexity.source == "python_ast"


def test_bfs_reports_graph_time_complexity() -> None:
    source = next(source for family, source in _POSITIVE_EXAMPLES if family == "bfs")
    detection = _detect(source)

    assert detection.time_complexity is not None
    assert detection.time_complexity.expression == "O(V+E)"
    assert detection.time_complexity.family == "graph"


def test_detect_algorithms_returns_frozen_algorithm_detection() -> None:
    source = _POSITIVE_EXAMPLES[2][1]
    detection = _detect(source)

    assert isinstance(detection, AlgorithmDetection)
    with pytest.raises(Exception):
        detection.names = ("sorting",)  # type: ignore[misc]
