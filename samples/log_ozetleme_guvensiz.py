"""
Sistem Log Ozetleme odevi - guvensiz ornek.

Islevsel olarak log satirlarini sayar; ancak kullanicidan gelen filtre ifadesini
eval() ile calistirdigi icin guvenlik riski barindirir.
"""

from __future__ import annotations

import re
from pathlib import Path


LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} .* \[(INFO|WARN|ERROR|CRITICAL)\] ")


def satirlari_yukle(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def guvensiz_filtre(line: str, filtre: str) -> bool:
    # Bilerek guvensiz: kullanici ifadesi dogrudan eval ediliyor.
    return bool(eval(filtre, {}, {"line": line}))


def main() -> int:
    log_path = Path("sample.log")
    if not log_path.exists():
        print("[HATA] sample.log bulunamadi")
        return 1

    filtre = input("Filtre ifadesi (ornek: 'ERROR' in line): ").strip() or "'ERROR' in line"
    lines = satirlari_yukle(log_path)
    matched = 0
    malformed = 0

    for line in lines:
        if not LINE_RE.match(line):
            malformed += 1
            continue
        if guvensiz_filtre(line, filtre):
            matched += 1

    print("Toplam:", len(lines))
    print("Eslesen:", matched)
    print("Bozuk:", malformed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
