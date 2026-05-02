"""
Sistem Log Ozetleme Odevi - Uygun cozum.

Gorev:
- Bir log dosyasini satir satir okuyup LEVEL bazli ozet cikarmak.
- Hata satirlarini ayri raporlamak.
- Dosya yok / bozuk satir gibi durumlari guvenli sekilde ele almak.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path


LOG_PATTERN = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[(?P<level>[A-Z]+)\]\s+(?P<msg>.+)$"
)


def parse_log_lines(lines: list[str]) -> tuple[Counter, list[str], int]:
    level_counts: Counter[str] = Counter()
    errors: list[str] = []
    malformed_count = 0

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = LOG_PATTERN.match(line)
        if not match:
            malformed_count += 1
            continue
        level = match.group("level")
        message = match.group("msg")
        level_counts[level] += 1
        if level in {"ERROR", "CRITICAL"}:
            errors.append(message)
    return level_counts, errors, malformed_count


def summarize_log_file(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Log dosyasi bulunamadi: {path}")
    if not path.is_file():
        raise ValueError(f"Log girdisi dosya olmali: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    levels, errors, malformed = parse_log_lines(lines)
    return {
        "total_lines": len(lines),
        "level_counts": dict(levels),
        "error_messages": errors,
        "malformed_lines": malformed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sistem log dosyasini ozetler.")
    parser.add_argument("log_file", help="Analiz edilecek log dosyasi yolu")
    args = parser.parse_args()

    try:
        result = summarize_log_file(Path(args.log_file))
    except (FileNotFoundError, ValueError) as exc:
        print(f"[HATA] {exc}")
        return 1

    print("Toplam satir:", result["total_lines"])
    print("Seviye sayaclari:", result["level_counts"])
    print("Bozuk satir sayisi:", result["malformed_lines"])
    print("Hata mesajlari:")
    for msg in result["error_messages"]:
        print("-", msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
