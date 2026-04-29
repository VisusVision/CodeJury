class Stack:
    """A simple stack implementation."""
    def __init__(self):
        self._data = []
    def push(self, item) -> None:
        """Push an item."""
        self._data.append(item)
    def pop(self):
        """Remove and return top item."""
        if not self._data:
            raise IndexError("Stack is empty")
        return self._data.pop()
    def peek(self):
        """Return top item without removing."""
        if not self._data:
            raise IndexError("Stack is empty")
        return self._data[-1]
    def is_empty(self) -> bool:
        """Return True if empty."""
        return len(self._data) == 0
    def __len__(self): return len(self._data)

def is_balanced(expr: str) -> bool:
    """Check bracket balance."""
    stack = Stack()
    pairs = {")": "(", "]": "[", "}": "{"}
    for ch in expr:
        if ch in pairs.values(): stack.push(ch)
        elif ch in pairs:
            if stack.is_empty() or stack.peek() != pairs[ch]: return False
            stack.pop()
    return stack.is_empty()

if __name__ == "__main__":
    s = Stack()
    for v in [10, 20, 30]: s.push(v)
    print("Size:", len(s))
    print("Pop:", s.pop())
    for expr, exp in [("([]{})", True), ("([)]", False), ("{[()]}", True)]:
        ok = is_balanced(expr)
        print(f"  {'OK' if ok==exp else 'FAIL'}  '{expr}' -> {ok}")
