"""
Programmatic code analysis utilities -- AST + Pattern Matching + Metrics.

LLM KULLANILMAZ. Tum analiz Python kodu ile yapilir.
Python icin ast modulu, C++/Java icin regex tabanli analiz.
"""

import ast
import re
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FunctionInfo:
    name: str = ""
    line: int = 0
    end_line: int = 0
    length: int = 0
    params: list[str] = field(default_factory=list)
    has_docstring: bool = False
    has_type_hints: bool = False
    has_return_annotation: bool = False
    nested_loops: int = 0
    max_nesting: int = 0
    complexity: str = "O(1)"
    uses_recursion: bool = False


@dataclass
class CodeMetrics:
    total_lines: int = 0
    blank_lines: int = 0
    comment_lines: int = 0
    code_lines: int = 0
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[dict] = field(default_factory=list)
    max_nesting_depth: int = 0
    avg_function_length: float = 0.0
    has_docstrings: bool = False
    has_type_hints: bool = False
    has_main_guard: bool = False
    imports: list[str] = field(default_factory=list)
    loop_patterns: list[dict] = field(default_factory=list)
    global_variables: list[str] = field(default_factory=list)
    magic_numbers: list[dict] = field(default_factory=list)
    duplicate_lines: list[dict] = field(default_factory=list)
    modern_features: list[str] = field(default_factory=list)
    antipatterns: list[dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def add_line_numbers(code: str) -> str:
    lines = code.splitlines()
    width = len(str(len(lines)))
    return "\n".join(f"{i+1:>{width}} | {line}" for i, line in enumerate(lines))


def strip_comments(source_code: str, language: str) -> str:
    """Prompt injection korumasi: yorum satirlarini temizler."""
    if language in ("python", "py"):
        code = re.sub(r'#.*$', '', source_code, flags=re.MULTILINE)
        return code
    elif language in ("cpp", "c++", "c", "java", "javascript", "js"):
        code = re.sub(r'//.*$', '', source_code, flags=re.MULTILINE)
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        return code
    return source_code


def compare_outputs(actual: str, expected: str) -> dict:
    """Gercek ciktiyi beklenen ciktiyla satir satir karsilastirir."""
    actual_lines = actual.strip().splitlines()
    expected_lines = expected.strip().splitlines()

    matches = 0
    differences = []
    max_lines = max(len(actual_lines), len(expected_lines))

    for i in range(max_lines):
        a = actual_lines[i] if i < len(actual_lines) else "<MISSING>"
        e = expected_lines[i] if i < len(expected_lines) else "<EXTRA>"
        if a.strip() == e.strip():
            matches += 1
        else:
            differences.append({
                "line": i + 1,
                "expected": e,
                "actual": a,
            })

    total = max(max_lines, 1)
    return {
        "match_percentage": round(matches / total * 100, 1),
        "total_lines_compared": max_lines,
        "matching_lines": matches,
        "differences": differences[:20],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PYTHON AST ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════


def _count_nested_loops(node: ast.AST, depth: int = 0) -> tuple[int, int]:
    """Recursive olarak ic ice dongu sayisi ve max derinligi bulur."""
    max_depth = depth
    loop_count = 0

    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.For, ast.While)):
            loop_count += 1
            child_loops, child_depth = _count_nested_loops(child, depth + 1)
            loop_count += child_loops
            max_depth = max(max_depth, child_depth)
        else:
            child_loops, child_depth = _count_nested_loops(child, depth)
            loop_count += child_loops
            max_depth = max(max_depth, child_depth)

    return loop_count, max_depth


_NLOGN_BUILTINS = {"sorted", "sort", "heapify", "nsmallest", "nlargest"}
_N_BUILTINS = {"sum", "max", "min", "any", "all", "len", "enumerate", "zip",
               "map", "filter", "reversed", "set", "list", "tuple", "dict",
               "Counter", "Counter.most_common"}


