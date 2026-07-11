from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Literal

from backend.algorithm_analysis.contracts import AlgorithmEvidence, StrictFrozenModel

RecursionKind = Literal["direct", "mutual"]
IterationKind = Literal["constant", "input_dependent", "unknown"]
NameResolver = Callable[[str], IterationKind]


class LoopFact(StrictFrozenModel):
    line: int
    depth: int
    iteration_kind: IterationKind = "unknown"


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


def _merge_iteration_kinds(*kinds: IterationKind) -> IterationKind:
    if not kinds:
        return "unknown"
    if any(kind == "unknown" for kind in kinds):
        return "unknown"
    if any(kind == "input_dependent" for kind in kinds):
        return "input_dependent"
    return "constant"


def _is_constant_literal_expr(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(isinstance(elt, ast.Constant) for elt in node.elts)
    return False


def _classify_range_bound(
    node: ast.expr,
    resolve_name: NameResolver,
) -> IterationKind:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return "constant"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _classify_range_bound(node.operand, resolve_name)
    if isinstance(node, ast.Name):
        return resolve_name(node.id)
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name == "len" and node.args:
            return _classify_iteration(node.args[0], resolve_name)
        return "unknown"
    if isinstance(node, ast.BinOp):
        return _merge_iteration_kinds(
            _classify_range_bound(node.left, resolve_name),
            _classify_range_bound(node.right, resolve_name),
        )
    return "unknown"


def _classify_iteration(
    node: ast.expr,
    resolve_name: NameResolver,
) -> IterationKind:
    if isinstance(node, ast.Constant):
        return "constant"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        if not node.elts:
            return "constant"
        return _merge_iteration_kinds(
            *(
                "constant"
                if isinstance(elt, ast.Constant)
                else "unknown"
                for elt in node.elts
            )
        )
    if isinstance(node, ast.Name):
        return resolve_name(node.id)
    if isinstance(node, ast.Attribute):
        base = _name_from_expr(node.value)
        if base is None:
            return "unknown"
        return resolve_name(base)
    if isinstance(node, ast.Subscript):
        base = _subscript_base(node)
        if base is None:
            return "unknown"
        return resolve_name(base)
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name == "range":
            if not node.args:
                return "constant"
            return _merge_iteration_kinds(
                *(_classify_range_bound(arg, resolve_name) for arg in node.args)
            )
        if name in {"enumerate", "reversed", "sorted", "list", "tuple", "set"} and node.args:
            return _classify_iteration(node.args[0], resolve_name)
        if name == "zip" and node.args:
            return _merge_iteration_kinds(
                *(_classify_iteration(arg, resolve_name) for arg in node.args)
            )
        return "unknown"
    return "unknown"


def _is_irrefutable_match_pattern(pattern: ast.pattern) -> bool:
    """Capture (`x`) or wildcard (`_`) patterns always match."""
    if isinstance(pattern, ast.MatchAs):
        return pattern.pattern is None
    if isinstance(pattern, ast.MatchOr):
        return any(_is_irrefutable_match_pattern(part) for part in pattern.patterns)
    return False


def _match_has_unguarded_irrefutable_case(node: ast.Match) -> bool:
    """True when some case is an unguarded irrefutable pattern (exhaustive fallthrough)."""
    for case in node.cases:
        if case.guard is not None:
            continue
        if _is_irrefutable_match_pattern(case.pattern):
            return True
    return False


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
        # Innermost binding wins: constant | input_dependent | unknown
        self._scope_bindings: list[dict[str, IterationKind]] = [{}]

    def _resolve_name(self, name: str) -> IterationKind:
        for bindings in reversed(self._scope_bindings):
            if name in bindings:
                return bindings[name]
        return "unknown"

    def _push_function_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        bindings: dict[str, IterationKind] = {}
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            bindings[arg.arg] = "input_dependent"
        if node.args.vararg is not None:
            bindings[node.args.vararg.arg] = "input_dependent"
        if node.args.kwarg is not None:
            bindings[node.args.kwarg.arg] = "input_dependent"
        self._scope_bindings.append(bindings)

    def _pop_function_scope(self) -> None:
        self._scope_bindings.pop()

    def _classify_binding_value(self, value: ast.expr | None) -> IterationKind:
        if value is None:
            return "unknown"
        if _is_constant_literal_expr(value):
            return "constant"
        if isinstance(value, ast.Name):
            # No alias analysis: copying a Name may share a mutable object.
            return "unknown"
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return _classify_iteration(value, self._resolve_name)
        return "unknown"

    def _set_binding(self, name: str, kind: IterationKind) -> None:
        self._scope_bindings[-1][name] = kind

    def _mark_assignment_binding(self, name: str, value: ast.expr | None) -> None:
        if isinstance(value, ast.Name):
            # Without alias tracking, invalidate both names so later mutations
            # through either spelling cannot leave a stale constant binding.
            self._set_binding(name, "unknown")
            self._set_binding(value.id, "unknown")
            return
        self._set_binding(name, self._classify_binding_value(value))

    def _mark_mutation_unknown(self, name: str) -> None:
        self._set_binding(name, "unknown")

    def _merge_path_bindings(
        self,
        before: dict[str, IterationKind],
        *path_bindings: dict[str, IterationKind],
    ) -> dict[str, IterationKind]:
        if not path_bindings:
            return dict(before)
        keys: set[str] = set(before)
        for path in path_bindings:
            keys |= path.keys()
        merged = dict(before)
        for key in keys:
            kinds: list[IterationKind] = []
            for path in path_bindings:
                if key in path:
                    kinds.append(path[key])
                elif key in before:
                    kinds.append(before[key])
                else:
                    kinds.append("unknown")
            merged[key] = kinds[0] if len(set(kinds)) == 1 else "unknown"
        return merged

    def _visit_branch_suite(self, statements: list[ast.stmt]) -> dict[str, IterationKind]:
        for stmt in statements:
            self.visit(stmt)
        return dict(self._scope_bindings[-1])

    _MUTATING_METHODS = frozenset({
        "append",
        "extend",
        "insert",
        "pop",
        "remove",
        "clear",
        "sort",
        "reverse",
        "add",
        "update",
        "discard",
        "setdefault",
    })

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
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr
            if method in self._MUTATING_METHODS:
                target = _name_from_expr(node.func.value)
                if target is not None:
                    self._mark_mutation_unknown(target)
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "heapq":
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
        self._push_function_scope(node)
        self.generic_visit(node)
        self._pop_function_scope()
        self._current_function = previous

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_For(self, node: ast.For) -> None:
        self.loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self.loop_depth)
        iteration_kind = _classify_iteration(node.iter, self._resolve_name)
        self.loops.append(
            LoopFact(line=node.lineno, depth=self.loop_depth, iteration_kind=iteration_kind)
        )
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
        self.loops.append(
            LoopFact(line=node.lineno, depth=self.loop_depth, iteration_kind="unknown")
        )
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
            if isinstance(target, ast.Name):
                self._mark_assignment_binding(name, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.target is not None:
            name = _assignment_target(node.target)
            if name is not None:
                self.assignments.append(AssignmentFact(line=node.lineno, target=name))
                if isinstance(node.target, ast.Name):
                    self._mark_assignment_binding(name, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._mark_mutation_unknown(node.target.id)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        before = dict(self._scope_bindings[-1])
        self._scope_bindings[-1] = dict(before)
        then_bindings = self._visit_branch_suite(list(node.body))
        self._scope_bindings[-1] = dict(before)
        else_bindings = self._visit_branch_suite(list(node.orelse))
        self._scope_bindings[-1] = self._merge_path_bindings(
            before, then_bindings, else_bindings
        )

    def visit_Try(self, node: ast.Try) -> None:
        before = dict(self._scope_bindings[-1])
        self._scope_bindings[-1] = dict(before)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)
        try_ok = dict(self._scope_bindings[-1])

        handler_bindings: list[dict[str, IterationKind]] = []
        for handler in node.handlers:
            self._scope_bindings[-1] = dict(before)
            if handler.type is not None:
                self.visit(handler.type)
            for stmt in handler.body:
                self.visit(stmt)
            handler_bindings.append(dict(self._scope_bindings[-1]))

        paths = (try_ok, *handler_bindings) if handler_bindings else (try_ok,)
        self._scope_bindings[-1] = self._merge_path_bindings(before, *paths)
        for stmt in node.finalbody:
            self.visit(stmt)

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        before = dict(self._scope_bindings[-1])
        case_bindings: list[dict[str, IterationKind]] = []
        for case in node.cases:
            self._scope_bindings[-1] = dict(before)
            self.visit(case.pattern)
            if case.guard is not None:
                self.visit(case.guard)
            for stmt in case.body:
                self.visit(stmt)
            case_bindings.append(dict(self._scope_bindings[-1]))
        if not case_bindings:
            self._scope_bindings[-1] = before
            return
        paths: list[dict[str, IterationKind]] = list(case_bindings)
        # Non-exhaustive match: subject may miss every case; keep pre-match bindings.
        if not _match_has_unguarded_irrefutable_case(node):
            paths.append(dict(before))
        self._scope_bindings[-1] = self._merge_path_bindings(before, *paths)

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
