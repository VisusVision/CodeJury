"""Assignment difficulty normalization and inference unit tests (RED phase)."""

from __future__ import annotations

import pytest

from backend.testing.difficulty import infer_assignment_difficulty, normalize_difficulty


def test_default_difficulty_is_medium() -> None:
    assert normalize_difficulty(None) == "medium"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("easy", "easy"),
        ("medium", "medium"),
        ("hard", "hard"),
        ("Easy", "easy"),
        ("  hard  ", "hard"),
    ],
)
def test_normalize_difficulty_accepts_valid_values(raw: str, expected: str) -> None:
    assert normalize_difficulty(raw) == expected


def test_normalize_difficulty_rejects_invalid_falls_back_to_medium() -> None:
    assert normalize_difficulty("invalid_value") == "medium"


def test_inference_is_deterministic_and_never_uses_student_code() -> None:
    kwargs = {
        "title": "Çok aşamalı veri işleme sistemi",
        "description": "CSV, hata durumları, modüler tasarım ve kapsamlı testler",
        "rubric": [{"name": "Mimari"}, {"name": "Testler"}],
    }
    assert infer_assignment_difficulty(**kwargs) == infer_assignment_difficulty(**kwargs)
    assert "student_code" not in infer_assignment_difficulty.__code__.co_varnames


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "title": "Merhaba",
            "description": "Basit bir program yazin.",
            "rubric": [],
        },
        {
            "title": "Çok aşamalı veri işleme sistemi",
            "description": "CSV, hata durumları, modüler tasarım ve kapsamlı testler",
            "rubric": [{"name": f"Kriter {i}"} for i in range(8)],
        },
        {
            "title": "Orta seviye odev",
            "description": "Dosya okuma ve temel istatistik hesaplama.",
            "rubric": [{"name": "Dogruluk"}, {"name": "Kod kalitesi"}],
        },
    ],
)
def test_inference_returns_only_valid_difficulty_literal(kwargs: dict) -> None:
    result = infer_assignment_difficulty(**kwargs)
    assert result in {"easy", "medium", "hard"}


def test_inference_short_simple_assignment_is_easier_than_long_complex_one() -> None:
    order = {"easy": 0, "medium": 1, "hard": 2}
    simple = infer_assignment_difficulty(
        title="Toplam",
        description="Iki sayiyi topla.",
        rubric=[],
    )
    complex_ = infer_assignment_difficulty(
        title="Çok aşamalı veri işleme sistemi",
        description="CSV, hata durumları, modüler tasarım ve kapsamlı testler",
        rubric=[{"name": f"Kriter {i}"} for i in range(10)],
    )
    assert order[complex_] >= order[simple]
