"""Guvenlik riskli: eval ile stack islemi (Stack odevine konu uyumlu ama tehlikeli)."""

from __future__ import annotations


class UnsafeStack:
    def __init__(self) -> None:
        self._items: list[str] = []

    def push(self, raw: str) -> None:
        # Tehlikeli: kullanici girdisini eval ile isler
        value = eval(raw)
        self._items.append(str(value))

    def pop(self) -> str:
        if not self._items:
            raise IndexError("bos stack")
        return self._items.pop()

    def is_empty(self) -> bool:
        return not self._items


def main() -> None:
    stack = UnsafeStack()
    stack.push("__import__('os').system('echo pwned')")
    print(stack.pop())


if __name__ == "__main__":
    main()
