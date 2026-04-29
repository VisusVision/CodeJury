"""
Uyumsuz ornek: Yayinci, kutuphane, kitap listeleri, kalitim veya bilesim yok.
Sadece sayisal islemler yapan basit bir script.
"""


def ortalama_hesapla(sayilar: list[int]) -> float:
    if not sayilar:
        return 0.0
    return sum(sayilar) / len(sayilar)


def en_buyuk_fark(sayilar: list[int]) -> int:
    if len(sayilar) < 2:
        return 0
    return max(sayilar) - min(sayilar)


def sirali_ciftleri_bul(sayilar: list[int]) -> list[int]:
    return sorted([sayi for sayi in sayilar if sayi % 2 == 0])


def main() -> None:
    notlar = [80, 45, 90, 72, 66]
    print("Ortalama:", ortalama_hesapla(notlar))
    print("En buyuk fark:", en_buyuk_fark(notlar))
    print("Cift sayilar:", sirali_ciftleri_bul(notlar))


if __name__ == "__main__":
    main()
