from __future__ import annotations

from backend.testing.comparator import compare_output
from backend.testing.contracts import EvaluatedTestCase, FormalTestCase, RawCaseResult
from backend.testing.runtime_classifier import classify_runtime


def evaluate_case(case: FormalTestCase, raw: RawCaseResult) -> EvaluatedTestCase:
    error_type: str | None = None
    error_message_tr: str | None = None
    status: str
    passed: bool

    if raw.timed_out:
        classification = classify_runtime(raw)
        status = "error"
        passed = False
        if classification is not None:
            error_type = classification.error_type
            error_message_tr = classification.error_message_tr
    elif raw.memory_exceeded:
        classification = classify_runtime(raw)
        status = "error"
        passed = False
        if classification is not None:
            error_type = classification.error_type
            error_message_tr = classification.error_message_tr
    elif not raw.compile_success:
        classification = classify_runtime(raw)
        status = "error"
        passed = False
        if classification is not None:
            error_type = classification.error_type
            error_message_tr = classification.error_message_tr
    elif raw.actual_exit_code != case.expected_exit_code:
        classification = classify_runtime(raw)
        if classification is not None and classification.error_type != "ExitMismatch":
            status = "error"
            passed = False
            error_type = classification.error_type
            error_message_tr = classification.error_message_tr
        else:
            status = "fail"
            passed = False
    else:
        classification = classify_runtime(raw)
        if classification is not None:
            status = "error"
            passed = False
            error_type = classification.error_type
            error_message_tr = classification.error_message_tr
        else:
            comparison = compare_output(case.expected_stdout, raw.actual_stdout)
            if comparison.matched:
                status = "pass"
                passed = True
            else:
                status = "fail"
                passed = False

    return EvaluatedTestCase(
        id=case.id,
        name=case.name,
        visibility=case.visibility,
        status=status,
        passed=passed,
        stdin=case.stdin,
        expected_stdout=case.expected_stdout,
        actual_stdout=raw.actual_stdout,
        actual_stderr=raw.actual_stderr,
        expected_exit_code=case.expected_exit_code,
        actual_exit_code=raw.actual_exit_code,
        error_type=error_type,
        error_message_tr=error_message_tr,
        source=case.source,
        oracle=case.oracle,
        files=case.files,
        wall_time_ms=raw.wall_time_ms,
        peak_memory_mb=raw.peak_memory_mb,
    )
