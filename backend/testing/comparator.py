from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

_HORIZONTAL_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")


@dataclass(frozen=True)
class ComparisonResult:
    matched: bool
    normalized_expected: str
    normalized_actual: str
    mode: Literal["text", "numeric"]


def normalize_output(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    normalized_lines = [
        _HORIZONTAL_WHITESPACE_RE.sub(" ", line).rstrip(" ")
        for line in lines
    ]
    while normalized_lines and normalized_lines[0] == "":
        normalized_lines.pop(0)
    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()
    return "\n".join(normalized_lines)


def parse_single_decimal(value: str) -> Decimal | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        number = Decimal(stripped)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return number


def compare_output(expected: str, actual: str) -> ComparisonResult:
    exp = normalize_output(expected)
    act = normalize_output(actual)
    exp_num = parse_single_decimal(exp)
    act_num = parse_single_decimal(act)
    if exp_num is not None and act_num is not None:
        absolute_tolerance = Decimal("1e-6")
        relative_tolerance = Decimal("1e-9")
        difference = abs(exp_num - act_num)
        scale = max(abs(exp_num), abs(act_num))
        matched = difference <= max(absolute_tolerance, relative_tolerance * scale)
        return ComparisonResult(matched, exp, act, "numeric")
    return ComparisonResult(exp == act, exp, act, "text")
