"""
Dynamic Test Agent -- tam LLM: calistirma degerlendirmesi Ollama ile.

Derleme, exit kodu, test sayilari ve skor gibi olgular sandbox/programatik katmandan alinir ve
JSON'da sabitlenir; LLM yalnizca edge_case/performance yorumunu zenginlestirir.

Girdi:  {"sandbox_result": dict, "expected_output": str | list[dict],
         "source_code": str, "language": str}
Cikti:  TestAgentOutput dict
"""

import ast
import json

from backend.agents.base import (
    BaseAgent,
    LLMInferenceError,
    build_llm_user_suffix,
    format_assignment_context_for_prompt,
)
from backend.agents.json_output_schema import TEST_AGENT_OUTPUT_SCHEMA
from backend.agents.assignment_alignment import (
    BRIEF_MIN_LEN,
    alignment_summary_tr,
    compute_brief_code_alignment,
)
from backend.agents.code_utils import compare_outputs

_TEST_SYSTEM_PROMPT = """\
You are an expert test / runtime analyst working from a secure Linux sandbox. The user message
gives you the FACTUAL sandbox results (compilation, exit code, stdout, stderr, execution time,
memory). Treat those facts as ground truth — never invent compilation success, runs status, or
pass/fail counts. Your qualitative fields elaborate on top of facts.

What you must report:
- compilation_success / runs_successfully: booleans aligned with sandbox facts.
- passed_tests / failed_tests / test_failures: aligned with sandbox-recorded unit tests.
- runtime_errors: classify any error visible in stderr or static analysis.
- edge_case_handling: "poor"|"fair"|"good"|"excellent" overall judgement.
- edge_cases_observed: concrete edge cases the code DOES handle (or explicitly says
  it does not). Mention things like empty input, None / null, single element, very
  large input, duplicate keys, negative numbers, boundary indexes, IO failure,
  concurrent access — only those relevant to this code.
- performance_notes: comment on time and memory ranges based on sandbox metrics.
- Score 0–100 using these bands:
  * compilation failure = 0.
  * timeout / memory exceeded for normal scripts = 0-10.
  * uncaught runtime exception / non-zero exit for normal scripts = 0-35.
  * CLI usage error because required arguments were not supplied = not a runtime failure; grade as limited smoke coverage.
  * long-running API/server process = not a timeout failure when the code is clearly a service.
  * passing smoke run with no formal tests = limited runtime evidence; when programmatic hints include
    static_checks_passed, treat those as verified edge-case signals from source code (not invented tests).
  If a brief is on record and the code is off-topic, do not award high score even if
  the binary runs — trust the brief_alignment hint.

Reply with ONLY this JSON shape:
{
  "compilation_success": true|false,
  "runs_successfully": true|false,
  "passed_tests": 0,
  "failed_tests": 0,
  "test_failures": [],
  "runtime_errors": [],
  "edge_case_handling": "poor|fair|good|excellent",
  "edge_cases_observed": [],
  "performance_notes": "...",
  "score": 0-100
}
"""


def _edge_case_rank(value: str) -> int:
    return {"poor": 0, "fair": 1, "good": 2, "excellent": 3}.get(str(value or "").strip().lower(), 1)


def _max_edge_case(*values: str) -> str:
    order = ("poor", "fair", "good", "excellent")
    best = "poor"
    for value in values:
        if _edge_case_rank(value) >= _edge_case_rank(best):
            best = str(value or best).strip().lower()
    return best if best in order else "fair"


def _func_source_segment(source_code: str, node: ast.AST) -> str:
    try:
        return ast.get_source_segment(source_code, node) or ""
    except (TypeError, ValueError):
        return ""


def _count_edge_guard_indicators(tree: ast.AST) -> int:
    indicators = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                indicators += 1
            elif isinstance(test, ast.Compare):
                for comp in test.comparators:
                    if isinstance(comp, ast.Constant):
                        if comp.value is None or comp.value == "" or comp.value == 0:
                            indicators += 1
        if isinstance(node, ast.Try):
            indicators += 1
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "isinstance":
            indicators += 1
        if isinstance(node, ast.Raise):
            indicators += 1
    return indicators


def _collect_static_behavior_checks(source_code: str, language: str) -> list[dict]:
    """Kaynak koddan genel davranis sinyalleri cikarir (odev-agnostik)."""
    if language.lower() not in ("python", "py"):
        return _collect_static_behavior_checks_generic(source_code)

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "test_name": f"static:{name}",
                "input": "",
                "expected": detail,
                "actual": "Kaynak kodda tespit edildi" if passed else "Kaynak kodda bulunamadi",
                "passed": passed,
                "match_pct": 100.0 if passed else 0.0,
                "visibility": "static",
            }
        )

    has_custom_exc = any(
        isinstance(node, ast.ClassDef)
        and any(
            (isinstance(base, ast.Name) and base.id == "Exception")
            or (isinstance(base, ast.Attribute) and base.attr == "Exception")
            for base in node.bases
        )
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    )
    add("custom_exception", has_custom_exc, "Ozel exception sinifi tanimli")

    has_try = any(isinstance(node, ast.Try) for node in ast.walk(tree))
    has_typed_handler = any(
        isinstance(node, ast.Try) and any(handler.type is not None for handler in node.handlers)
        for node in ast.walk(tree)
    )
    add("error_handling", has_typed_handler or has_try, "Hata yakalama (try/except) mevcut")

    has_raise = any(isinstance(node, ast.Raise) for node in ast.walk(tree))
    add("explicit_error_signaling", has_raise, "Hata durumunda raise kullanimi")

    mutators = {"pop", "peek", "dequeue", "remove", "popleft", "popitem"}
    guarded_mutator = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        seg = _func_source_segment(source_code, node).lower()
        if not seg:
            continue
        touches_mutator = node.name in mutators or ".pop(" in seg or ".remove(" in seg
        if not touches_mutator:
            continue
        if "raise" in seg and any(
            token in seg
            for token in ("is_empty", "len(", "not self", "if not ", "== 0", "==0")
        ):
            guarded_mutator = True
            break
    add("empty_guard_before_mutator", guarded_mutator, "Bos/yetersiz durumda mutator oncesi kontrol")

    guard_ifs = _count_edge_guard_indicators(tree)
    add("boundary_guards", guard_ifs >= 2, "Sinir/bos/None kosul kontrolleri")

    has_isinstance = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        for node in ast.walk(tree)
    )
    add("input_type_validation", has_isinstance, "isinstance ile girdi dogrulama")

    has_zd_handler = any(
        isinstance(handler.type, ast.Name) and handler.type.id == "ZeroDivisionError"
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    )
    add("division_guard", has_zd_handler, "ZeroDivisionError icin koruma")

    add("main_entrypoint", 'if __name__' in source_code, "__main__ guard ile calistirilabilir yapi")

    return checks[:8]