def _estimate_complexity(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Fonksiyonun zaman karmasikligini tahmin eder."""
    _, max_loop_depth = _count_nested_loops(func_node)

    has_recursion = False
    func_name = func_node.name
    uses_nlogn = False
    uses_n = False

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            call_name = ""
            if isinstance(node.func, ast.Name):
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                call_name = node.func.attr

            if call_name == func_name:
                has_recursion = True
            if call_name in _NLOGN_BUILTINS:
                uses_nlogn = True
            if call_name in _N_BUILTINS:
                uses_n = True

    if has_recursion and max_loop_depth > 0:
        return "O(n * recursive)"
    elif has_recursion:
        return "O(recursive)"
    elif max_loop_depth == 0:
        if uses_nlogn:
            return "O(n log n)"
        elif uses_n:
            return "O(n)"
        return "O(1)"
    elif max_loop_depth == 1:
        if uses_nlogn:
            return "O(n^2 log n)"
        return "O(n)"
    elif max_loop_depth == 2:
        return "O(n^2)"
    elif max_loop_depth == 3:
        return "O(n^3)"
    else:
        return f"O(n^{max_loop_depth})"


def _is_function_like(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _function_calls_self(func_node: ast.AST) -> bool:
    """f() veya self.f() ile ayni fonksiyonun tekrar cagrilmasi (_estimate_complexity ile uyumlu)."""
    if not _is_function_like(func_node):
        return False
    name = func_node.name
    for n in ast.walk(func_node):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and n.func.id == name:
                return True
            if isinstance(n.func, ast.Attribute) and n.func.attr == name:
                return True
    return False


def _detect_modern_features(tree: ast.AST, source: str) -> list[str]:
    """Modern Python ozelliklerini tespit eder."""
    features = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ListComp):
            features.append("list_comprehension")
        elif isinstance(node, ast.SetComp):
            features.append("set_comprehension")
        elif isinstance(node, ast.DictComp):
            features.append("dict_comprehension")
        elif isinstance(node, ast.GeneratorExp):
            features.append("generator_expression")
        elif isinstance(node, ast.JoinedStr):
            features.append("f_string")
        elif isinstance(node, ast.With):
            features.append("context_manager")
        elif isinstance(node, (ast.NamedExpr,)):
            features.append("walrus_operator")
        elif isinstance(node, ast.Match):
            features.append("match_case")

    if "dataclass" in source or "@dataclass" in source:
        features.append("dataclass")
    if "TypeVar" in source or "Generic" in source:
        features.append("generics")
    if "Counter(" in source or "defaultdict(" in source:
        features.append("collections_usage")
    if "enumerate(" in source:
        features.append("enumerate")

    return list(set(features))


def _is_string_var(tree: ast.AST, var_name: str) -> bool:
    """Degiskenin string olarak initialize edilip edilmedigini kontrol eder."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == var_name:
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return True
                    if isinstance(node.value, ast.JoinedStr):
                        return True
    return False


def _detect_antipatterns(tree: ast.AST, source: str) -> list[dict]:
    """Anti-pattern'leri tespit eder."""
    antipatterns = []

    for node in ast.walk(tree):
        # range(len(x)) -- stil onerisi, yanlis degil
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "range":
                if node.args and isinstance(node.args[0], ast.Call):
                    inner = node.args[0]
                    if isinstance(inner.func, ast.Name) and inner.func.id == "len":
                        antipatterns.append({
                            "type": "range_len",
                            "line": node.lineno,
                            "description": "Oneri: range(len()) yerine enumerate() kullanilabilir",
                            "severity": "suggestion",
                        })

        # Bare except -- gercek bug riski
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            antipatterns.append({
                "type": "bare_except",
                "line": node.lineno,
                "description": "Bare 'except:' kullanilmis, spesifik exception belirtin",
                "severity": "high",
            })

        # Mutable default argument -- gercek bug riski
        if _is_function_like(node):
            for default in node.args.defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    antipatterns.append({
                        "type": "mutable_default",
                        "line": node.lineno,
                        "description": f"{node.name}() fonksiyonunda mutable default argument -- bug olusturabilir",
                        "severity": "high",
                    })

        # == True / == False -- stil onerisi, yanlis degil
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.Is)):
                    if isinstance(comp, ast.Constant) and comp.value in (True, False):
                        antipatterns.append({
                            "type": "eq_true_false",
                            "line": node.lineno,
                            "description": (
                                f"Oneri: '== {comp.value}' yerine "
                                + ("direkt kosul" if comp.value else "'not' operatoru")
                                + " kullanilabilir"
                            ),
                            "severity": "suggestion",
                        })

        # String concatenation in loop (+=) -- sadece string degiskenler icin
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            if isinstance(node.target, ast.Name) and _is_string_var(tree, node.target.id):
                for parent in ast.walk(tree):
                    if isinstance(parent, (ast.For, ast.While)):
                        for child in ast.walk(parent):
                            if child is node:
                                antipatterns.append({
                                    "type": "string_concat_loop",
                                    "line": node.lineno,
                                    "description": "Dongu icinde += ile string birlestirme -- buyuk veride yavas olabilir",
                                    "severity": "low",
                                })
                                break

    # Global variable usage
    lines = source.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("global "):
            antipatterns.append({
                "type": "global_keyword",
                "line": i + 1,
                "description": "global keyword kullanimi -- kapsullemeyi bozar",
                "severity": "medium",
            })

    return antipatterns


