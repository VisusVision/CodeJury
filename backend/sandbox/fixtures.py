"""Infer minimal sandbox fixture files for file-based student submissions."""

from __future__ import annotations

import re
from pathlib import PurePosixPath


_CSV_PATH_RE = re.compile(
    r"""Path\s*\(\s*['"]([^'"]+\.csv)['"]\s*\)|open\s*\(\s*['"]([^'"]+\.csv)['"]""",
    re.IGNORECASE,
)
_PATH_ASSIGN_RE = re.compile(
    r"""(\w+)\s*=\s*Path\s*\(\s*['"]([^'"]+\.csv)['"]\s*\)""",
    re.IGNORECASE,
)


def _default_csv_content(filename: str) -> str:
    lower = filename.lower()
    if any(token in lower for token in ("ogrenci", "score", "not", "input", "grade")):
        return "name,score\nAyse,88\nMehmet,42\n"
    return "name,value\nsample,1\n"


def _csv_paths_opened_for_read(source_code: str) -> list[str]:
    """Collect CSV filenames that student code reads (skip write-only outputs)."""
    read_names: list[str] = []

    def _remember(raw: str) -> None:
        name = PurePosixPath(raw).name
        if name and name not in read_names:
            read_names.append(name)

    for var, raw_path in _PATH_ASSIGN_RE.findall(source_code):
        if re.search(rf"{re.escape(var)}\.open\s*\(\s*['\"]r", source_code, re.IGNORECASE):
            _remember(raw_path)

    for match in _CSV_PATH_RE.finditer(source_code):
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
        if re.search(rf"open\s*\(\s*['\"]{escaped}['\"]\s*\)", source_code) and not re.search(
            rf"open\s*\(\s*['\"]{escaped}['\"]\s*,\s*['\"]w",
            source_code,
            re.IGNORECASE,
        ):
            _remember(raw_path)

    return read_names


def infer_sandbox_files(*, assignment_brief: str, source_code: str) -> list[dict[str, str]]:
    """Return [{name, content}, ...] for CSV input paths referenced in student code."""
    del assignment_brief  # reserved for future brief-driven fixture parsing
    names = _csv_paths_opened_for_read(source_code)
    if not names:
        return []

    files: list[dict[str, str]] = []
    for name in names:
        files.append({"name": name, "content": _default_csv_content(name)})
    return files