def _collect_static_behavior_checks_generic(source_code: str) -> list[dict]:
    src = source_code or ""
    lowered = src.lower()
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "test_name": f"static:{name}",
                "input": "",
                "expected": detail,
                "actual": "Kaynak kodda tespit edildi" if passed else "Kaynak kodda bulunamadi",
                "passed": passed,
                "match_pct": 100.0 if passed else 0.0,
                "visibility": "static",
            }
        )

    add("error_handling", "try" in lowered and "catch" in lowered, "try/catch hata yakalama")
    add("explicit_error_signaling", "throw" in lowered, "throw ile hata sinyali")
    add("boundary_guards", "if (" in lowered and ("null" in lowered or "empty" in lowered), "Sinir/bos kontrol")
    add("main_entrypoint", "int main" in lowered, "main giris noktasi")
    return [check for check in checks if check.get("passed")]


def _runtime_static_test_counts(test_results: list) -> tuple[int, int, int]:
    runtime_passed = runtime_failed = static_passed = 0
    for item in test_results or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("test_name") or "")
        is_static = item.get("visibility") == "static" or name.startswith("static:")
        if bool(item.get("passed")):
            if is_static:
                static_passed += 1
            else:
                runtime_passed += 1
        elif not is_static:
            runtime_failed += 1
    return runtime_passed, runtime_failed, static_passed


def _scan_code_security_risks(source_code: str, language: str) -> list[dict]:
    if language.lower() not in ("python", "py"):
        return []
    try:
        from backend.agents.security import _check_dangerous_patterns, _check_python_ast

        merged: list[dict] = []
        seen: set[tuple] = set()
        for raw in _check_python_ast(source_code) + _check_dangerous_patterns(source_code):
            if not isinstance(raw, dict):
                continue
            key = (raw.get("line"), str(raw.get("type") or ""))
            if key in seen:
                continue
            seen.add(key)
            merged.append(raw)
        return merged
    except Exception:
        return []


def _min_edge_case(*values: str) -> str:
    order = ("poor", "fair", "good", "excellent")
    best = "excellent"
    for value in values:
        text = str(value or "").strip().lower()
        if text in order and order.index(text) < order.index(best):
            best = text
    return best


def _compute_test_score(
    *,
    runtime_passed: int,
    runtime_failed: int,
    static_passed: int = 0,
    edge_case: str,
    runs_ok: bool,
    runtime_errors: list,
) -> int:
    total_runtime = runtime_passed + runtime_failed
    if not runs_ok:
        if runtime_passed > 0 and total_runtime > 0:
            correctness_pct = (runtime_passed / total_runtime) * 100.0
            score = int(correctness_pct * 0.55) + 12
            return max(22, min(55, score))
        return 15 if runtime_failed else 25

    if total_runtime <= 0:
        score = 18
    else:
        correctness_pct = (runtime_passed / total_runtime) * 100.0
        score = int(correctness_pct * 0.78) + (12 if not runtime_errors else 6)

    score += min(10, static_passed * 2)
    edge_bonus = {"poor": 0, "fair": 4, "good": 10, "excellent": 16}.get(edge_case, 4)
    if runtime_passed <= 0:
        edge_bonus = min(edge_bonus, 2)
    score += edge_bonus
    return max(0, min(100, score))


_NON_FORMAL_TEST_NAMES = {
    "Test #1",
    "cli_usage",
    "runtime",
    "compilation",
    "timeout",
    "memory",
    "stdin_smoke",
    "stdin_run",
    "Odev metniyle uyum",
}


