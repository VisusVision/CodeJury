"""RED tests for backend.testing.comparator."""

from __future__ import annotations

import pytest

from backend.testing.comparator import compare_output


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("a\r\nb\r\n", "a\nb\n"),
        ("a   b\n", "a\tb\n"),
        ("a  \n", "a\n"),
        ("\n1\n2\n\n", "1\n2"),
        ("0.3000000", "0.3000004"),
    ],
)
def test_comparator_accepts_defined_equivalence(expected: str, actual: str) -> None:
    assert compare_output(expected, actual).matched is True


def test_comparator_preserves_internal_blank_lines() -> None:
    assert compare_output("a\n\nb", "a\nb").matched is False


def test_comparator_rejects_real_content_difference() -> None:
    assert compare_output("42", "43").matched is False
