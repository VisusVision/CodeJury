"""Stack (LIFO) - odevle uyumlu cozum."""

from __future__ import annotations


class StackEmptyError(Exception):
    """Stack bosken pop/peek yapildiginda firlatilir."""


class Stack:
    def __init__(self) -> None:
        self._items: list[object] = []

    def push(self, item: object) -> None:
        self._items.append(item)

    def pop(self) -> object:
        if self.is_empty():
            raise StackEmptyError("Stack bos")
        return self._items.pop()

    def peek(self) -> object:
        if self.is_empty():
            raise StackEmptyError("Stack bos")
        return self._items[-1]

    def is_empty(self) -> bool:
        return len(self._items) == 0

    def __len__(self) -> int:
        return len(self._items)


def main() -> None:
    stack = Stack()
    stack.push(1)
    stack.push(2)
    print(stack.peek())
    print(stack.pop())
    print(len(stack))


if __name__ == "__main__":
    main()
