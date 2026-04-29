"""
Ödev metni ile kaynak kod arasında kaba uyum sinyali (LLM olmadan).

Amaç: Kütüphane / OOP vb. bir ödevde yalnızca fibonacci-asal gibi alakasız ama
çalışan kodların yapay yüksek 'fonksiyonellik' puanını engellemek.
"""

from __future__ import annotations

import ast
import re


def _fold(text: str) -> str:
    t = (text or "").lower()
    for a, b in (
        ("ı", "i"),
        ("ğ", "g"),
        ("ü", "u"),
        ("ş", "s"),
        ("ö", "o"),
        ("ç", "c"),
    ):
        t = t.replace(a, b)
    return t


def _source_without_comments_and_docstrings(source: str) -> str:
    """Domain keyword checks should not be fooled by comments/docstrings like 'not a library app'."""
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
    # Yalnizca docstring tasiyabilen dugumlere bak: Module / def / async def / class.
    # Diger dugumlerde (ornegin ast.Lambda) `body` liste olmayabilir veya farkli
    # bir AST nesnesi olabilir; subscript hatasini onler.
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


BRIEF_MIN_LEN = 32

# Ödev metninde geçince ilgili domain aranır
_LIBRARY_BRIEF = (
    "kutuphane",
    "kutuphani",
    "library",
    "kitap",
    "kitaplik",
    "book",
    "odunc",
    "odunc ver",
    "iade",
    "uye",
    "üye",
    "katalog",
    "catalog",
    "isbn",
    "rafta",
)
_LIBRARY_CODE = _LIBRARY_BRIEF + (
    "kitap",
    "kutuphane",
    "library",
    "book",
    "borrow",
    "checkout",
    "return_book",
    "odunc_ver",
    "uye_ekle",
)

_PUBLISHER_BRIEF = (
    "yayinci",
    "yayincisi",
    "yayimci",
    "yayimcisi",
    "publisher",
    "publishing",
)
_PUBLISHER_CODE = _PUBLISHER_BRIEF + (
    "kitapyayincisi",
    "kitap_yayincisi",
    "yayinci_adi",
    "kendi_kitaplari",
    "iliskili_yayincilar",
    "baska_yayincidan",
)

_OOP_BRIEF = (
    "sinif ",
    " sinif",
    "siniflar",
    "sinifi",
    "nesne",
    "oop",
    " kalitim",
    "kalıtım",
    "miras",
    "kapsul",
    "arayuz",
    "arayüz",
    "polimorf",
    " soyut ",
)
_MATH_TOY = (
    "fibonacci",
    "fib(",
    "def fib",
    "asal_mi",
    "is_prime",
    "prime",
    "factorial",
    "factoriyel",
    "gcd(",
    "ebob",
)


def compute_brief_code_alignment(brief: str, source: str) -> tuple[float, list[str]]:
    """
    0..1 çarpanı: 1 = ceza yok / net brief yok; düşük = ödevle ciddi uyumsuzluk.
    İkinci dönüş: kısa açıklama etiketleri (log / rapor).
    """
    b = (brief or "").strip()
    s = source or ""
    if len(b) < BRIEF_MIN_LEN:
        return 1.0, []

    code_for_keywords = _source_without_comments_and_docstrings(s)
    bf, sf = _fold(b), _fold(code_for_keywords)

    reasons: list[str] = []

    brief_lib = any(k in bf for k in _LIBRARY_BRIEF)
    brief_oop = any(k in bf for k in _OOP_BRIEF)
    brief_publisher = any(k in bf for k in _PUBLISHER_BRIEF)
    class_defs = len(re.findall(r"^\s*class\s+\w+", code_for_keywords, re.MULTILINE))

    code_lib = any(k in sf for k in _LIBRARY_CODE)
    code_publisher = any(k in sf for k in _PUBLISHER_CODE)
    if not code_lib and class_defs > 0:
        if any(x in sf for x in ("kitap", "kutuphane", "library", "book", "uye", "member")):
            code_lib = True

    toy_math = any(k in sf for k in _MATH_TOY)

    factor = 1.0

    if brief_lib:
        if not code_lib:
            factor = 0.22
            if toy_math:
                factor = 0.14
            reasons.append("brief_kutuphane_kodda_yok")
        else:
            factor = min(factor, 0.92)
            if toy_math and class_defs < 2:
                factor = min(factor, 0.45)
                reasons.append("kutuphane_beklenirken_math_agirligi")

    if brief_publisher:
        if not code_publisher:
            factor = min(factor, 0.18)
            reasons.append("brief_yayinci_kodda_yok")
        elif class_defs < 2:
            factor = min(factor, 0.55)
            reasons.append("brief_yayinci_modeli_zayif")

    if brief_oop and class_defs < 1:
        factor *= 0.35
        reasons.append("brief_oop_sinif_yok")
    elif brief_oop and class_defs < 2 and brief_lib:
        factor *= 0.72
        reasons.append("brief_oop_az_sinif")

    if toy_math and brief_lib and not code_lib:
        reasons.append("math_toy_vs_library")

    return max(0.05, min(1.0, factor)), reasons


def alignment_summary_tr(reasons: list[str]) -> str:
    if not reasons:
        return ""
    labels = {
        "brief_kutuphane_kodda_yok": "Ödev metni kütüphane/kitap odaklı; kodda bu domain görünmüyor.",
        "brief_yayinci_kodda_yok": "Ödev metni KitapYayıncısı/yayıncı modeli istiyor; kodda yayıncı domaini görünmüyor.",
        "brief_yayinci_modeli_zayif": "Yayıncı modeli için sınıf ve ilişki yapısı zayıf kalıyor.",
        "kutuphane_beklenirken_math_agirligi": "Kütüphane ödevi beklenirken kod ağırlıklı olarak klasik matematik örneklerine benziyor.",
        "brief_oop_sinif_yok": "Ödev metni OOP/sınıf istiyor; kaynakta sınıf tanımı yok.",
        "brief_oop_az_sinif": "OOP ödevi için sınıf yapısı yetersiz kalabilir.",
        "math_toy_vs_library": "Fibonacci/asallık vb. ile kütüphane konusu örtüşmüyor.",
    }
    parts = [labels.get(r, r) for r in reasons]
    return " ".join(parts)