def _is_formal_test_result(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("formal") is False:
        return False
    if item.get("formal") is True:
        return True
    name = str(item.get("test_name") or item.get("name") or "").strip()
    if name.startswith(("static:", "security:")):
        return False
    if name in _NON_FORMAL_TEST_NAMES:
        return False
    visibility = str(item.get("visibility") or "").strip().lower()
    return visibility in {"public", "hidden"}


def _formal_test_stats(test_results: list) -> tuple[int, int]:
    formal_results = [item for item in test_results if _is_formal_test_result(item)]
    passed = sum(1 for item in formal_results if bool(item.get("passed")))
    return passed, len(formal_results)


def _apply_formal_score_contract(
    payload: dict,
    *,
    test_evidence_status: str | None = None,
    test_source: str | None = None,
    test_set_id: str | None = None,
    cache_version: int | None = None,
) -> dict:
    out = dict(payload)
    formal_passed, formal_total = _formal_test_stats(list(out.get("test_results") or []))
    evidence_status = str(test_evidence_status or "").strip().lower()
    if evidence_status not in {"available", "unavailable"}:
        evidence_status = "available" if formal_total > 0 else "unavailable"

    out["formalPassed"] = formal_passed
    out["formalTotal"] = formal_total
    out["testEvidenceStatus"] = evidence_status
    if test_source is not None:
        out["testSource"] = str(test_source)
    if test_set_id is not None:
        out["testSetId"] = str(test_set_id)
    if cache_version is not None:
        out["cacheVersion"] = cache_version

    if formal_total > 0:
        formal_score = round(100 * formal_passed / formal_total)
        out["formalScore"] = formal_score
        out["score"] = formal_score
    else:
        out["formalScore"] = 0
        out["score"] = min(40, int(out.get("score", 0) or 0))
    return out


def _payload_has_formal_cases(payload: dict) -> bool:
    _, formal_total = _formal_test_stats(list(payload.get("test_results") or []))
    return formal_total > 0


def _recalculate_score_from_results(payload: dict) -> int:
    runtime_passed, runtime_failed, static_passed = _runtime_static_test_counts(
        payload.get("test_results") or []
    )
    return _compute_test_score(
        runtime_passed=runtime_passed,
        runtime_failed=runtime_failed,
        static_passed=static_passed,
        edge_case=str(payload.get("edge_case_handling", "fair")),
        runs_ok=bool(payload.get("runs_successfully")),
        runtime_errors=list(payload.get("runtime_errors") or []),
    )


def _is_severe_for_test_score(risk: dict) -> bool:
    typ = str(risk.get("type") or "").lower()
    sev = str(risk.get("severity") or "").lower()
    if typ in {"code_injection", "command_inject", "command_injection"}:
        return sev in {"critical", "high"}
    if sev == "critical" and typ not in {"network_access", "file_access"}:
        return True
    return False


def _apply_test_score_guardrails(
    payload: dict,
    source_code: str,
    language: str,
    align_f: float,
    task_alignment: dict | None,
) -> dict:
    out = dict(payload)
    if out.get("service_runtime_accepted") or _payload_has_formal_cases(out):
        return out

    out["score"] = _recalculate_score_from_results(out)

    align_factor = align_f
    off_topic = False
    if isinstance(task_alignment, dict):
        if "factor" in task_alignment:
            align_factor = float(task_alignment.get("factor", align_f))
        off_topic = bool(task_alignment.get("llm_off_topic"))

    cap = 100
    edge_cap = "excellent"
    guardrail_notes: list[str] = []

    risks = _scan_code_security_risks(source_code, language)
    severe = [risk for risk in risks if _is_severe_for_test_score(risk)]
    if _looks_like_http_client_program(source_code, language) and severe:
        severe = [
            risk
            for risk in severe
            if str(risk.get("type") or "").lower() not in {"network_access", "file_access"}
        ]
    if out.get("service_runtime_accepted") and severe:
        severe = [
            risk
            for risk in severe
            if str(risk.get("type") or "").lower() not in {"network_access", "file_access"}
        ]
    if severe:
        cap = min(cap, 34)
        edge_cap = "poor"
        guardrail_notes.append("Tehlikeli calistirma deseni (eval/exec/shell vb.)")
        existing = {str(item.get("test_name") or "") for item in out.get("test_results") or []}
        if "security:unsafe_runtime" not in existing:
            detail = str(severe[0].get("description") or "Guvenlik riski")[:180]
            out["test_results"] = list(out.get("test_results") or []) + [{
                "test_name": "security:unsafe_runtime",
                "input": "",
                "expected": "Guvenli calistirma",
                "actual": detail,
                "passed": False,
                "match_pct": 0.0,
                "visibility": "security",
            }]
            out["test_failures"] = list(out.get("test_failures") or []) + [{
                "test_name": "security:unsafe_runtime",
                "reason": detail,
            }]
            out["failed_tests"] = int(out.get("failed_tests", 0) or 0) + 1
            out["total_tests"] = int(out.get("passed_tests", 0) or 0) + int(out.get("failed_tests", 0) or 0)
            out["runs_successfully"] = False

    if off_topic or align_factor < 0.25:
        cap = min(cap, 40)
        edge_cap = "poor"
        guardrail_notes.append("Odev konusu ile uyumsuz teslim")
    elif align_factor < 0.45:
        cap = min(cap, 58)
        edge_cap = _min_edge_case(edge_cap, "fair")
        guardrail_notes.append("Odev metni ile sinirli uyum")

    out["edge_case_handling"] = _min_edge_case(out.get("edge_case_handling", "fair"), edge_cap)
    out["score"] = min(int(out.get("score", 0) or 0), cap)
    if guardrail_notes:
        out["test_score_guardrails"] = guardrail_notes
        note = " | ".join(guardrail_notes)
        perf = str(out.get("performance_notes") or "").strip()
        if note not in perf:
            out["performance_notes"] = f"{perf} | {note}".strip(" |")
    return out


def _augment_with_static_coverage(payload: dict, source_code: str, language: str) -> dict:
    """Smoke/formal testlerden sonra kaynak-kod davranis sinyallerini ekler."""
    if not payload.get("runs_successfully"):
        return payload
    if int(payload.get("failed_tests", 0) or 0) > 0:
        return payload

    static_checks = [check for check in _collect_static_behavior_checks(source_code, language) if check.get("passed")]
    if not static_checks:
        return payload

    out = dict(payload)
    existing = list(out.get("test_results") or [])
    existing_names = {str(item.get("test_name") or "") for item in existing}
    added = [check for check in static_checks if check.get("test_name") not in existing_names]
    if not added:
        return out

    for check in added:
        check["formal"] = False
    out["test_results"] = existing + added
    out["passed_tests"] = int(out.get("passed_tests", 0) or 0) + len(added)
    out["total_tests"] = int(out.get("passed_tests", 0) or 0) + int(out.get("failed_tests", 0) or 0)
    out["static_checks_passed"] = len(added)

    ast_edge = _evaluate_edge_cases_ast(source_code, language)
    static_edge = "excellent" if len(added) >= 4 else "good" if len(added) >= 2 else "fair"
    out["edge_case_handling"] = _max_edge_case(out.get("edge_case_handling", "fair"), ast_edge, static_edge)
    observed = [
        str(item.get("expected", "")).strip()
        for item in added
        if str(item.get("expected", "")).strip()
    ]
    if observed:
        out["edge_cases_observed"] = observed[:8]

    out["score"] = _recalculate_score_from_results(out)
    out["static_coverage_augmented"] = True
    return out


def _programmatic_from_sandbox_tests(
    sb_tests: list,
    *,
    exit_code: int,
    exec_time_ms: float,
    peak_memory_mb: float,
    stderr: str = "",
    expected_cases: list | None = None,
    source_code: str = "",
    language: str = "python",
) -> dict | None:
    """Map orchestrator test_results into TestAgent programmatic fields."""
    if not isinstance(sb_tests, list) or not sb_tests:
        return None

    visibility_by_name: dict[str, str] = {}
    if isinstance(expected_cases, list):
        for raw_case in expected_cases:
            if not isinstance(raw_case, dict):
                continue
            case_name = str(raw_case.get("name") or raw_case.get("test_name") or "").strip()
            visibility = str(raw_case.get("visibility") or "").strip().lower()
            if case_name and visibility in {"public", "hidden"}:
                visibility_by_name[case_name] = visibility

    test_results: list[dict] = []
    test_failures: list[dict] = []
    passed = 0
    failed = 0

    for raw in sb_tests:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("test_name") or "sandbox_test")
        ok = bool(raw.get("passed"))
        actual_stderr = str(raw.get("actual_stderr") or raw.get("stderr") or "")
        actual = str(raw.get("actual_stdout") or raw.get("actual") or actual_stderr or "")
        expected = str(raw.get("expected_stdout") or raw.get("expected") or "")
        detail = {
            "test_name": name,
            "input": str(raw.get("stdin") or raw.get("input") or "")[:120],
            "expected": expected[:200],
            "actual": actual[:200],
            "passed": ok,
            "match_pct": 100.0 if ok else 0.0,
            "formal": bool(expected_cases),
        }
        visibility = visibility_by_name.get(name)
        if visibility:
            detail["visibility"] = visibility
        if not ok:
            err = str(raw.get("error") or "Sandbox testi basarisiz")
            if actual_stderr and actual_stderr not in err:
                err = f"{err}\n{actual_stderr}"
            detail["diff_detail"] = err
            test_failures.append({"test_name": name, "reason": err})
            failed += 1
        else:
            passed += 1
        test_results.append(detail)

    if not test_results:
        return None

    error_text = "\n".join(
        str(item.get("reason") or "")
        for item in test_failures
        if isinstance(item, dict)
    )
    runtime_errors = _classify_errors("\n".join([stderr or "", error_text])) if failed or (exit_code != 0 and passed == 0) else []
    runs_ok = failed == 0 and (exit_code == 0 or passed > 0)
    edge_case = "good" if passed >= 2 else "fair"
    if source_code:
        edge_case = _max_edge_case(edge_case, _evaluate_edge_cases_ast(source_code, language))
    perf_notes = _evaluate_performance(exec_time_ms, peak_memory_mb)

    payload = {
        "compilation_success": True,
        "runs_successfully": runs_ok,
        "passed_tests": passed,
        "failed_tests": failed,
        "total_tests": passed + failed,
        "test_results": test_results,
        "test_failures": test_failures,
        "runtime_errors": runtime_errors,
        "edge_case_handling": edge_case,
        "performance_notes": perf_notes,
        "score": _compute_test_score(
            runtime_passed=passed,
            runtime_failed=failed,
            static_passed=0,
            edge_case=edge_case,
            runs_ok=runs_ok,
            runtime_errors=runtime_errors,
        ),
    }
    if source_code:
        payload = _augment_with_static_coverage(payload, source_code, language)
    if expected_cases:
        payload = _apply_formal_score_contract(payload)
    return payload