def _detect_magic_numbers(tree: ast.AST) -> list[dict]:
    """Magic number'lari tespit eder (0, 1, 2, -1 haric)."""
    magic = []
    allowed = {0, 1, 2, -1, 100, 10}

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value not in allowed and abs(node.value) > 2:
                if hasattr(node, "lineno"):
                    magic.append({
                        "value": node.value,
                        "line": node.lineno,
                    })

    return magic


def _find_duplicate_lines(source: str) -> list[dict]:
    """Tekrarlanan anlamli satirlari bulur (DRY ihlalleri)."""
    lines = source.splitlines()
    seen = {}
    duplicates = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        skip = ("#", "//", "/*", "import", "from", "def ", "async def ", "class ")
        if len(stripped) > 25 and not stripped.startswith(skip):
            if stripped in seen:
                duplicates.append({
                    "first_line": seen[stripped] + 1,
                    "duplicate_line": i + 1,
                    "code": stripped[:60],
                })
            else:
                seen[stripped] = i

    return duplicates


def analyze_python_ast(source_code: str) -> CodeMetrics:
    """Python kodu icin AST tabanli derin analiz."""
    metrics = CodeMetrics()
    lines = source_code.splitlines()
    metrics.total_lines = len(lines)

    # Line counting
    for line in lines:
        stripped = line.strip()
        if not stripped:
            metrics.blank_lines += 1
        elif stripped.startswith('#'):
            metrics.comment_lines += 1
        else:
            metrics.code_lines += 1

    # AST parsing
    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        metrics.antipatterns.append({
            "type": "syntax_error",
            "line": e.lineno or 0,
            "description": f"Syntax hatasi: {e.msg}",
            "severity": "critical",
        })
        return metrics

    # Functions (sync + async)
    for node in ast.walk(tree):
        if _is_function_like(node):
            end_line = getattr(node, "end_lineno", node.lineno + 5)
            length = end_line - node.lineno + 1

            has_doc = (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            )

            has_hints = any(
                arg.annotation is not None
                for arg in node.args.args
            )
            has_return = node.returns is not None

            nested_loops, max_nest = _count_nested_loops(node)
            complexity = _estimate_complexity(node)
            has_recursion = _function_calls_self(node)

            fn = FunctionInfo(
                name=node.name,
                line=node.lineno,
                end_line=end_line,
                length=length,
                params=[arg.arg for arg in node.args.args],
                has_docstring=has_doc,
                has_type_hints=has_hints,
                has_return_annotation=has_return,
                nested_loops=nested_loops,
                max_nesting=max_nest,
                complexity=complexity,
                uses_recursion=has_recursion,
            )
            metrics.functions.append(fn)

        elif isinstance(node, ast.ClassDef):
            metrics.classes.append({"name": node.name, "line": node.lineno})

        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    metrics.imports.append(alias.name)
            else:
                metrics.imports.append(f"from {node.module}" if node.module else "from .")

    # Loop patterns
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            parent_loops = 0
            for p in ast.walk(tree):
                if isinstance(p, (ast.For, ast.While)) and p != node:
                    for child in ast.walk(p):
                        if child is node:
                            parent_loops += 1

            metrics.loop_patterns.append({
                "type": "for" if isinstance(node, ast.For) else "while",
                "line": node.lineno,
                "nesting_level": parent_loops,
                "code": lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
            })

    # Max nesting
    if metrics.loop_patterns:
        metrics.max_nesting_depth = max(lp["nesting_level"] for lp in metrics.loop_patterns) + 1

    # Function stats
    if metrics.functions:
        metrics.avg_function_length = round(
            sum(f.length for f in metrics.functions) / len(metrics.functions), 1
        )
        metrics.has_docstrings = any(f.has_docstring for f in metrics.functions)
        metrics.has_type_hints = any(f.has_type_hints for f in metrics.functions)

    # Main guard
    metrics.has_main_guard = 'if __name__' in source_code

    # Modern features
    metrics.modern_features = _detect_modern_features(tree, source_code)

    # Anti-patterns
    metrics.antipatterns = _detect_antipatterns(tree, source_code)

    # Magic numbers
    metrics.magic_numbers = _detect_magic_numbers(tree)

    # Duplicate lines
    metrics.duplicate_lines = _find_duplicate_lines(source_code)

    return metrics


