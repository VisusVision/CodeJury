"""API konfigurasyon istemcisi odevi icin alakasiz teslim."""


def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


print(fibonacci(8))