class TestAgent(BaseAgent):
    name = "test_agent"
    description = "Dinamik test ve calistirma analizi"

    def _pre_schema_normalize(self, result: dict, output_json_schema: dict | None) -> dict:
        if output_json_schema is not TEST_AGENT_OUTPUT_SCHEMA or not isinstance(result, dict):
            return result
        out = dict(result)
        flags = [
            str(flag)
            for flag in out.get("guardrail_flags", [])
            if str(flag).strip()
        ] if isinstance(out.get("guardrail_flags"), list) else []

        def default(key: str, value, flag: str = "test_agent_schema_defaulted") -> None:
            if key not in out or out.get(key) is None:
                out[key] = value
                if flag not in flags:
                    flags.append(flag)

        default("compilation_success", False)
        default("runs_successfully", False)
        default("passed_tests", 0)
        default("failed_tests", 0)
        default("test_failures", [])
        default("runtime_errors", [])
        default("edge_case_handling", "fair")
        default("edge_cases_observed", [])
        default("performance_notes", "")
        default("score", 0, "test_agent_score_defaulted")
        if flags:
            out["guardrail_flags"] = flags
        return out

    async def analyze(self, input_data: dict) -> dict:
        sandbox = input_data["sandbox_result"]
        expected = input_data.get("expected_output", "")
        source_code = input_data.get("source_code", "")
        language = input_data.get("language", "python")
        report_language = input_data.get("report_language") or "tr"

        programmatic = self._programmatic_analysis(
            sandbox,
            expected,
            source_code,
            language,
            input_data.get("assignment_description") or "",
            rubric_criteria=input_data.get("faculty_rubric_criteria"),
            task_alignment=input_data.get("task_alignment"),
        )

        truncated = self._truncate_code(source_code, max_lines=150)
        sb_compact = {
            "compiled": sandbox.get("compilation_success"),
            "exit": sandbox.get("exit_code"),
            "stdout": (sandbox.get("stdout") or "")[:300],
            "stderr": (sandbox.get("stderr") or "")[:300],
            "time_ms": sandbox.get("execution_time_ms"),
        }
        prog_compact = {
            "compiled": programmatic["compilation_success"],
            "runs": programmatic["runs_successfully"],
            "passed": programmatic.get("passed_tests", 0),
            "failed": programmatic.get("failed_tests", 0),
            "static_checks_passed": programmatic.get("static_checks_passed", 0),
            "brief_alignment": round(float(programmatic.get("brief_code_alignment_factor", 1.0)), 3),
            "edge_case_hint": programmatic["edge_case_handling"],
            "errors": programmatic.get("runtime_errors", [])[:3],
            "failures": [f.get("reason", "")[:80] for f in programmatic.get("test_failures", [])[:3]],
        }

        brief = format_assignment_context_for_prompt(input_data.get("assignment_description"))
        user_prompt = (
            f"Code (language tag: {language}):\n```\n{truncated}\n```\n"
            f"{brief}"
            f"FACTUAL sandbox (keep these values aligned in your JSON):\n{json.dumps(sb_compact, ensure_ascii=False, separators=(',',':'))}\n"
            f"Non-binding heuristic hint (score/edge are reference only):\n{json.dumps(prog_compact, ensure_ascii=False, separators=(',',':'))}\n"
            "Task: Enrich edge_case_handling and performance_notes; set score 0–100 consistent with facts."
            f"{build_llm_user_suffix(report_language=report_language)}"
        )

        try:
            llm_result = await self._call_llm(
                system_prompt=_TEST_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                required_keys=[],
                output_json_schema=TEST_AGENT_OUTPUT_SCHEMA,
            )
        except LLMInferenceError as exc:
            llm_result = self._with_contract_metadata(
                {
                    "compilation_success": programmatic["compilation_success"],
                    "runs_successfully": programmatic["runs_successfully"],
                    "passed_tests": programmatic["passed_tests"],
                    "failed_tests": programmatic["failed_tests"],
                    "test_failures": list(programmatic.get("test_failures") or []),
                    "runtime_errors": list(programmatic.get("runtime_errors") or []),
                    "edge_case_handling": programmatic.get("edge_case_handling", "fair"),
                    "edge_cases_observed": [],
                    "performance_notes": programmatic.get("performance_notes", ""),
                    "score": programmatic["score"],
                    "llm_error": str(exc)[:300],
                },
                llm_status="fallback",
                guardrail_flags=["llm_inference_fallback"],
            )

        # Sandbox-olgusal alanlar: her zaman programatik (hallucinasyonu onler)
        llm_result["compilation_success"] = programmatic["compilation_success"]
        llm_result["runs_successfully"] = programmatic["runs_successfully"]
        llm_result["passed_tests"] = programmatic["passed_tests"]
        llm_result["failed_tests"] = programmatic["failed_tests"]
        if "total_tests" in programmatic:
            llm_result["total_tests"] = programmatic["total_tests"]
        if "test_results" in programmatic:
            llm_result["test_results"] = programmatic["test_results"]
        if programmatic.get("static_checks_passed"):
            llm_result["static_checks_passed"] = programmatic["static_checks_passed"]
        if programmatic.get("static_coverage_augmented"):
            llm_result["static_coverage_augmented"] = True
        if programmatic.get("test_score_guardrails"):
            llm_result["test_score_guardrails"] = list(programmatic.get("test_score_guardrails") or [])
        if programmatic.get("service_runtime_accepted"):
            llm_result["service_runtime_accepted"] = True
        if programmatic.get("performance_notes") and not str(llm_result.get("performance_notes") or "").strip():
            llm_result["performance_notes"] = programmatic["performance_notes"]
        if programmatic.get("edge_cases_observed") and not llm_result.get("edge_cases_observed"):
            llm_result["edge_cases_observed"] = list(programmatic.get("edge_cases_observed") or [])
        p_fail = programmatic.get("test_failures")
        if isinstance(programmatic.get("test_results"), list):
            llm_result["test_failures"] = p_fail or []
        elif isinstance(p_fail, list) and p_fail:
            llm_result["test_failures"] = p_fail
        elif not isinstance(llm_result.get("test_failures"), list) or not llm_result.get("test_failures"):
            llm_result["test_failures"] = p_fail or []
        p_re = programmatic.get("runtime_errors")
        if isinstance(programmatic.get("test_results"), list):
            llm_result["runtime_errors"] = p_re or []
        elif isinstance(p_re, list) and p_re:
            llm_result["runtime_errors"] = p_re
        elif not isinstance(llm_result.get("runtime_errors"), list) or not llm_result.get("runtime_errors"):
            llm_result["runtime_errors"] = p_re or []

        prog_s = programmatic["score"]
        llm_s = self._safe_int(llm_result.get("score"), prog_s)
        defaulted_flags = [
            str(flag)
            for flag in (llm_result.get("guardrail_flags") or [])
            if str(flag).strip()
        ] if isinstance(llm_result.get("guardrail_flags"), list) else []
        score_was_defaulted = "test_agent_score_defaulted" in defaulted_flags

        llm_result["score"] = max(0, min(100, llm_s))
        # Objective runtime facts override LLM score (not heuristic programmatic hints).
        if not programmatic["compilation_success"]:
            llm_result["score"] = 0
        elif not programmatic["runs_successfully"]:
            llm_result["score"] = min(int(llm_result["score"]), 35)
        elif (
            not score_was_defaulted
            and int(programmatic.get("failed_tests", 0) or 0) == 0
            and int(programmatic.get("passed_tests", 0) or 0) > 0
            and int(llm_result["score"]) == 0
        ):
            # LLM score 0 contradicts recorded sandbox pass results — repair from facts.
            llm_result["score"] = max(1, min(100, int(prog_s)))
            flags = [
                str(flag)
                for flag in (llm_result.get("guardrail_flags") or [])
                if str(flag).strip()
            ] if isinstance(llm_result.get("guardrail_flags"), list) else []
            if "test_agent_score_repaired_sandbox_pass" not in flags:
                flags.append("test_agent_score_repaired_sandbox_pass")
            llm_result["guardrail_flags"] = flags
        elif (
            programmatic.get("service_runtime_accepted")
            and programmatic.get("runs_successfully")
        ):
            align_f = 1.0
            if isinstance(input_data.get("task_alignment"), dict):
                try:
                    align_f = float(input_data["task_alignment"].get("factor", 1.0) or 1.0)
                except (TypeError, ValueError):
                    align_f = 1.0
            service_floor = 70 if align_f >= 0.75 else 62
            llm_result["score"] = max(
                int(llm_result["score"]),
                int(prog_s),
                service_floor,
            )
            flags = [
                str(flag)
                for flag in (llm_result.get("guardrail_flags") or [])
                if str(flag).strip()
            ] if isinstance(llm_result.get("guardrail_flags"), list) else []
            if "test_agent_score_repaired_service_runtime" not in flags:
                flags.append("test_agent_score_repaired_service_runtime")
            llm_result["guardrail_flags"] = flags
        elif (
            programmatic.get("runs_successfully")
            and int(programmatic.get("failed_tests", 0) or 0) == 0
            and int(prog_s) > int(llm_result["score"])
            and not programmatic.get("test_score_guardrails")
        ):
            llm_result["score"] = max(int(llm_result["score"]), int(prog_s))
            flags = [
                str(flag)
                for flag in (llm_result.get("guardrail_flags") or [])
                if str(flag).strip()
            ] if isinstance(llm_result.get("guardrail_flags"), list) else []
            if "test_agent_score_repaired_programmatic_floor" not in flags:
                flags.append("test_agent_score_repaired_programmatic_floor")
            llm_result["guardrail_flags"] = flags

        observed = llm_result.get("edge_cases_observed")
        if not isinstance(observed, list):
            llm_result["edge_cases_observed"] = []
        else:
            llm_result["edge_cases_observed"] = [
                str(item).strip()
                for item in observed
                if isinstance(item, (str, int, float)) and str(item).strip()
            ][:8]

        return _apply_formal_score_contract(
            llm_result,
            test_evidence_status=input_data.get("test_evidence_status"),
            test_source=input_data.get("test_source"),
            test_set_id=input_data.get("test_set_id"),
            cache_version=input_data.get("cache_version"),
        )

    def _programmatic_analysis(
        self,
        sandbox: dict,
        expected,
        source_code: str,
        language: str,
        assignment_description: str = "",
        rubric_criteria: list | None = None,
        task_alignment: dict | None = None,
    ) -> dict:
        brief_raw = (assignment_description or "").strip()
        if isinstance(task_alignment, dict) and "factor" in task_alignment:
            align_f = float(task_alignment["factor"])
            align_rs = list(task_alignment.get("reasons", []))
        else:
            align_f, align_rs = compute_brief_code_alignment(
                brief_raw,
                source_code,
                rubric_criteria=rubric_criteria,
            )

        def _finish(d: dict) -> dict:
            d["brief_code_alignment_factor"] = align_f
            d["brief_alignment_reasons"] = list(align_rs)
            has_formal = _payload_has_formal_cases(d) or formal_expected_cases is not None
            if source_code and not has_formal:
                d = _apply_network_delivery_runtime_patch(
                    d,
                    source_code,
                    language,
                    timed_out=bool(timeout),
                    exit_code=int(exit_code or 0),
                    stderr=str(stderr or ""),
                    align_f=align_f,
                )
            if (
                source_code
                and d.get("runs_successfully")
                and int(d.get("failed_tests", 0) or 0) == 0
                and not has_formal
            ):
                d = _augment_with_static_coverage(d, source_code, language)
            if source_code:
                d = _apply_test_score_guardrails(
                    d,
                    source_code,
                    language,
                    align_f,
                    task_alignment,
                )
            return _apply_formal_score_contract(d)

        compilation = sandbox.get("compilation_success", True)
        exit_code = sandbox.get("exit_code", 0)
        stdout = sandbox.get("stdout", "")
        stderr = sandbox.get("stderr", "")
        exec_time = sandbox.get("execution_time_ms", 0)
        peak_mem = sandbox.get("peak_memory_mb", 0)
        timeout = sandbox.get("timed_out", sandbox.get("timeout", False))
        mem_exceeded = sandbox.get("memory_exceeded", False)
        sb_static = sandbox.get("static_analysis", {})
        service_program = _looks_like_service_program(source_code, language)
        cli_program = _looks_like_cli_program(source_code, language)
        cli_usage_exit = (
            cli_program
            and exit_code != 0
            and _looks_like_cli_usage_error(stderr)
        )

        formal_expected_cases = expected if isinstance(expected, list) and expected else None
        sandbox_tests = _programmatic_from_sandbox_tests(
            sandbox.get("test_results") or [],
            exit_code=exit_code,
            exec_time_ms=exec_time,
            peak_memory_mb=peak_mem,
            stderr=stderr,
            expected_cases=formal_expected_cases,
            source_code=source_code,
            language=language,
        )
        if sandbox_tests is not None:
            return _finish(sandbox_tests)

        if not compilation:
            errors = _classify_errors(stderr)
            return _finish({
                "compilation_success": False,
                "runs_successfully": False,
                "passed_tests": 0,
                "failed_tests": 1,
                "test_failures": [{"test_name": "compilation", "reason": stderr[:300]}],
                "runtime_errors": errors,
                "edge_case_handling": "poor",
                "performance_notes": "Kod derlenemedi.",
                "score": 0,
            })

        if timeout and not service_program:
            return _finish({
                "compilation_success": True,
                "runs_successfully": False,
                "passed_tests": 0,
                "failed_tests": 1,
                "test_failures": [{"test_name": "timeout", "reason": "Zaman asimi -- sonsuz dongu veya cok yavas algoritma"}],
                "runtime_errors": ["Timeout: sonsuz dongu veya cok yavas algoritma"],
                "edge_case_handling": "poor",
                "performance_notes": f"Timeout ({exec_time}ms)",
                "score": 5,
            })
        if timeout and service_program and formal_expected_cases is None:
            # API/server assignments often keep the process alive intentionally.
            return _finish({
                "compilation_success": True,
                "runs_successfully": True,
                "passed_tests": 1,
                "failed_tests": 0,
                "test_failures": [],
                "runtime_errors": [],
                "edge_case_handling": "fair",
                "performance_notes": (
                    f"Servis tipi uygulama tespit edildi; surekli calisma nedeniyle timeout ({exec_time}ms) "
                    "testte hata olarak sayilmadi."
                ),
                "score": 72 if align_f >= 0.7 else 58,
                "service_runtime_accepted": True,
            })

        if (
            service_program
            and compilation
            and exit_code != 0
            and "serve_forever" in (source_code or "").lower()
            and formal_expected_cases is None
        ):
            return _finish({
                "compilation_success": True,
                "runs_successfully": True,
                "passed_tests": 1,
                "failed_tests": 0,
                "test_failures": [],
                "runtime_errors": [],
                "edge_case_handling": "fair",
                "performance_notes": (
                    "Servis tipi uygulama sandbox ortaminda surekli calistigi icin "
                    "tek seferlik calistirma basarisizligi sayilmadi."
                ),
                "score": 72 if align_f >= 0.7 else 58,
                "service_runtime_accepted": True,
            })

        if mem_exceeded and not service_program:
            return _finish({
                "compilation_success": True,
                "runs_successfully": False,
                "passed_tests": 0,
                "failed_tests": 1,
                "test_failures": [{"test_name": "memory", "reason": "Bellek limiti asildi"}],
                "runtime_errors": [f"MemoryExceeded: {peak_mem:.1f}MB kullanildi, limit asildi"],
                "edge_case_handling": "poor",
                "performance_notes": f"Bellek asimi ({peak_mem:.1f}MB)",
                "score": 5,
            })
        if mem_exceeded and service_program and formal_expected_cases is None:
            return _finish({
                "compilation_success": True,
                "runs_successfully": True,
                "passed_tests": 1,
                "failed_tests": 0,
                "test_failures": [],
                "runtime_errors": [],
                "edge_case_handling": "fair",
                "performance_notes": (
                    f"Servis tipi uygulama icin bellek yuksek gorundu ({peak_mem:.1f}MB); "
                    "calisma basarisizligi sayilmadi."
                ),
                "score": 62 if align_f >= 0.7 else 48,
                "service_runtime_accepted": True,
            })

        if cli_usage_exit and formal_expected_cases is None:
            return _finish({
                "compilation_success": True,
                "runs_successfully": True,
                "passed_tests": 1,
                "failed_tests": 0,
                "total_tests": 1,
                "test_results": [{
                    "test_name": "cli_usage",
                    "input": "",
                    "expected": "CLI argumani istendiginde kullanim mesaji uretilmesi",
                    "actual": stderr[:200],
                    "passed": True,
                    "match_pct": 100.0,
                }],
                "test_failures": [],
                "runtime_errors": [],
                "edge_case_handling": "fair",
                "performance_notes": (
                    "CLI tipi program arguman bekliyor; formal test girdisi verilmedigi icin "
                    "kullanim mesaji runtime hatasi sayilmadi."
                ),
                "score": 72 if align_f >= 0.7 else 52,
            })

        runs_ok = exit_code == 0
        runtime_errors = []

        if exit_code != 0:
            runtime_errors = _classify_errors(stderr)

        if not runs_ok and not runtime_errors:
            runtime_errors.append(f"Exit code: {exit_code}")

        for issue in sb_static.get("issues", []):
            code = issue.get("code", "")
            msg = issue.get("message", "")
            line = issue.get("line", 0)
            if code.startswith("S") or code == "ERROR":
                entry = f"[Satir {line}] {msg}" if line else msg
                if entry not in runtime_errors:
                    runtime_errors.append(entry)

        test_results = []
        test_failures = []
        passed = 0
        failed = 0
        assignment_mismatch_fail = False

        if formal_expected_cases is not None:
            for idx, tc in enumerate(formal_expected_cases, 1):
                tc_name = tc.get("name", f"Test #{idx}")
                tc_input = tc.get("input", "")
                tc_expected = tc.get("expected", "")
                tc_actual = tc.get("actual", stdout)
                comparison = compare_outputs(tc_actual, tc_expected)

                case_passed = comparison["match_percentage"] == 100.0
                case_detail = {
                    "test_name": tc_name,
                    "input": tc_input[:120],
                    "expected": tc_expected[:200],
                    "actual": tc_actual[:200],
                    "passed": case_passed,
                    "match_pct": comparison["match_percentage"],
                    "formal": True,
                }

                if case_passed:
                    passed += 1
                else:
                    failed += 1
                    diffs = comparison["differences"][:3]
                    diff_text = "; ".join(
                        f"satir {d['line']}: beklenen='{d['expected'][:40]}' gercek='{d['actual'][:40]}'"
                        for d in diffs
                    )
                    case_detail["diff_detail"] = diff_text
                    test_failures.append({
                        "test_name": tc_name,
                        "input_data": tc_input[:80],
                        "expected": tc_expected[:100],
                        "actual": tc_actual[:100],
                        "reason": f"Cikti uyumsuzlugu (%{comparison['match_percentage']} eslesme). {diff_text}",
                    })

                test_results.append(case_detail)

        elif expected:
            comparison = compare_outputs(stdout, expected)
            case_passed = comparison["match_percentage"] == 100.0

            test_results.append({
                "test_name": "Test #1",
                "input": "",
                "expected": expected[:200],
                "actual": stdout[:200],
                "passed": case_passed,
                "match_pct": comparison["match_percentage"],
            })

            if case_passed:
                passed = 1
            else:
                failed = 1
                for diff in comparison["differences"][:5]:
                    test_failures.append({
                        "test_name": f"output_line_{diff['line']}",
                        "expected": diff["expected"],
                        "actual": diff["actual"],
                        "reason": "Cikti uyumsuzlugu",
                    })
        elif runs_ok:
            no_formal = not isinstance(expected, list) and not expected
            if no_formal and len(brief_raw) >= BRIEF_MIN_LEN and align_f < 0.42:
                assignment_mismatch_fail = True
                passed = 0
                failed = 1
                reason = alignment_summary_tr(align_rs)
                if not reason.strip():
                    reason = (
                        "Kod calisiyor ancak odev metnindeki konu ile teslim arasinda otomatik uyum kontrolu "
                        "ciddi uyumsuzluk gosteriyor."
                    )
                test_failures.append({
                    "test_name": "Odev metniyle uyum",
                    "reason": reason,
                })
                test_results.append({
                    "test_name": "Odev metniyle uyum",
                    "input": "",
                    "expected": (brief_raw[:500] + ("..." if len(brief_raw) > 500 else "")) or "(odev metni)",
                    "actual": stdout[:200],
                    "passed": False,
                    "match_pct": 0.0,
                })
            else:
                passed = 1
                test_results.append({
                    "test_name": "Test #1",
                    "input": "",
                    "expected": "(belirtilmemis)",
                    "actual": stdout[:200],
                    "passed": True,
                    "match_pct": 100.0,
                })
        elif passed + failed == 0:
            failed = 1
            reason = runtime_errors[0] if runtime_errors else f"Program exit code {exit_code} ile sonlandi."
            test_failures.append({
                "test_name": "runtime",
                "reason": reason,
            })
            test_results.append({
                "test_name": "runtime",
                "input": "",
                "expected": "Programin hatasiz tamamlanmasi",
                "actual": (stderr or stdout)[:200],
                "passed": False,
                "match_pct": 0.0,
            })
        edge_case = _evaluate_edge_cases_ast(source_code, language)
        if assignment_mismatch_fail:
            edge_case = "poor"
        perf_notes = _evaluate_performance(exec_time, peak_mem)

        return _finish({
            "compilation_success": compilation,
            "runs_successfully": runs_ok,
            "passed_tests": passed,
            "failed_tests": failed,
            "total_tests": passed + failed,
            "test_results": test_results,
            "test_failures": test_failures,
            "runtime_errors": runtime_errors,
            "edge_case_handling": edge_case,
            "performance_notes": perf_notes,
            "score": _compute_test_score(
                runtime_passed=passed,
                runtime_failed=failed,
                static_passed=0,
                edge_case=edge_case,
                runs_ok=runs_ok,
                runtime_errors=runtime_errors,
            ),
        })


