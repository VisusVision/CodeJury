"""Banka hesabi - OOP odevle uyumlu cozum."""

from __future__ import annotations


class InsufficientFundsError(Exception):
    """Bakiye yetersiz oldugunda firlatilir."""


class BankAccount:
    def __init__(self, owner: str, balance: float = 0.0) -> None:
        self.owner = owner
        self._balance = balance

    @property
    def balance(self) -> float:
        return self._balance

    def deposit(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("Yatirilacak tutar pozitif olmalidir")
        self._balance += amount

    def withdraw(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("Cekilecek tutar pozitif olmalidir")
        if amount > self._balance:
            raise InsufficientFundsError("Yetersiz bakiye")
        self._balance -= amount


def main() -> None:
    account = BankAccount("Ali", 100.0)
    account.deposit(50)
    account.withdraw(30)
    print(f"{account.owner} bakiye: {account.balance}")


if __name__ == "__main__":
    main()
