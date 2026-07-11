"""Deterministic assignment difficulty normalization and inference."""

from __future__ import annotations

from backend.testing.contracts import AssignmentDifficulty

_VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})

_COMPLEXITY_KEYWORDS: tuple[str, ...] = (
    "çok aşamalı",
    "modüler",
    "kapsamlı",
    "mimari",
    "api",
    "veritabanı",
    "eşzamanlı",
    "karmaşık",
    "gelişmiş",
    "paralel",
    "dağıtık",
    "optimizasyon",
    "çoklu",
    "asenkron",
    "concurrent",
    "database",
    "architecture",
)

_SIMPLE_KEYWORDS: tuple[str, ...] = (
    "basit",
    "temel",
    "kolay",
    "toplam",
    "merhaba",
    "hello",
    "iki sayi",
    "iki sayı",
)


def normalize_difficulty(raw: str | None) -> AssignmentDifficulty:
    value = str(raw or "medium").strip().lower()
    if value in _VALID_DIFFICULTIES:
        return value  # type: ignore[return-value]
    return "medium"


def infer_assignment_difficulty(
    title: str,
    description: str,
    rubric: list[dict],
) -> AssignmentDifficulty:
    combined = f"{title} {description}".lower()
    score = len(combined) // 12
    score += len(rubric) * 4

    for keyword in _COMPLEXITY_KEYWORDS:
        if keyword in combined:
            score += 6

    for keyword in _SIMPLE_KEYWORDS:
        if keyword in combined:
            score -= 4

    if score <= 4:
        return "easy"
    if score <= 18:
        return "medium"
    return "hard"
