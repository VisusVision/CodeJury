from __future__ import annotations


class SandboxUnavailableError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        detail: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.retryable = retryable

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
