"""
Veri Guzellestirme ve Temizleme odevi icin alakasiz ornek.

Bu kod bir sayi tahmin oyunudur. SQLite tablosu, POST/PUT endpointleri,
veri temizleme veya metin guzellestirme akisi icermez.
"""

from __future__ import annotations

import random


def get_guess(prompt: str = "Tahmininiz: ") -> int:
    while True:
        raw = input(prompt).strip()
        try:
            return int(raw)
        except ValueError:
            print("Lutfen sayi girin.")


def play_game(lower: int = 1, upper: int = 100, max_attempts: int = 7) -> None:
    secret = random.randint(lower, upper)
    print(f"{lower}-{upper} arasinda tuttugum sayiyi bulmaya calisin.")

    for attempt in range(1, max_attempts + 1):
        guess = get_guess(f"{attempt}. tahmin: ")
        if guess == secret:
            print("Tebrikler, dogru bildiniz!")
            return
        if guess < secret:
            print("Daha buyuk bir sayi deneyin.")
        else:
            print("Daha kucuk bir sayi deneyin.")

    print(f"Hakkiniz bitti. Dogru sayi: {secret}")


def main() -> None:
    print("Mini Sayi Tahmin Oyunu")
    play_game()


if __name__ == "__main__":
    main()