def analyze_generic(source_code: str, language: str) -> CodeMetrics:
    """C++/Java icin regex tabanli basit analiz."""
    metrics = CodeMetrics()
    lines = source_code.splitlines()
    metrics.total_lines = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            metrics.blank_lines += 1
        elif stripped.startswith(("//", "/*", "*", "#")):
            metrics.comment_lines += 1
        else:
            metrics.code_lines += 1

        loop_match = re.match(r'^(\s*)(for|while)\s*[\(]', line)
        if loop_match:
            indent = len(loop_match.group(1))
            metrics.loop_patterns.append({
                "type": loop_match.group(2),
                "line": i + 1,
                "nesting_level": indent // 4,
                "code": stripped,
            })

    if metrics.loop_patterns:
        metrics.max_nesting_depth = max(lp["nesting_level"] for lp in metrics.loop_patterns) + 1

    metrics.duplicate_lines = _find_duplicate_lines(source_code)
    return metrics


def get_code_metrics(source_code: str, language: str) -> CodeMetrics:
    """Dile gore uygun analyzer'i secer."""
    lang = language.lower()
    if lang in ("python", "py"):
        return analyze_python_ast(source_code)
    return analyze_generic(source_code, lang)


def format_metrics_summary(metrics: CodeMetrics) -> str:
    """Metrikleri okunabilir ozet formata cevirir."""
    parts = [
        f"Toplam: {metrics.total_lines} satir "
        f"(kod: {metrics.code_lines}, bos: {metrics.blank_lines}, yorum: {metrics.comment_lines})",
    ]

    if metrics.functions:
        fn_list = []
        for f in metrics.functions:
            flags = []
            if f.has_docstring:
                flags.append("doc")
            if f.has_type_hints:
                flags.append("typed")
            if f.uses_recursion:
                flags.append("recursive")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            fn_list.append(f"  {f.name}() satir {f.line}, {f.length} satir, {f.complexity}{flag_str}")
        parts.append(f"Fonksiyonlar ({len(metrics.functions)}):")
        parts.extend(fn_list)
        parts.append(f"Ort. fonksiyon uzunlugu: {metrics.avg_function_length} satir")

    if metrics.classes:
        parts.append(f"Siniflar: {', '.join(c['name'] for c in metrics.classes)}")

    if metrics.loop_patterns:
        parts.append(f"Donguler: {len(metrics.loop_patterns)}, max derinlik: {metrics.max_nesting_depth}")

    if metrics.modern_features:
        parts.append(f"Modern ozellikler: {', '.join(metrics.modern_features)}")

    if metrics.antipatterns:
        parts.append(f"Anti-pattern: {len(metrics.antipatterns)} tespit edildi")

    return "\n".join(parts)
