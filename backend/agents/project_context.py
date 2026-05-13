from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


_TURKISH_FOLD_MAP = str.maketrans({
    "ç": "c",
    "Ç": "C",
    "ğ": "g",
    "Ğ": "G",
    "ı": "i",
    "İ": "I",
    "ö": "o",
    "Ö": "O",
    "ş": "s",
    "Ş": "S",
    "ü": "u",
    "Ü": "U",
})

_STOPWORDS = {
    "odev",
    "ogrenci",
    "ogrenciler",
    "gelistirin",
    "gelistir",
    "yazin",
    "yaz",
    "olusturun",
    "olustur",
    "yoneten",
    "durumlari",
    "durumlar",
    "kayitlari",
    "kayit",
    "olsun",
    "icin",
    "ile",
    "ve",
    "veya",
    "bir",
    "tum",
    "olarak",
    "beklenen",
    "teslim",
    "proje",
    "program",
    "uygulama",
}

_IMPORTANT_SHORT_TERMS = {"api", "csv", "json", "cli", "sql", "ph", "ui", "log", "bst"}


@dataclass(frozen=True)
class ProjectContext:
    terms: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    io_formats: list[str] = field(default_factory=list)
    error_cases: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return ", ".join(self.terms[:12]) if self.terms else (
            "odevin somut varliklari, girdileri, ciktilari ve hata durumlari"
        )

    def prompt_block(self) -> str:
        parts = [f"Proje terimleri: {self.summary}."]
        if self.deliverables:
            parts.append(f"Beklenen teslimler: {', '.join(self.deliverables[:8])}.")
        if self.io_formats:
            parts.append(f"Girdi/cikti bicimleri: {', '.join(self.io_formats[:8])}.")
        if self.error_cases:
            parts.append(f"Hata/kenar durumlari: {', '.join(self.error_cases[:8])}.")
        if self.tech_stack:
            parts.append(f"Teknik baglam: {', '.join(self.tech_stack[:8])}.")
        return "\n".join(parts)


def fold_text(raw: str | None) -> str:
    text = str(raw or "").translate(_TURKISH_FOLD_MAP)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _append_unique(target: list[str], value: str) -> None:
    item = value.strip(" .,:;()[]{}'\"").lower()
    if item and item not in target:
        target.append(item)


def _rubric_text(rubric_criteria: list[dict[str, Any]] | None) -> str:
    rows: list[str] = []
    for row in rubric_criteria or []:
        if not isinstance(row, dict):
            continue
        rows.append(str(row.get("name", "") or ""))
        rows.append(str(row.get("description", "") or ""))
    return "\n".join(rows)


def build_project_context(
    title: str | None,
    description: str | None,
    rubric_criteria: list[dict[str, Any]] | None = None,
    *,
    term_limit: int = 12,
) -> ProjectContext:
    text = fold_text("\n".join(x for x in (title or "", description or "", _rubric_text(rubric_criteria)) if x))
    lower = text.lower()

    terms: list[str] = []
    for raw in re.findall(r"/[A-Za-z0-9_\-/]+|[A-Za-z0-9_]{2,}", text):
        term = raw.strip(" .,:;()[]{}'\"").lower()
        if not term or term in _STOPWORDS or term.isdigit():
            continue
        if len(term) < 4 and term not in _IMPORTANT_SHORT_TERMS:
            continue
        _append_unique(terms, term)
        if len(terms) >= term_limit:
            break

    deliverables: list[str] = []
    for marker, label in (
        ("endpoint", "endpointler"),
        ("api", "API"),
        ("rapor", "rapor"),
        ("dosya", "dosya islemleri"),
        ("csv", "CSV raporu"),
        ("json", "JSON yanitlari"),
        ("sinif", "siniflar"),
        ("class", "siniflar"),
        ("test", "testler"),
        ("cli", "CLI"),
        ("frontend", "arayuz"),
        ("react", "React arayuzu"),
    ):
        if marker in lower:
            _append_unique(deliverables, label)

    io_formats: list[str] = []
    for marker, label in (
        ("csv", "CSV"),
        ("json", "JSON"),
        ("dosya", "dosya"),
        ("endpoint", "HTTP endpoint"),
        ("api", "HTTP API"),
        ("komut", "komut satiri"),
        ("cli", "komut satiri"),
        ("rapor", "rapor ciktisi"),
    ):
        if marker in lower:
            _append_unique(io_formats, label)

    error_cases: list[str] = []
    for pattern, label in (
        (r"\bhata\w*\b", "hata durumlari"),
        (r"\bgecersiz\b", "gecersiz girdi"),
        (r"\bhatali\b", "hatali satir/deger"),
        (r"\bolmayan\b", "olmayan id/kayit"),
        (r"\bstokta olmayan\b", "stokta olmayan kaynak"),
        (r"\bgecikmis\b", "gecikmis islem"),
        (r"\bkenar\b", "kenar durumlar"),
    ):
        if re.search(pattern, lower):
            _append_unique(error_cases, label)

    tech_stack: list[str] = []
    for marker, label in (
        ("fastapi", "FastAPI"),
        ("flask", "Flask"),
        ("django", "Django"),
        ("sqlite", "SQLite"),
        ("react", "React"),
        ("python", "Python"),
        ("javascript", "JavaScript"),
        ("typescript", "TypeScript"),
        ("c++", "C++"),
        ("java", "Java"),
    ):
        if marker in lower:
            _append_unique(tech_stack, label)

    return ProjectContext(
        terms=terms,
        deliverables=deliverables,
        io_formats=io_formats,
        error_cases=error_cases,
        tech_stack=tech_stack,
    )