def looks_like_missing_input_file_error(stderr: str) -> bool:
    return "filenotfounderror" in str(stderr or "").lower()


def _classify_errors(stderr: str) -> list[str]:
    errors = []
    stderr_lower = stderr.lower()

    if "segmentation fault" in stderr_lower or "sigsegv" in stderr_lower:
        errors.append("Segmentation fault: bellek erisim ihlali")
    if "stack overflow" in stderr_lower or "recursionerror" in stderr_lower:
        errors.append("Stack overflow: muhtemelen sonsuz recursion")
    if "timeout" in stderr_lower or "time limit" in stderr_lower:
        errors.append("Timeout: sonsuz dongu veya cok yavas algoritma")
    if "out of memory" in stderr_lower or "memoryerror" in stderr_lower:
        errors.append("Out of Memory: asiri bellek kullanimi")
    if "zerodivisionerror" in stderr_lower:
        errors.append("ZeroDivisionError: sifira bolme hatasi")
    if "indexerror" in stderr_lower:
        errors.append("IndexError: liste indeks asimi")
    if "keyerror" in stderr_lower:
        errors.append("KeyError: sozlukte bulunmayan anahtar")
    if "typeerror" in stderr_lower:
        errors.append("TypeError: tip uyumsuzlugu")
    if "valueerror" in stderr_lower:
        errors.append("ValueError: gecersiz deger")
    if "filenotfounderror" in stderr_lower:
        errors.append("FileNotFoundError: dosya bulunamadi")
    if "traceback" in stderr_lower and not errors:
        stderr_lines = stderr.strip().splitlines()
        if stderr_lines:
            errors.append(f"Python exception: {stderr_lines[-1][:200]}")
    if "error" in stderr_lower and not errors:
        errors.append(f"Hata: {stderr[:200]}")

    return errors


