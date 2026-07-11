"""Fixture policy validation tests (RED phase)."""

from __future__ import annotations

import pytest

from backend.testing.contracts import TestFixture
from backend.testing.fixture_policy import FixturePolicyError, validate_case_fixtures


def test_fixture_policy_accepts_nested_utf8_text() -> None:
    result = validate_case_fixtures(
        [TestFixture(name="data/input.csv", content="id,value\n1,2\n")]
    )
    assert result[0].name == "data/input.csv"


@pytest.mark.parametrize("suffix", [".txt", ".csv", ".tsv", ".json"])
def test_fixture_policy_accepts_all_allowed_extensions(suffix: str) -> None:
    result = validate_case_fixtures(
        [TestFixture(name=f"data/input{suffix}", content="ok")]
    )
    assert result[0].name == f"data/input{suffix}"


@pytest.mark.parametrize(
    "name",
    ["../secret.txt", "..\\secret.txt", "/tmp/a.txt", "solution.py", "a.exe"],
)
def test_fixture_policy_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(FixturePolicyError):
        validate_case_fixtures([TestFixture(name=name, content="x")])


def test_fixture_policy_rejects_nul_byte_in_name() -> None:
    with pytest.raises(FixturePolicyError):
        validate_case_fixtures([TestFixture(name="data\x00evil.txt", content="x")])


def test_fixture_policy_enforces_per_file_bytes() -> None:
    with pytest.raises(FixturePolicyError):
        validate_case_fixtures(
            [TestFixture(name="big.txt", content="x" * (64 * 1024 + 1))]
        )


def test_fixture_policy_enforces_total_bytes() -> None:
    # Each file is under 64 KiB (32768 ASCII bytes), but 9 files exceed 256 KiB total.
    with pytest.raises(FixturePolicyError):
        validate_case_fixtures(
            [
                TestFixture(name=f"{index}.txt", content="x" * 32768)
                for index in range(9)
            ]
        )


def test_fixture_policy_enforces_max_file_count() -> None:
    with pytest.raises(FixturePolicyError):
        validate_case_fixtures(
            [TestFixture(name=f"{index}.txt", content="x") for index in range(11)]
        )


def test_fixture_policy_rejects_absolute_posix_path() -> None:
    with pytest.raises(FixturePolicyError):
        validate_case_fixtures([TestFixture(name="/etc/passwd", content="x")])


def test_fixture_policy_rejects_disallowed_suffix_case_insensitive() -> None:
    with pytest.raises(FixturePolicyError):
        validate_case_fixtures([TestFixture(name="virus.EXE", content="x")])
