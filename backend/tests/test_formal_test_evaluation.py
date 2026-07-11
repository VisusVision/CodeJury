"""RED tests for backend.testing.evaluation."""

from __future__ import annotations

from backend.testing.contracts import FormalTestCase, RawCaseResult
from backend.testing.evaluation import evaluate_case


def _formal_case(**kwargs: object) -> FormalTestCase:
    defaults: dict[str, object] = {
        "id": "case-1",
        "name": "square two",
        "stdin": "2\n",
        "expected_stdout": "4\n",
        "expected_exit_code": 0,
        "visibility": "public",
        "source": "auto_generated",
        "oracle": "llm_verified",
    }
    defaults.update(kwargs)
    return FormalTestCase(**defaults)


def _raw_result(**kwargs: object) -> RawCaseResult:
    defaults: dict[str, object] = {
        "id": "case-1",
        "actual_stdout": "4\n",
        "actual_stderr": "",
        "actual_exit_code": 0,
        "timed_out": False,
        "memory_exceeded": False,
        "compile_success": True,
        "container_passed": True,
    }
    defaults.update(kwargs)
    return RawCaseResult(**defaults)


def test_evaluation_overrides_container_passed_when_output_wrong() -> None:
    evaluated = evaluate_case(
        _formal_case(),
        _raw_result(actual_stdout="5\n", container_passed=True),
    )
    assert evaluated.status == "fail"
    assert evaluated.passed is False
    assert evaluated.actual_stdout == "5\n"


def test_evaluation_passes_whitespace_equivalent_output_despite_container_fail() -> None:
    evaluated = evaluate_case(
        _formal_case(expected_stdout="4  \n"),
        _raw_result(actual_stdout="4\t\n", container_passed=False),
    )
    assert evaluated.status == "pass"
    assert evaluated.passed is True


def test_evaluation_copies_source_oracle_visibility_from_formal_case() -> None:
    case = _formal_case(
        visibility="hidden",
        source="manual",
        oracle="teacher",
    )
    evaluated = evaluate_case(case, _raw_result())
    assert evaluated.visibility == "hidden"
    assert evaluated.source == "manual"
    assert evaluated.oracle == "teacher"


def test_evaluation_marks_timeout_as_error() -> None:
    evaluated = evaluate_case(
        _formal_case(),
        _raw_result(timed_out=True, actual_stdout="", container_passed=False),
    )
    assert evaluated.status == "error"
    assert evaluated.passed is False
    assert evaluated.error_type == "Timeout"


def test_evaluation_marks_exit_mismatch_as_fail_not_error() -> None:
    evaluated = evaluate_case(
        _formal_case(expected_exit_code=0),
        _raw_result(actual_exit_code=1, container_passed=False),
    )
    assert evaluated.status == "fail"
    assert evaluated.passed is False
    assert evaluated.error_type is None


def test_evaluation_marks_runtime_exception_as_error() -> None:
    evaluated = evaluate_case(
        _formal_case(),
        _raw_result(
            actual_exit_code=1,
            actual_stderr="Traceback...\nZeroDivisionError: division by zero",
            container_passed=False,
        ),
    )
    assert evaluated.status == "error"
    assert evaluated.passed is False
    assert evaluated.error_type == "ZeroDivisionError"


def test_evaluation_passes_matching_nonzero_exit_code() -> None:
    evaluated = evaluate_case(
        _formal_case(expected_exit_code=1, expected_stdout=""),
        _raw_result(actual_exit_code=1, actual_stdout="", container_passed=False),
    )
    assert evaluated.status == "pass"
    assert evaluated.passed is True
    assert evaluated.error_type is None


def test_evaluation_passes_matching_nonzero_exit_with_warning_stderr() -> None:
    evaluated = evaluate_case(
        _formal_case(expected_exit_code=1, expected_stdout=""),
        _raw_result(
            actual_exit_code=1,
            actual_stdout="",
            actual_stderr="warning: unused import",
            container_passed=False,
        ),
    )
    assert evaluated.status == "pass"
    assert evaluated.passed is True
    assert evaluated.error_type is None
