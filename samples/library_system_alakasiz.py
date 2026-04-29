"""
Alakasiz ornek: kutuphane ile ilgisi yok — Fibonacci ve asal kontrol.
"""


def fib(n: int) -> int:
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def asal_mi(x: int) -> bool:
    if x < 2:
        return False
    for d in range(2, int(x**0.5) + 1):
        if x % d == 0:
            return False
    return True


def main() -> None:
    print("fib(10) =", fib(10))
    print("asal_mi(17) =", asal_mi(17))


if __name__ == "__main__":
    main()
