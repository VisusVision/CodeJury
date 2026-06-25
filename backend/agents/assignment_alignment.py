"""
Ödev/rubrik metni ile kaynak arasında yalnızca genel, domain-bağımsız heuristikler (LLM olmadan).

Kapsam alakası / 'alakasız teslim' değerlendirmesi `task_relevance` (LLM) ile yapılır; bu modül
Ollama kapalıyken veya çok uç durumlarda destekler.
"""

from __future__ import annotations

import ast
from typing import Any

BRIEF_MIN_LEN = 32

# Belirgin görev tanımı varken neredeyse boş teslim (LLM öncesi ipucu)
_MIN_SUBSTANTIVE_CODE_CHARS = 28


def _source_without_comments_and_docstrings(source: str) -> str:
    """Yorum ve modül/docstring satırlarını çıkarır; kaba 'içerik var mı' sayımı için."""
    text = (source or "").lstrip("\ufeff")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        lines = [
            line
            for line in text.splitlines()
            if not line.lstrip().startswith("#")
        ]
        return "\n".join(lines)

    docstring_lines: set[int] = set()
    docstring_carriers = (
        ast.Module,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )
    for node in ast.walk(tree):
        if not isinstance(node, docstring_carriers):
            continue
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and hasattr(first, "lineno")
        ):
            start = int(first.lineno)
            end = int(getattr(first, "end_lineno", start))
            docstring_lines.update(range(start, end + 1))

    kept: list[str] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if idx in docstring_lines:
            continue
        if line.lstrip().startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _rubric_criteria_text(rubric_criteria: list[dict[str, Any]] | None) -> str:
    """Öğretmen rubriğindeki satır adı + açıklamalarını tek metinde birleştirir."""
    if not rubric_criteria:
        return ""
    chunks: list[str] = []
    for row in rubric_criteria:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "") or "").strip()
        desc = str(row.get("description", "") or "").strip()
        if name:
            chunks.append(name)
        if desc:
            chunks.append(desc)
    return "\n".join(chunks).strip()


def compute_brief_code_alignment(
    brief: str,
    source: str,
    *,
    rubric_criteria: list[dict[str, Any]] | None = None,
) -> tuple[float, list[str]]:
    """
    0..1 çarpanı: çoğu durumda 1.0 (nötr). Domain'e özel anahtar kelime eşleştirmesi yok.

    - Ödev + rubrik metni yeterince uzun değilse: görev tanımı yok sayılır → 1.0 (LLM de atlar).
    - Görev tanımı varken kaynak neredeyse boşsa: hafif ceza (tam alakasızlık yine LLM'de).
    """
    b = (brief or "").strip()
    s = source or ""
    rub_blob = _rubric_criteria_text(rubric_criteria)
    combined = "\n".join(x for x in (b, rub_blob) if x).strip()
    if len(combined) < BRIEF_MIN_LEN:
        return 1.0, []

    body = _source_without_comments_and_docstrings(s)
    compact = "".join(body.split())
    if len(compact) < _MIN_SUBSTANTIVE_CODE_CHARS:
        return 0.28, ["submission_nearly_empty"]

    from backend.agents.task_relevance import obvious_cross_domain_mismatch

    if obvious_cross_domain_mismatch(combined.lower(), body.lower()):
        return 0.15, ["cross_domain_mismatch"]

    return 1.0, []


def alignment_summary_tr(reasons: list[str]) -> str:
    if not reasons:
        return ""
    prefix = (
        "Bu teslim, ödev ve rubrikte tanımlanan görevle uyumlu görünmüyor; alakasız veya yanlış "
        "dosya yüklenmiş olabilir."
    )
    labels = {
        "submission_nearly_empty": "Teslim edilen kaynak neredeyse boş veya yetersiz; görev karşılanmıyor.",
        "cross_domain_mismatch": "Teslim, ödevin veri/dosya analizi konusundan farklı bir alana (ör. playlist, UI) ait görünüyor.",
        "llm_task_relevance_off_topic": "Görev uyumu: Kod, ödev konusu ve rubrikle örtüşmüyor (alakasız teslim).",
        "llm_task_not_fulfilled": "Görev uyumu: Kod, ödevin istenen çıktılarını önemli ölçüde karşılamıyor.",
        "llm_low_task_fit": "Görev uyumu: Kod ile ödev beklentisi arasında ciddi uyumsuzluk var.",
    }
    parts = [labels.get(r, r) for r in reasons]
    return prefix + " " + " ".join(parts)
