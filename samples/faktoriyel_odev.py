"""
Örnek teslim: n faktöriyeli — fonksiyon adı faktoriyel, tek pozitif tam sayı (n >= 1).
"""


def faktoriyel(n: int) -> int:
    if not isinstance(n, int) or n < 1:
        raise ValueError("n pozitif bir tam sayı olmalıdır (n >= 1).")
    sonuc = 1
    for i in range(2, n + 1):
        sonuc *= i
    return sonuc


def main() -> None:
    girdi = input("Pozitif bir tam sayı girin (n): ").strip()
    try:
        n = int(girdi)
    except ValueError:
        print("Geçerli bir tam sayı girilmedi.")
        return
    try:
        sonuc = faktoriyel(n)
    except ValueError as e:
        print(e)
        return
    print(f"faktoriyel({n}) = {sonuc}")


if __name__ == "__main__":
    main()
