"""
Sistem Log Ozetleme odevi icin alakasiz ornek.

Bu kod bir mini not ortalamasi hesaplayicisidir; log dosyasi okumaz,
regex ile log satiri ayrisimi yapmaz ve seviye bazli rapor uretmez.
"""

from __future__ import annotations


def ortalama_hesapla(notlar: list[float]) -> float:
    if not notlar:
        raise ValueError("Not listesi bos olamaz.")
    return sum(notlar) / len(notlar)


def harf_notu(ortalama: float) -> str:
    if ortalama >= 90:
        return "AA"
    if ortalama >= 80:
        return "BA"
    if ortalama >= 70:
        return "BB"
    if ortalama >= 60:
        return "CB"
    if ortalama >= 50:
        return "CC"
    return "FF"


def main() -> None:
    notlar = [78, 92, 85, 61, 74]
    ort = ortalama_hesapla(notlar)
    print("Ortalama:", round(ort, 2))
    print("Harf notu:", harf_notu(ort))


if __name__ == "__main__":
    main()