def _evaluate_edge_cases_ast(source_code: str, language: str) -> str:
    """AST + keyword tabanli edge case yonetimi analizi."""
    indicators = 0

    if language.lower() in ("python", "py"):
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return "poor"

        for node in ast.walk(tree):
            # if not x / if x is None / if len(x) == 0
            if isinstance(node, ast.If):
                test = node.test
                if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                    indicators += 1
                elif isinstance(test, ast.Compare):
                    for op, comp in zip(test.ops, test.comparators):
                        if isinstance(comp, ast.Constant) and comp.value is None:
                            indicators += 1
                        elif isinstance(comp, ast.Constant) and isinstance(comp.value, int) and comp.value == 0 and comp.value is not False:
                            indicators += 1
                        elif isinstance(comp, ast.Constant) and comp.value == "":
                            indicators += 1

            # try/except
            if isinstance(node, ast.Try):
                indicators += 2
                for handler in node.handlers:
                    if handler.type is not None:
                        indicators += 1

            # isinstance checks
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "isinstance":
                    indicators += 1

            # assert statements
            if isinstance(node, ast.Assert):
                indicators += 1

            # raise statements (custom errors)
            if isinstance(node, ast.Raise):
                indicators += 2
                if isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name):
                    indicators += 1
    else:
        if "if (" in source_code and ("null" in source_code.lower() or "nullptr" in source_code):
            indicators += 1
        if "try" in source_code and "catch" in source_code:
            indicators += 2
        if "throw" in source_code:
            indicators += 1

    if indicators >= 5:
        return "excellent"
    elif indicators >= 3:
        return "good"
    elif indicators >= 1:
        return "fair"
    return "poor"


