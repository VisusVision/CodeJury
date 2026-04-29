"""
Hava Durumu Hesaplayici
Sicaklik birim cevirimi ve basit hava durumu sinifi.
Bu kod kitap/kutuphane/kiralama ile hicbir alakasi yoktur.
"""

import math


def fahrenheit_to_celsius(f: float) -> float:
    """Fahrenheit'i Celsius'a cevirir."""
    return (f - 32) * 5 / 9


def celsius_to_fahrenheit(c: float) -> float:
    """Celsius'i Fahrenheit'a cevirir."""
    return c * 9 / 5 + 32


def ruzgar_serinligi(sicaklik_c: float, ruzgar_kmh: float) -> float:
    """Ruzgar serinligini (wind chill) hesaplar."""
    if sicaklik_c > 10 or ruzgar_kmh < 4.8:
        return sicaklik_c
    return (
        13.12
        + 0.6215 * sicaklik_c
        - 11.37 * (ruzgar_kmh ** 0.16)
        + 0.3965 * sicaklik_c * (ruzgar_kmh ** 0.16)
    )


def daire_alani(yaricap: float) -> float:
    """Verilen yaricapli dairenin alanini hesaplar."""
    if yaricap < 0:
        raise ValueError("Yaricap negatif olamaz")
    return math.pi * yaricap ** 2


def fibonacci(n: int) -> list[int]:
    """Ilk n fibonacci sayisini uretir."""
    seri = [0, 1]
    for _ in range(2, n):
        seri.append(seri[-1] + seri[-2])
    return seri[:n]


def asal_mi(sayi: int) -> bool:
    """Verilen sayinin asal olup olmadigini kontrol eder."""
    if sayi < 2:
        return False
    for i in range(2, int(math.sqrt(sayi)) + 1):
        if sayi % i == 0:
            return False
    return True


if __name__ == "__main__":
    print("32 F =", fahrenheit_to_celsius(32), "C")
    print("100 C =", celsius_to_fahrenheit(100), "F")
    print("Wind chill (5C, 30kmh):", round(ruzgar_serinligi(5, 30), 2))
    print("Daire alani r=3:", round(daire_alani(3), 2))
    print("Ilk 10 Fibonacci:", fibonacci(10))
    print("17 asal mi?:", asal_mi(17))
    print("Asal sayilar 1-30:", [n for n in range(1, 31) if asal_mi(n)])
