"""Kelime frekans analizi - metin CLI odevi icin uygun ornek."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

TOP_N = 10
PUNCTUATION = ".,!?;:\\\"'()[]{} "


def read_text(input_path: Path) -> str:
    with input_path.open("r", encoding="utf-8") as handle:
        return handle.read()


def word_frequencies(text: str) -> Counter:
    words = []
    for raw in text.split():
        cleaned = raw.strip(PUNCTUATION).lower()
        if cleaned:
            words.append(cleaned)
    return Counter(words)


def format_report(freqs: Counter, top_n: int) -> list[str]:
    return [f"{word}: {count}" for word, count in freqs.most_common(top_n)]


def main() -> None:
    if len(sys.argv) < 2:
        print("Kullanim: python kelime_frekans.py <dosya>")
        return
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Dosya bulunamadi: {path}")
        return
    freqs = word_frequencies(read_text(path))
    for line in format_report(freqs, TOP_N):
        print(line)


if __name__ == "__main__":
    main()