def _evaluate_performance(exec_time, peak_mem) -> str:
    parts = []

    if exec_time:
        if exec_time < 100:
            parts.append(f"Calisma suresi: {exec_time}ms (hizli)")
        elif exec_time < 1000:
            parts.append(f"Calisma suresi: {exec_time}ms (kabul edilebilir)")
        elif exec_time < 5000:
            parts.append(f"Calisma suresi: {exec_time}ms (yavas)")
        else:
            parts.append(f"Calisma suresi: {exec_time}ms (cok yavas!)")

    if peak_mem:
        if peak_mem < 50:
            parts.append(f"Bellek: {peak_mem}MB (dusuk)")
        elif peak_mem < 256:
            parts.append(f"Bellek: {peak_mem}MB (orta)")
        else:
            parts.append(f"Bellek: {peak_mem}MB (yuksek!)")

    return " | ".join(parts) if parts else "Performans verisi yok."


def _looks_like_service_program(source_code: str, language: str) -> bool:
    src = (source_code or "").lower()
    if language.lower() in ("python", "py"):
        service_markers = (
            "serve_forever(",
            "httpserver(",
            "basehttprequesthandler",
            "app.run(",
            "uvicorn.run(",
            "fastapi(",
            "@app.get(",
            "@app.post(",
        )
        return any(marker in src for marker in service_markers)
    return any(marker in src for marker in ("listen(", "accept(", "bind(", "server"))


