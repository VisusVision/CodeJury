from __future__ import annotations

import ast
from typing import Literal

from backend.algorithm_analysis.contracts import AlgorithmEvidence, StrictFrozenModel

RecursionKind = Literal["direct", "mutual"]


class LoopFact(StrictFrozenModel):
    line: int
    depth: int


class RecursionSignal(StrictFrozenModel):
    kind: RecursionKind
    line: int
    functions: tuple[str, ...]


class AssignmentFact(StrictFrozenModel):
    line: int
    target: str


class SubscriptFact(StrictFrozenModel):
    line: int
    base: str


class PythonAstFacts(StrictFrozenModel):
    loops: tuple[LoopFact, ...] = ()
    max_loop_depth: int = 0
    recursion_signals: tuple[RecursionSignal, ...] = ()
    call_names: tuple[str, ...] = ()
    assignments: tuple[AssignmentFact, ...] = ()
    subscripts: tuple[SubscriptFact, ...] = ()
    data_structures: tuple[str, ...] = ()
    evidence: tuple[AlgorithmEvidence, ...] = ()
    syntax_error: str | None = None


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _name_from_expr(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _name_from_expr(node.value)
    return None


def _assignment_target(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        return _name_from_expr(node.value)
    return None


def _subscript_base(node: ast.Subscript) -> str | None:
    return _name_from_expr(node.value)


def _evidence(kind: str, line: int, detail: str, confidence: float = 0.85) -> AlgorithmEvidence:
    return AlgorithmEvidence(kind=kind, line=line, detail=detail, confidence=confidence)


class _FactCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.loops: list[LoopFact] = []
        self.loop_depth = 0
        self.max_loop_depth = 0
        self.call_names: set[str] = set()
        self.assignments: list[AssignmentFact] = []
        self.subscripts: list[SubscriptFact] = []
        self.data_structures: set[str] = set()
        self.evidence: list[AlgorithmEvidence] = []
        self.imported_modules: set[str] = set()
        self.imported_names: set[str] = set()
        self.function_defs: set[str] = set()
        self.function_calls: dict[str, list[tuple[int, str]]] = {}
        self._current_function: str | None = None
        self._append_targets: dict[str, list[int]] = {}
        self._pop_targets: dict[str, list[int]] = {}
        self._has_while_loop = False
        self._bound_targets: set[str] = set()

    def _record_call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name is None:
            return
        self.call_names.add(name)
        if self._current_function is not None:
            self.function_calls.setdefault(self._current_function, []).append(
                (node.lineno, name)
            )
        if name == "sorted":
            self.evidence.append(_evidence("sort_call", node.lineno, "builtin sorted() call"))
        elif name == "sort":
            self.evidence.append(_evidence("sort_call", node.lineno, "list.sort() method call"))
        elif name == "set":
            self.data_structures.add("set")
            self.evidence.append(_evidence("data_structure", node.lineno, "set() construction"))
        elif name == "deque":
            self.data_structures.add("deque")
            self.evidence.append(_evidence("data_structure", node.lineno, "deque() construction"))
        elif name == "append" and isinstance(node.func, ast.Attribute):
            target = _name_from_expr(node.func.value)
            if target is not None:
                self._append_targets.setdefault(target, []).append(node.lineno)
        elif name == "pop" and isinstance(node.func, ast.Attribute):
            target = _name_from_expr(node.func.value)
            if target is not None:
                self._pop_targets.setdefault(target, []).append(node.lineno)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "heapq":
                self.data_structures.add("heapq")
                self.evidence.append(
                    _evidence("data_structure", node.lineno, "heapq module usage")
                )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imported_modules.add(alias.asname or alias.name.split(".")[0])
            if alias.name == "heapq" or alias.name.startswith("heapq."):
                self.data_structures.add("heapq")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            name = alias.asname or alias.name
            self.imported_names.add(name)
            if module == "collections" and name == "deque":
                self.data_structures.add("deque")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_defs.add(node.name)
        previous = self._current_function
        self._current_function = node.name
        self.generic_visit(node)
        self._current_function = previous

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_For(self, node: ast.For) -> None:
        self.loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self.loop_depth)
        self.loops.append(LoopFact(line=node.lineno, depth=self.loop_depth))
        self.evidence.append(
            _evidence("nested_loop", node.lineno, f"loop depth {self.loop_depth}")
        )
        if isinstance(node.iter, ast.Subscript):
            base = _subscript_base(node.iter)
            if base == "adj":
                self.evidence.append(
                    _evidence("adjacency_traversal", node.lineno, "iterate adjacency list")
                )
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self._has_while_loop = True
        self.loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self.loop_depth)
        self.loops.append(LoopFact(line=node.lineno, depth=self.loop_depth))
        self.evidence.append(
            _evidence("nested_loop", node.lineno, f"loop depth {self.loop_depth}")
        )
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            name = _assignment_target(target)
            if name is None:
                continue
            self.assignments.append(AssignmentFact(line=node.lineno, target=name))
            if name in {"lo", "hi"}:
                self._bound_targets.add(name)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.target is not None:
            name = _assignment_target(node.target)
            if name is not None:
                self.assignments.append(AssignmentFact(line=node.lineno, target=name))
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        base = _subscript_base(node)
        if base is not None:
            self.subscripts.append(SubscriptFact(line=node.lineno, base=base))
            if base == "memo":
                self.evidence.append(_evidence("dp_memo", node.lineno, "memo table access"))
            elif base == "dp":
                self.evidence.append(_evidence("dp_table", node.lineno, "dp table access"))
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        self.data_structures.add("dict")
        self.evidence.append(_evidence("data_structure", node.lineno, "dict literal"))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._record_call(node)
        self.generic_visit(node)

    def _build_recursion_signals(self) -> list[RecursionSignal]:
        signals: list[RecursionSignal] = []
        seen_mutual: set[frozenset[str]] = set()

        for func, calls in self.function_calls.items():
            for line, callee in calls:
                if callee == func:
                    signals.append(
                        RecursionSignal(kind="direct", line=line, functions=(func,))
                    )
                    self.evidence.append(
                        _evidence("direct_recursion", line, f"{func} calls itself")
                    )

        for func_a, calls_a in self.function_calls.items():
            callees_a = {callee for _, callee in calls_a}
            for func_b in callees_a:
                if func_a == func_b:
                    continue
                calls_b = self.function_calls.get(func_b, [])
                if any(callee == func_a for _, callee in calls_b):
                    pair = frozenset({func_a, func_b})
                    if pair in seen_mutual:
                        continue
                    seen_mutual.add(pair)
                    line = next(
                        lineno
                        for lineno, callee in calls_a
                        if callee == func_b
                    )
                    signals.append(
                        RecursionSignal(
                            kind="mutual",
                            line=line,
                            functions=(func_a, func_b),
                        )
                    )
                    self.evidence.append(
                        _evidence(
                            "mutual_recursion",
                            line,
                            f"{func_a} and {func_b} call each other",
                        )
                    )
        return signals

    def _detect_binary_search_bounds(self) -> None:
        if self._has_while_loop and self._bound_targets == {"lo", "hi"}:
            line = next(
                (row.line for row in self.assignments if row.target in {"lo", "hi"}),
                1,
            )
            self.evidence.append(
                _evidence("binary_search_bound", line, "lo/hi bound updates in while loop")
            )

    def _detect_rollback_mutation(self) -> None:
        for target in set(self._append_targets) & set(self._pop_targets):
            append_line = self._append_targets[target][0]
            pop_line = self._pop_targets[target][0]
            if append_line < pop_line:
                self.evidence.append(
                    _evidence(
                        "rollback_mutation",
                        pop_line,
                        f"{target} append/pop mutation pattern",
                    )
                )

    def finalize(self) -> PythonAstFacts:
        if "heapq" in self.imported_modules:
            self.data_structures.add("heapq")
        if "deque" in self.imported_names:
            self.data_structures.add("deque")

        self._detect_binary_search_bounds()
        self._detect_rollback_mutation()
        recursion_signals = self._build_recursion_signals()

        for structure in sorted(self.data_structures):
            if not any(
                entry.kind == "data_structure" and structure in entry.detail
                for entry in self.evidence
            ):
                self.evidence.append(
                    _evidence("data_structure", 1, f"{structure} usage detected", 0.8)
                )

        return PythonAstFacts(
            loops=tuple(self.loops),
            max_loop_depth=self.max_loop_depth,
            recursion_signals=tuple(recursion_signals),
            call_names=tuple(sorted(self.call_names)),
            assignments=tuple(self.assignments),
            subscripts=tuple(self.subscripts),
            data_structures=tuple(sorted(self.data_structures)),
            evidence=tuple(self.evidence),
            syntax_error=None,
        )


def extract_python_facts(source: str) -> PythonAstFacts:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        message = exc.msg or "invalid syntax"
        if exc.lineno is not None:
            message = f"{message} (line {exc.lineno})"
        return PythonAstFacts(syntax_error=message)

    collector = _FactCollector()
    collector.visit(tree)
    return collector.finalize()
