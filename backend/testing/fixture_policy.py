from __future__ import annotations

from pathlib import PurePosixPath

from backend.testing.contracts import TestFixture

ALLOWED_SUFFIXES = frozenset({".txt", ".csv", ".tsv", ".json"})
MAX_FILES_PER_CASE = 10
MAX_FILE_BYTES = 64 * 1024
MAX_CASE_BYTES = 256 * 1024


class FixturePolicyError(ValueError):
    pass


def validate_case_fixtures(files: list[TestFixture]) -> list[TestFixture]:
    if len(files) > MAX_FILES_PER_CASE:
        raise FixturePolicyError(
            f"case has {len(files)} fixture files; maximum is {MAX_FILES_PER_CASE}"
        )

    total_bytes = 0
    for fixture in files:
        if "\\" in fixture.name or "\x00" in fixture.name:
            raise FixturePolicyError(f"invalid fixture name: {fixture.name!r}")

        path = PurePosixPath(fixture.name)
        if path.is_absolute():
            raise FixturePolicyError(f"absolute fixture path not allowed: {fixture.name!r}")
        if ".." in path.parts:
            raise FixturePolicyError(f"path traversal not allowed: {fixture.name!r}")

        suffix = path.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise FixturePolicyError(
                f"disallowed fixture suffix {suffix!r} for {fixture.name!r}"
            )

        file_bytes = len(fixture.content.encode("utf-8"))
        if file_bytes > MAX_FILE_BYTES:
            raise FixturePolicyError(
                f"fixture {fixture.name!r} exceeds per-file byte limit ({file_bytes} > {MAX_FILE_BYTES})"
            )

        total_bytes += file_bytes
        if total_bytes > MAX_CASE_BYTES:
            raise FixturePolicyError(
                f"case fixtures exceed total byte limit ({total_bytes} > {MAX_CASE_BYTES})"
            )

    return files


def validate_test_fixture(fixture: TestFixture) -> TestFixture:
    return validate_case_fixtures([fixture])[0]