def _looks_like_http_client_program(source_code: str, language: str) -> bool:
    src = (source_code or "").lower()
    if language.lower() in ("python", "py"):
        client_markers = (
            "urllib.request",
            "urlopen(",
            "requests.get",
            "requests.post",
            "httpx.get",
            "httpx.post",
            "aiohttp.client",
        )
        return any(marker in src for marker in client_markers)
    return any(marker in src for marker in ("curl ", "http.get", "fetch("))


def _network_runtime_failure_blob(*, stderr: str = "", test_failures: list | None = None) -> str:
    parts = [(stderr or "").lower()]
    for item in test_failures or []:
        if isinstance(item, dict):
            parts.append(str(item.get("reason") or "").lower())
    return " ".join(parts)


def _indicates_service_or_network_sandbox_limit(blob: str) -> bool:
    needles = (
        "timeout",
        "timed out",
        "time out",
        "connection refused",
        "actively refused",
        "errno 111",
        "errno 98",
        "address already in use",
        "serve_forever",
        "network is unreachable",
        "name or service not known",
        "urlopen error",
        "http error",
    )
    return any(needle in blob for needle in needles)


def _apply_network_delivery_runtime_patch(
    payload: dict,
    source_code: str,
    language: str,
    *,
    timed_out: bool = False,
    exit_code: int = 0,
    stderr: str = "",
    align_f: float = 1.0,
) -> dict:
    """HTTP sunucu/istemci teslimlerinde sandbox ag kisitlarini yumusat."""
    if _payload_has_formal_cases(payload):
        return payload
    service = _looks_like_service_program(source_code, language)
    client = _looks_like_http_client_program(source_code, language)
    if not service and not client:
        return payload

    out = dict(payload)
    failures = list(out.get("test_failures") or [])
    blob = _network_runtime_failure_blob(stderr=stderr, test_failures=failures)
    failed = int(out.get("failed_tests", 0) or 0)
    accept = False

    if service:
        if timed_out:
            accept = True
        elif failed > 0 and _indicates_service_or_network_sandbox_limit(blob):
            accept = True
        elif not out.get("runs_successfully") and exit_code != 0 and timed_out:
            accept = True
    elif client:
        if exit_code == 0 and align_f >= 0.45:
            if failed == 0:
                accept = True
            elif failed > 0 and _indicates_service_or_network_sandbox_limit(blob):
                accept = True

    if not accept:
        return out

    floor_score = 68 if align_f >= 0.7 else 52
    if client and not service:
        floor_score = 72 if align_f >= 0.7 else 58

    out["runs_successfully"] = True
    out["service_runtime_accepted"] = True
    out["score"] = max(int(out.get("score", 0) or 0), floor_score)
    note = (
        "Ag/servis tipi teslim sandbox ortaminda surekli calisma veya ag erisimi olmadan "
        "test edildigi icin kismi runtime basarisizligi sayilmadi."
    )
    perf = str(out.get("performance_notes") or "").strip()
    if note not in perf:
        out["performance_notes"] = f"{perf} | {note}".strip(" |")
    return out


def _looks_like_cli_program(source_code: str, language: str) -> bool:
    src = (source_code or "").lower()
    if language.lower() in ("python", "py"):
        markers = (
            "argparse",
            "argumentparser(",
            "sys.argv",
            "click.command",
            "typer.",
            "add_argument(",
        )
        return any(marker in src for marker in markers)
    return any(marker in src for marker in ("argc", "argv", "getopt"))


def _looks_like_cli_usage_error(stderr: str) -> bool:
    err = (stderr or "").lower()
    return (
        "usage:" in err
        or "the following arguments are required" in err
        or "required:" in err
        or "too few arguments" in err
    )
