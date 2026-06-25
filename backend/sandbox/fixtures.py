"""Infer minimal sandbox fixture files for file-based student submissions."""

from __future__ import annotations

import re
from pathlib import PurePosixPath


_INPUT_EXT_RE = r"(?:csv|txt)"
_PATH_RE = re.compile(
    rf"""Path\s*\(\s*['"]([^'"]+\.{_INPUT_EXT_RE})['"]\s*\)|open\s*\(\s*['"]([^'"]+\.{_INPUT_EXT_RE})['"]""",
    re.IGNORECASE,
)
_PATH_ASSIGN_RE = re.compile(
    rf"""(\w+)\s*=\s*Path\s*\(\s*['"]([^'"]+\.{_INPUT_EXT_RE})['"]\s*\)""",
    re.IGNORECASE,
)
_BRIEF_FILE_RE = re.compile(rf"\b[\w.-]+\.{_INPUT_EXT_RE}\b", re.IGNORECASE)


def _default_csv_content(filename: str) -> str:
    lower = filename.lower()
    if any(token in lower for token in ("ogrenci", "score", "not", "input", "grade")):
        return "name,score\nAyse,88\nMehmet,42\n"
    return "name,value\nsample,1\n"


def _default_txt_content(filename: str) -> str:
    lower = filename.lower()
    if any(token in lower for token in ("sayi", "number", "input")):
        return "10\nabc\n7\n-3\n0\n\n12\n5\n"
    return "ornek satir\nikinci satir\n"


def _default_content(filename: str) -> str:
    if filename.lower().endswith(".csv"):
        return _default_csv_content(filename)
    return _default_txt_content(filename)


def _candidate_names(source_code: str, assignment_brief: str) -> list[str]:
    names: list[str] = []

    def _remember(raw: str) -> None:
        name = PurePosixPath(raw).name
        if name and name not in names:
            names.append(name)

    for match in _BRIEF_FILE_RE.finditer(assignment_brief):
        _remember(match.group(0))
    for match in _BRIEF_FILE_RE.finditer(source_code):
        _remember(match.group(0))
    return names


def _paths_opened_for_read(source_code: str, assignment_brief: str) -> list[str]:
    """Collect filenames that student code reads (skip write-only outputs)."""
    read_names: list[str] = []

    def _remember(raw: str) -> None:
        name = PurePosixPath(raw).name
        if name and name not in read_names:
            read_names.append(name)

    for var, raw_path in _PATH_ASSIGN_RE.findall(source_code):
        if re.search(rf"{re.escape(var)}\.open\s*\(\s*['\"]r", source_code, re.IGNORECASE):
            _remember(raw_path)
        elif re.search(rf"{re.escape(var)}\.read_text\s*\(", source_code, re.IGNORECASE):
            _remember(raw_path)

    for match in _PATH_RE.finditer(source_code):
        raw_path = match.group(1) or match.group(2)
        if not raw_path:
            continue
        basename = PurePosixPath(raw_path).name
        escaped = re.escape(basename)
        if re.search(
            rf"open\s*\(\s*['\"]{escaped}['\"]\s*,\s*['\"]r",
            source_code,
            re.IGNORECASE,
        ):
            _remember(raw_path)
            continue
        if re.search(
            rf"Path\s*\(\s*['\"]{escaped}['\"]\s*\)\.read_text\s*\(",
            source_code,
            re.IGNORECASE,
        ):
            _remember(raw_path)
            continue
        if re.search(rf"open\s*\(\s*['\"]{escaped}['\"]\s*\)", source_code) and not re.search(
            rf"open\s*\(\s*['\"]{escaped}['\"]\s*,\s*['\"]w",
            source_code,
            re.IGNORECASE,
        ):
            _remember(raw_path)

    def _is_written(name: str) -> bool:
        escaped = re.escape(name)
        return bool(
            re.search(
                rf"Path\s*\(\s*['\"]{escaped}['\"]\s*\)\.write_text\s*\(",
                source_code,
                re.IGNORECASE,
            )
            or re.search(
                rf"open\s*\(\s*['\"]{escaped}['\"]\s*,\s*['\"]w",
                source_code,
                re.IGNORECASE,
            )
        )

    def _looks_like_output_target(name: str) -> bool:
        lower = name.lower()
        if not any(token in lower for token in ("sonuc", "output", "report", "rapor", "cikti")):
            return False
        escaped = re.escape(name)
        return bool(
            re.search(
                rf"\b{escaped}\b.*\b(?:yaz\w*|write\w*|output|rapor)\b|\b(?:yaz\w*|write\w*|output|rapor)\b.*\b{escaped}\b",
                assignment_brief,
                re.IGNORECASE,
            )
        )

    for name in _candidate_names(source_code, assignment_brief):
        escaped = re.escape(name)
        if name in read_names or _is_written(name) or _looks_like_output_target(name):
            continue
        if not re.search(rf"\b{escaped}\b", source_code, re.IGNORECASE):
            continue
        if re.search(rf"\b(?:oku\w*|read\w*|girdi|input)\b.*\b{escaped}\b|\b{escaped}\b.*\b(?:oku\w*|read\w*|girdi|input)\b", assignment_brief, re.IGNORECASE):
            _remember(name)

    return read_names


def infer_sandbox_files(*, assignment_brief: str, source_code: str) -> list[dict[str, str]]:
    """Return [{name, content}, ...] for input file paths referenced in student code."""
    names = _paths_opened_for_read(source_code, assignment_brief)
    if not names:
        return []

    files: list[dict[str, str]] = []
    for name in names:
        files.append({"name": name, "content": _default_content(name)})
    return files
