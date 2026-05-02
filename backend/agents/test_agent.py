"""
Dynamic Test Agent -- tam LLM: calistirma degerlendirmesi Ollama ile.

Derleme, exit kodu, test sayilari gibi olgular sandbox'tan alinir ve JSON'da sabitlenir; edge_case,
performance_notes ve skor yorumu LLM'den gelir. LLM cagrisi zorunludur (ollama kapaliysa hata).

Girdi:  {"sandbox_result": dict, "expected_output": str | list[dict],
         "source_code": str, "language": str}
Cikti:  TestAgentOutput dict
"""

import ast
import json

from backend.agents.base import BaseAgent, build_llm_user_suffix, format_assignment_context_for_prompt
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
- Score 0–100. Compilation failure → 0. Timeout / memory-exceeded → ~5. If a
  brief is on record and the code is off-topic, do not award high score even if
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


class TestAgent(BaseAgent):
    name = "test_agent"
    description = "Dinamik test ve calistirma analizi"

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

        llm_result = await self._call_llm(
            system_prompt=_TEST_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            required_keys=["compilation_success", "score"],
            output_json_schema=TEST_AGENT_OUTPUT_SCHEMA,
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
        p_fail = programmatic.get("test_failures")
        if isinstance(p_fail, list) and p_fail:
            llm_result["test_failures"] = p_fail
        elif not isinstance(llm_result.get("test_failures"), list) or not llm_result.get("test_failures"):
            llm_result["test_failures"] = p_fail or []
        p_re = programmatic.get("runtime_errors")
        if isinstance(p_re, list) and p_re:
            llm_result["runtime_errors"] = p_re
        elif not isinstance(llm_result.get("runtime_errors"), list) or not llm_result.get("runtime_errors"):
            llm_result["runtime_errors"] = p_re or []

        prog_s = programmatic["score"]
        llm_s = self._safe_int(llm_result.get("score"), prog_s)
        af = float(programmatic.get("brief_code_alignment_factor", 1.0))
        if af < 0.999:
            blended = int(round(prog_s + (llm_s - prog_s) * af))
            llm_result["score"] = max(0, min(100, min(llm_s, max(prog_s, blended))))
        else:
            llm_result["score"] = llm_s

        observed = llm_result.get("edge_cases_observed")
        if not isinstance(observed, list):
            llm_result["edge_cases_observed"] = []
        else:
            llm_result["edge_cases_observed"] = [
                str(item).strip()
                for item in observed
                if isinstance(item, (str, int, float)) and str(item).strip()
            ][:8]

        return llm_result

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
            return d

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
        if timeout and service_program:
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
                "score": 68 if align_f >= 0.7 else 50,
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
        if mem_exceeded and service_program:
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

        if isinstance(expected, list):
            for idx, tc in enumerate(expected, 1):
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
        edge_case = _evaluate_edge_cases_ast(source_code, language)
        if assignment_mismatch_fail:
            edge_case = "poor"
        perf_notes = _evaluate_performance(exec_time, peak_mem)

        total_tests = max(passed + failed, 1)
        if not runs_ok:
            score = 15
        else:
            correctness_pct = (passed / total_tests) * 100
            score = int(correctness_pct * 0.7)
            if not runtime_errors:
                score += 15
            edge_bonus = {"poor": 0, "fair": 5, "good": 10, "excellent": 15}.get(edge_case, 0)
            score += edge_bonus

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
            "score": max(0, min(100, score)),
        })


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

            # raise statements
            if isinstance(node, ast.Raise):
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
