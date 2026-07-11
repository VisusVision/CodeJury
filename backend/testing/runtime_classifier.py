from __future__ import annotations

import re
from dataclasses import dataclass

from backend.testing.contracts import RawCaseResult

_RUNTIME_ERROR_TYPES = (
    "ZeroDivisionError",
    "IndexError",
    "KeyError",
    "TypeError",
    "ValueError",
    "FileNotFoundError",
    "RuntimeError",
)

_ERROR_MESSAGES_TR: dict[str, str] = {
    "Timeout": "Program zaman aşımına uğradı.",
    "MemoryExceeded": "Program bellek sınırını aştı.",
    "CompilationError": "Program derlenemedi.",
    "ExitMismatch": "Program beklenmeyen çıkış kodu ile sonlandı.",
    "ZeroDivisionError": "Program sıfıra bölme hatası verdi.",
    "IndexError": "Program liste indeks aşımı hatası verdi.",
    "KeyError": "Program sözlükte bulunmayan anahtar hatası verdi.",
    "TypeError": "Program tip uyumsuzluğu hatası verdi.",
    "ValueError": "Program geçersiz değer hatası verdi.",
    "FileNotFoundError": "Program dosya bulunamadı hatası verdi.",
    "RuntimeError": "Program çalışma zamanı hatası verdi.",
    "UnknownRuntimeError": "Program bilinmeyen bir çalışma zamanı hatası verdi.",
}


@dataclass(frozen=True)
class RuntimeClassification:
    error_type: str
    error_message_tr: str


def _classify_stderr(stderr: str) -> RuntimeClassification | None:
    for error_type in _RUNTIME_ERROR_TYPES:
        if re.search(rf"\b{re.escape(error_type)}\b", stderr):
            return RuntimeClassification(
                error_type=error_type,
                error_message_tr=_ERROR_MESSAGES_TR[error_type],
            )
    if stderr.strip():
        return RuntimeClassification(
            error_type="UnknownRuntimeError",
            error_message_tr=_ERROR_MESSAGES_TR["UnknownRuntimeError"],
        )
    return None


def classify_runtime(raw: RawCaseResult) -> RuntimeClassification | None:
    if raw.timed_out:
        return RuntimeClassification(
            error_type="Timeout",
            error_message_tr=_ERROR_MESSAGES_TR["Timeout"],
        )
    if raw.memory_exceeded:
        return RuntimeClassification(
            error_type="MemoryExceeded",
            error_message_tr=_ERROR_MESSAGES_TR["MemoryExceeded"],
        )
    if not raw.compile_success:
        return RuntimeClassification(
            error_type="CompilationError",
            error_message_tr=_ERROR_MESSAGES_TR["CompilationError"],
        )
    if raw.actual_exit_code != 0:
        stderr_classification = _classify_stderr(raw.actual_stderr)
        if stderr_classification is not None:
            return stderr_classification
        return RuntimeClassification(
            error_type="ExitMismatch",
            error_message_tr=_ERROR_MESSAGES_TR["ExitMismatch"],
        )
    return _classify_stderr(raw.actual_stderr)
