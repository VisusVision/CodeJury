"""RED tests for backend.testing.runtime_classifier."""

from __future__ import annotations

import pytest

from backend.testing.contracts import RawCaseResult
from backend.testing.runtime_classifier import classify_runtime


def raw_case(**kwargs: object) -> RawCaseResult:
    defaults: dict[str, object] = {
        "id": "case-1",
        "actual_stdout": "",
        "actual_stderr": "",
        "actual_exit_code": 0,
        "timed_out": False,
        "memory_exceeded": False,
        "compile_success": True,
    }
    defaults.update(kwargs)
    return RawCaseResult(**defaults)


@pytest.mark.parametrize(
    ("raw_kwargs", "expected_type", "expected_message_fragment"),
    [
        ({"timed_out": True}, "Timeout", "zaman aşım"),
        ({"memory_exceeded": True}, "MemoryExceeded", "bellek"),
        ({"compile_success": False}, "CompilationError", "derle"),
        (
            {"actual_exit_code": 1, "actual_stderr": ""},
            "ExitMismatch",
            "çıkış",
        ),
        (
            {"actual_stderr": "Traceback...\nZeroDivisionError: division by zero"},
            "ZeroDivisionError",
            "sıfıra bölme",
        ),
        (
            {"actual_stderr": "Traceback...\nIndexError: list index out of range"},
            "IndexError",
            "indeks",
        ),
        (
            {"actual_stderr": "Traceback...\nKeyError: 'missing'"},
            "KeyError",
            "anahtar",
        ),
        (
            {"actual_stderr": "Traceback...\nTypeError: unsupported operand"},
            "TypeError",
            "tip",
        ),
        (
            {"actual_stderr": "Traceback...\nValueError: invalid literal"},
            "ValueError",
            "değer",
        ),
        (
            {"actual_stderr": "Traceback...\nFileNotFoundError: [Errno 2]"},
            "FileNotFoundError",
            "dosya",
        ),
        (
            {"actual_stderr": "Traceback...\nRuntimeError: boom"},
            "RuntimeError",
            "çalışma zamanı",
        ),
        (
            {"actual_exit_code": 1, "actual_stderr": "something unexpected"},
            "UnknownRuntimeError",
            "bilinmeyen",
        ),
    ],
)
def test_runtime_classifier_taxonomy(
    raw_kwargs: dict[str, object],
    expected_type: str,
    expected_message_fragment: str,
) -> None:
    classification = classify_runtime(raw_case(**raw_kwargs))
    assert classification is not None
    assert classification.error_type == expected_type
    assert expected_message_fragment in classification.error_message_tr.lower()


def test_runtime_classifier_returns_none_for_clean_run() -> None:
    assert classify_runtime(raw_case()) is None


def test_timeout_wins_over_stderr_exception() -> None:
    classification = classify_runtime(
        raw_case(timed_out=True, actual_stderr="ZeroDivisionError: division by zero")
    )
    assert classification is not None
    assert classification.error_type == "Timeout"


def test_memory_wins_over_exit_mismatch() -> None:
    classification = classify_runtime(
        raw_case(memory_exceeded=True, actual_exit_code=1)
    )
    assert classification is not None
    assert classification.error_type == "MemoryExceeded"


def test_compile_failure_wins_before_runtime_parsing() -> None:
    classification = classify_runtime(
        raw_case(
            compile_success=False,
            actual_stderr="Traceback...\nZeroDivisionError: division by zero",
        )
    )
    assert classification is not None
    assert classification.error_type == "CompilationError"


def test_matching_nonzero_exit_allows_benign_stderr_warnings() -> None:
    assert (
        classify_runtime(
            raw_case(actual_exit_code=1, actual_stderr="warning: deprecated api"),
            expected_exit_code=1,
        )
        is None
    )


def test_matching_nonzero_exit_still_reports_known_exception() -> None:
    classification = classify_runtime(
        raw_case(
            actual_exit_code=1,
            actual_stderr="Traceback...\nZeroDivisionError: division by zero",
        ),
        expected_exit_code=1,
    )
    assert classification is not None
    assert classification.error_type == "ZeroDivisionError"
