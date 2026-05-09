"""
LLM tabanlı görev uyumu: ödev + rubrik ile yüklenen kodun **aynı görevi** hedefleyip hedeflemediği.

Alan (domain) spesifik kurallar yok; yeni projeler ve rubrikler için genel amaçlı değerlendirmedir.

Programatik `compute_brief_code_alignment` yalnızca nötr / neredeyse boş teslim ipucu verir; asıl uyum
burada belirlenir ve `merge_task_alignment` ile birleşir.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.agents.assignment_alignment import (
    BRIEF_MIN_LEN,
    _rubric_criteria_text,
    _source_without_comments_and_docstrings,
)
from backend.agents.base import build_llm_user_suffix
from backend.agents.json_output_schema import TASK_RELEVANCE_OUTPUT_SCHEMA, collect_validation_messages
from backend.core.config import settings
from backend.llm.ollama_client import chat_json

logger = logging.getLogger(__name__)

_TASK_RELEVANCE_SYSTEM = """\
You are a strict grading assistant. The instructor brief and rubric rows together define ONE assignment.
The student submitted source code. Your job is to judge whether this submission is actually aimed at
that assignment — for ANY subject (algorithms, OOP, web, data structures, games, etc.).

Output JSON fields:
- relevance_factor: float 0–1. Use 1.0 only when the code clearly implements what the assignment asks.
  Use 0.05–0.22 when the code is clearly a different project / wrong topic / unrelated file (wrong stack,
  wrong problem, or unrelated codebase). Middle values only for partial or ambiguous fit.
- off_topic: true if the code addresses a different problem than the assignment (not a minor bug).
- student_fulfills_assignment: true only if the code substantively meets the described deliverables.
- confidence: optional 0–1.
- explanation: 2–4 sentences in the report language. If off_topic or very low relevance, you MUST
  clearly state that the submission does not match the assignment (e.g. Turkish: «alakasız teslim»,
  «ödevle bağlantısı yok», «yanlış ödev / yanlış proje yüklendi»).
- submission_domain_guess: short neutral label of what the code does (e.g. "CRUD API", "linked list").
- task_domain_guess: short neutral label of what the assignment requires.

Rules:
- Compare **only** the stated assignment (brief + rubric) to the code. Do not assume a favorite domain.
- Do NOT mark a submission off-topic just because it lacks tests, comments, type hints, perfect error
  handling, or a preferred framework. Those are quality/completeness issues, not topic mismatch.
- If the code implements the core data model, algorithm, API shape, CLI shape, or main functions requested
  by the brief, keep off_topic false and use a middle relevance_factor for incomplete work.
- Set off_topic true only for a different problem/domain, wrong file, empty placeholder, or a submission
  that cannot reasonably be considered an attempt at the assignment.
- If brief + rubric are too vague to infer a task, set relevance_factor 1.0, off_topic false,
  student_fulfills_assignment true, and say the task was underspecified.
- Empty or placeholder code → very low relevance_factor, student_fulfills_assignment false.
- All string fields must be single-line JSON strings; escape quotes and do not insert raw line breaks.
Reply with ONLY valid JSON matching the schema in the user message.
"""


def _task_domain_guess_from_text(text: str) -> str:
    blob = (text or "").lower()
    if any(t in blob for t in ("api", "endpoint", "fastapi", "flask", "http")):
        return "API / web servis"
    if any(t in blob for t in ("sqlite", "sql", "database", "tablo")):
        return "veritabani uygulamasi"
    if any(t in blob for t in ("log", "cli", "dosya", "arguman", "komut")):
        return "dosya/CLI araci"
    if any(t in blob for t in ("kutuphane", "kitap", "uye", "odunc", "iade")):
        return "OOP kutuphane sistemi"
    if any(t in blob for t in ("agac", "ağaç", "bst", "dugum", "node", "inorder", "preorder")):
        return "agac veri yapisi"
    if any(t in blob for t in ("liste", "ortalama", "istatistik", "flatten", "veri")):
        return "veri isleme"
    return "programlama odevi"


def _contains_marker(text: str, marker: str) -> bool:
    marker_l = marker.lower()
    if " " in marker_l:
        return marker_l in text
    if re.search(r"[a-z0-9_]", marker_l, flags=re.IGNORECASE):
        return bool(re.search(rf"(?<![a-z0-9_]){re.escape(marker_l)}(?![a-z0-9_])", text))
    return marker_l in text


def _has_code_deliverable_intent(text: str) -> bool:
    non_code_deliverables = ("makale", "rapor", "poster", "sunum", "slayt", "essay")
    explicit_tech_markers = (
        "api",
        "endpoint",
        "fonksiyon",
        "kod",
        "program",
        "script",
        "cli",
        "web",
        "react",
        "html",
        "css",
        "python",
        "javascript",
        "typescript",
        "c++",
        "cpp",
    )
    if any(_contains_marker(text, marker) for marker in non_code_deliverables) and not any(
        _contains_marker(text, marker) for marker in explicit_tech_markers
    ):
        return False

    code_intent_markers = (
        "yaz",
        "yazin",
        "gelistir",
        "gelistirin",
        "uygulama",
        "arac",
        "api",
        "endpoint",
        "fonksiyon",
        "kod",
        "program",
        "script",
        "cli",
        "web",
        "react",
        "html",
        "css",
        "python",
        "javascript",
        "typescript",
        "c++",
        "cpp",
    )
    if any(_contains_marker(text, marker) for marker in code_intent_markers):
        return True
    return not any(_contains_marker(text, marker) for marker in non_code_deliverables)


def _has_recognized_capability_requirement(text: str) -> bool:
    task_text = (text or "").lower()
    if not _has_code_deliverable_intent(task_text):
        return False
    marker_groups = (
        ("api", "endpoint", "http", "server", "post", "put", "get", "route"),
        (
            "api istemcisi",
            "istemci",
            "client",
            "api_url",
            "ortam degisken",
            "konfigurasyon",
            "config",
            "url",
            "durum kodu",
            "status code",
            "http istek",
        ),
        ("react", "frontend", "ui", "arayuz", "bilesen", "component", "form", "state", "todo"),
        ("html", "css", "responsive", "medya sorgusu", "portfolio", "portfolyo", "sayfa"),
        ("javascript", "typescript", "node", "npm"),
        ("c++", "cpp", "vektor", "vector", "sirala", "siralayan", "sort", "min", "max"),
        ("sqlite", "sql", "database", "db", "tablo"),
        ("log", "dosya", "file", "cli", "arguman", "komut", "satir", "rapor", "export", "cikti dosyasi"),
        ("sinif", "class", "oop", "nesne", "kalitim", "encapsulation"),
        ("agac", "tree", "bst", "dugum", "node", "traversal", "inorder", "preorder", "postorder"),
        ("liste", "list", "veri", "data", "istatistik", "ortalama", "average", "flatten", "donustur", "dönüştür"),
        ("pytest", "unittest", "unit test", "otomatik test"),
    )
    return any(any(_contains_marker(task_text, marker) for marker in group) for group in marker_groups)


def _deterministic_capability_fallback(
    *,
    combined_task_text: str,
    code_sample: str,
    capability_match: float,
) -> dict[str, Any] | None:
    if not _has_recognized_capability_requirement(combined_task_text):
        return None
    if capability_match > 0.24:
        return None
    return {
        "skipped": False,
        "relevance_factor": 0.22,
        "off_topic": True,
        "student_fulfills_assignment": False,
        "confidence": 0.72,
        "explanation": (
            "Deterministik görev uyumu kontrolü, kodun ödevde açıkça istenen temel "
            "kabiliyetleri taşımadığını gösterdi."
        ),
        "submission_domain_guess": _task_domain_guess_from_text(code_sample),
        "task_domain_guess": _task_domain_guess_from_text(combined_task_text),
        "capability_match": round(max(0.0, min(1.0, capability_match)), 3),
        "reason": "deterministic_capability_mismatch",
    }


def _unwrap_task_relevance_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Best-effort unwrap for models that nest JSON under result/report/data."""
    required = {"relevance_factor", "off_topic", "student_fulfills_assignment"}
    top_hits = len(required.intersection(raw.keys()))
    if top_hits >= 2:
        return raw

    stack: list[dict[str, Any]] = []
    for value in raw.values():
        if isinstance(value, dict):
            stack.append(value)
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict):
                stack.append(parsed)

    best = raw
    best_hits = top_hits
    while stack:
        cand = stack.pop(0)
        hits = len(required.intersection(cand.keys()))
        if hits > best_hits:
            best = cand
            best_hits = hits
        for value in cand.values():
            if isinstance(value, dict):
                stack.append(value)
            elif isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    stack.append(parsed)
    return {**raw, **best} if best is not raw else raw



async def assess_task_relevance_llm(
    *,
    assignment_description: str,
    source_code: str,
    rubric_criteria: list[dict[str, Any]] | None,
    report_language: str = "tr",
) -> dict[str, Any]:
    brief = (assignment_description or "").strip()
    source_clean = _source_without_comments_and_docstrings(source_code or "")
    # Use the instructor brief only for capability gating; rubric rows can be noisy/generic.
    capability_match = _capability_match_signal(assignment_description, None, source_clean)
    rub_blob = _rubric_criteria_text(rubric_criteria)
    combined = "\n".join(x for x in (brief, rub_blob) if x).strip()
    if len(combined) < BRIEF_MIN_LEN:
        return {"skipped": True, "relevance_factor": 1.0, "reason": "insufficient_task_context"}

    code_sample = source_clean or (source_code or "")
    fallback = _deterministic_capability_fallback(
        combined_task_text=combined,
        code_sample=code_sample,
        capability_match=capability_match,
    )

    if not settings.ollama_enabled:
        if fallback:
            return fallback
        return {"skipped": True, "relevance_factor": 1.0, "reason": "ollama_disabled"}

    rubric_json = []
    if rubric_criteria:
        for i, row in enumerate(rubric_criteria):
            if not isinstance(row, dict):
                continue
            rubric_json.append({
                "row": i,
                "name": str(row.get("name", "") or ""),
                "description": str(row.get("description", "") or ""),
            })

    max_chars = 12000
    if len(code_sample) > max_chars:
        code_sample = (
            code_sample[: max_chars // 2]
            + "\n# [... truncated for relevance check ...]\n"
            + code_sample[-max_chars // 2 :]
        )

    user_prompt = (
        "[INSTRUCTOR BRIEF]\n"
        f"{brief or '(none)'}\n\n"
        "[FACULTY RUBRIC ROWS — name + description]\n"
        f"{json.dumps(rubric_json, ensure_ascii=False, indent=2) if rubric_json else '(none)'}\n\n"
        "[STUDENT SOURCE — excerpt]\n"
        f"```\n{code_sample}\n```\n"
        "Return JSON with: relevance_factor, off_topic, student_fulfills_assignment, explanation, "
        "submission_domain_guess, task_domain_guess; optional confidence 0–1."
        "\nRequired JSON shape exactly: {"
        "\"relevance_factor\":0.0,"
        "\"off_topic\":false,"
        "\"student_fulfills_assignment\":false,"
        "\"confidence\":0.0,"
        "\"explanation\":\"single-line explanation\","
        "\"submission_domain_guess\":\"short label\","
        "\"task_domain_guess\":\"short label\""
        "}. Use single-line strings only; do not insert raw newlines inside JSON strings."
        f"{build_llm_user_suffix(report_language=report_language)}"
    )

    try:
        raw = await chat_json(
            system_prompt=_TASK_RELEVANCE_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.15,
            num_predict=1536,
            model=settings.ollama_coder_model,
            use_cache=False,
        )
    except Exception as exc:
        logger.warning("[task_relevance] LLM cagrisi basarisiz: %s", exc)
        if fallback:
            return fallback
        return {"skipped": True, "relevance_factor": 1.0, "reason": "llm_error"}

    if not isinstance(raw, dict):
        if fallback:
            return fallback
        return {"skipped": True, "relevance_factor": 1.0, "reason": "invalid_response"}
    raw = _unwrap_task_relevance_payload(raw)
    if not str(raw.get("task_domain_guess", "")).strip():
        raw["task_domain_guess"] = _task_domain_guess_from_text(combined)
    if not str(raw.get("submission_domain_guess", "")).strip():
        raw["submission_domain_guess"] = _task_domain_guess_from_text(code_sample)
    if not str(raw.get("explanation", "")).strip():
        raw["explanation"] = "Gorev uyumu kod ve odev aciklamasi karsilastirilarak degerlendirildi."
    if "confidence" in raw and raw.get("confidence") is None:
        raw.pop("confidence", None)

    msgs = collect_validation_messages(raw, TASK_RELEVANCE_OUTPUT_SCHEMA)
    if msgs:
        logger.warning("[task_relevance] schema ilk tur: %s", msgs[:4])
        repair = (
            user_prompt
            + "\n\n[SCHEMA REPAIR] Fix JSON. Errors:\n"
            + "\n".join(msgs)
            + "\nReturn ONLY complete valid JSON."
        )
        try:
            raw2 = await chat_json(
                system_prompt=_TASK_RELEVANCE_SYSTEM,
                user_prompt=repair,
                temperature=0.1,
                num_predict=1536,
                model=settings.ollama_coder_model,
                use_cache=False,
            )
        except Exception as exc:
            logger.warning("[task_relevance] schema onarim basarisiz: %s", exc)
            return {"skipped": True, "relevance_factor": 1.0, "reason": "schema_repair_failed"}
        if isinstance(raw2, dict):
            raw = _unwrap_task_relevance_payload(raw2)
            if not str(raw.get("task_domain_guess", "")).strip():
                raw["task_domain_guess"] = _task_domain_guess_from_text(combined)
            if not str(raw.get("submission_domain_guess", "")).strip():
                raw["submission_domain_guess"] = _task_domain_guess_from_text(code_sample)
            if not str(raw.get("explanation", "")).strip():
                raw["explanation"] = "Gorev uyumu kod ve odev aciklamasi karsilastirilarak degerlendirildi."
            msgs = collect_validation_messages(raw, TASK_RELEVANCE_OUTPUT_SCHEMA)
        if msgs:
            logger.warning("[task_relevance] schema ikinci tur hata: %s", msgs[:4])
            try:
                rf_soft = float(raw.get("relevance_factor", 1.0))
            except (TypeError, ValueError):
                rf_soft = 1.0
            rf_soft = max(0.05, min(1.0, rf_soft))
            return {
                "skipped": False,
                "relevance_factor": rf_soft,
                "off_topic": bool(raw.get("off_topic")),
                "student_fulfills_assignment": bool(
                    raw.get("student_fulfills_assignment", not bool(raw.get("off_topic")))
                ),
                "explanation": str(raw.get("explanation", "")).strip(),
                "submission_domain_guess": str(raw.get("submission_domain_guess", "")).strip(),
                "task_domain_guess": str(raw.get("task_domain_guess", "")).strip(),
                "capability_match": round(max(0.0, min(1.0, capability_match)), 3),
                "reason": "schema_invalid_soft_parse",
            }

    try:
        rf = float(raw.get("relevance_factor", 1.0))
    except (TypeError, ValueError):
        rf = 1.0
    rf = max(0.05, min(1.0, rf))

    out = {
        "skipped": False,
        "relevance_factor": rf,
        "off_topic": bool(raw.get("off_topic")),
        "student_fulfills_assignment": bool(raw.get("student_fulfills_assignment")),
        "explanation": str(raw.get("explanation", "")).strip(),
        "submission_domain_guess": str(raw.get("submission_domain_guess", "")).strip(),
        "task_domain_guess": str(raw.get("task_domain_guess", "")).strip(),
        "capability_match": round(max(0.0, min(1.0, capability_match)), 3),
    }
    try:
        cf = raw.get("confidence")
        if cf is not None:
            out["confidence"] = max(0.0, min(1.0, float(cf)))
    except (TypeError, ValueError):
        pass
    return out


def _guess_token_overlap(a: str | None, b: str | None) -> bool:
    """Tiny lexical overlap check to soften obvious false negatives."""
    ta = {t for t in re.findall(r"[a-z0-9_]{3,}", (a or "").lower())}
    tb = {t for t in re.findall(r"[a-z0-9_]{3,}", (b or "").lower())}
    if not ta or not tb:
        return False
    stop = {"the", "and", "for", "code", "task", "assignment", "project", "student"}
    ta = ta - stop
    tb = tb - stop
    if not ta or not tb:
        return False
    return len(ta.intersection(tb)) >= 1


def _capability_match_signal(
    assignment_description: str | None,
    rubric_criteria: list[dict[str, Any]] | None,
    source_code: str | None,
) -> float:
    """Estimate generic assignment-capability fit between task text and source code (0..1)."""
    task_text = "\n".join(
        x for x in ((assignment_description or "").strip(), _rubric_criteria_text(rubric_criteria)) if x
    ).lower()
    code_text = _source_without_comments_and_docstrings(source_code or "").lower()
    if len(task_text) < BRIEF_MIN_LEN and not _has_recognized_capability_requirement(task_text):
        return 1.0

    groups: list[tuple[set[str], set[str]]] = [
        (
            {"api", "endpoint", "http", "server", "post", "put", "get", "route"},
            {"httpserver", "basehttprequesthandler", "do_post", "do_put", "do_get", "fastapi", "flask", "route"},
        ),
        (
            {
                "api istemcisi",
                "istemci",
                "client",
                "api_url",
                "ortam degisken",
                "konfigurasyon",
                "config",
                "url",
                "durum kodu",
                "status code",
                "http istek",
            },
            {
                "os.environ",
                "getenv(",
                "urllib.request",
                "urlopen(",
                "requests.get",
                "status_code",
                ".status",
                "timeout=",
            },
        ),
        (
            {"react", "frontend", "ui", "arayuz", "bilesen", "component", "form", "state", "gorev", "todo"},
            {
                "react",
                "usestate",
                "useeffect",
                "export function",
                "function ",
                "return <",
                "jsx",
                "onclick",
                "onchange",
                "setitems",
                "setstate",
                "filter(",
            },
        ),
        (
            {"html", "css", "responsive", "medya sorgusu", "portfolio", "portfolyo", "sayfa"},
            {
                "<!doctype",
                "<html",
                "<head",
                "<body",
                "<style",
                "@media",
                "display: flex",
                "display:flex",
                "display: grid",
                "display:grid",
                "grid-template",
                "<header",
                "<section",
                "<article",
                "class=",
            },
        ),
        (
            {"javascript", "typescript", "node", "npm"},
            {"const ", "let ", "function ", "=>", "import ", "export ", "require(", "module.exports"},
        ),
        (
            {"c++", "cpp", "vektor", "vector", "sirala", "siralayan", "sort", "min", "max"},
            {
                "#include <vector>",
                "#include<vector>",
                "std::vector",
                "vector<",
                "std::sort",
                "sort(",
                "min_element",
                "max_element",
                "begin()",
                "end()",
            },
        ),
        (
            {"sqlite", "sql", "database", "db", "tablo"},
            {"sqlite3", "connect(", "cursor", "select ", "insert ", "update ", "create table"},
        ),
        (
            {"log", "dosya", "file", "cli", "arguman", "komut", "satir", "rapor", "export", "cikti dosyasi"},
            {
                "argparse",
                "sys.argv",
                "path(",
                "read_text",
                "open(",
                "readlines",
                "splitlines",
                "write(",
                "writerow",
                "dictwriter",
                "os.system",
                "export_report",
            },
        ),
        (
            {"sinif", "class", "oop", "nesne", "kalitim", "encapsulation"},
            {"class ", "__init__", "self.", "super("},
        ),
        (
            {"agac", "tree", "bst", "dugum", "node", "traversal", "inorder", "preorder", "postorder"},
            {"class ", "node", "dugum", "inorder", "preorder", "postorder", "left", "right", "sol", "sag"},
        ),
        (
            {"liste", "list", "veri", "data", "istatistik", "ortalama", "average", "flatten", "donustur", "dönüştür"},
            {
                "list[",
                "list(",
                "append(",
                "extend(",
                "sum(",
                "len(",
                "flatten",
                "average",
                "ortalama",
                "filter(",
                "map(",
            },
        ),
        (
            {"pytest", "unittest", "unit test", "otomatik test"},
            {"assert ", "pytest", "unittest", "test_"},
        ),
    ]

    required = 0
    matched = 0
    client_context = any(
        _contains_marker(task_text, marker)
        for marker in ("api istemcisi", "istemci", "client", "api_url", "ortam degisken", "konfigurasyon")
    )
    for task_markers, code_markers in groups:
        if client_context and task_markers == {"api", "endpoint", "http", "server", "post", "put", "get", "route"}:
            continue
        if any(_contains_marker(task_text, marker) for marker in task_markers):
            required += 1
            if any(marker in code_text for marker in code_markers):
                matched += 1

    task_tokens = {t for t in re.findall(r"[a-z0-9_]{3,}", task_text)}
    code_tokens = {t for t in re.findall(r"[a-z0-9_]{3,}", code_text)}
    stop = {
        "the", "and", "for", "with", "from", "this", "that", "code", "task",
        "assignment", "project", "student", "return", "true", "false", "none",
    }
    task_tokens -= stop
    code_tokens -= stop
    overlap_count = len(task_tokens.intersection(code_tokens))
    overlap_signal = min(0.5, overlap_count / 10.0) if task_tokens and code_tokens else 0.0

    if required == 0:
        return overlap_signal
    capability = matched / float(required)
    return max(0.0, min(1.0, (0.85 * capability) + (0.15 * overlap_signal)))


def merge_task_alignment(
    programmatic_factor: float,
    programmatic_reasons: list[str],
    llm_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """LLM görev uyumu ile birleştirir; alakasız teslimde çarpanı doğrudan düşürür."""
    reasons = list(programmatic_reasons)
    out: dict[str, Any] = {
        "factor": max(0.05, min(1.0, float(programmatic_factor))),
        "reasons": reasons,
        "programmatic_factor": max(0.05, min(1.0, float(programmatic_factor))),
        "llm_factor": None,
        "llm_explanation": None,
        "llm_off_topic": False,
        "llm_skipped": True,
        "submission_domain_guess": None,
        "task_domain_guess": None,
    }

    if not llm_payload or llm_payload.get("skipped"):
        return out

    try:
        llm_raw = float(llm_payload.get("relevance_factor", 1.0))
    except (TypeError, ValueError):
        llm_raw = 1.0
    llm_raw = max(0.05, min(1.0, llm_raw))

    off = bool(llm_payload.get("off_topic"))
    fulfils = bool(llm_payload.get("student_fulfills_assignment", True))
    try:
        capability_signal = float(llm_payload.get("capability_match", 0.0))
    except (TypeError, ValueError):
        capability_signal = 0.0

    llm_f = llm_raw
    if off:
        llm_f = min(llm_f, 0.2)
    elif not fulfils:
        llm_f = min(llm_f, 0.3)
    elif llm_raw < 0.45:
        llm_f = min(llm_f, 0.35)
    llm_f = max(0.05, min(1.0, llm_f))

    out["llm_skipped"] = False
    out["llm_factor"] = llm_f
    out["submission_domain_guess"] = llm_payload.get("submission_domain_guess") or None
    out["task_domain_guess"] = llm_payload.get("task_domain_guess") or None

    expl = str(llm_payload.get("explanation", "") or "").strip()
    if expl:
        out["llm_explanation"] = expl

    llm_confidence = llm_payload.get("confidence")
    try:
        conf = float(llm_confidence) if llm_confidence is not None else None
    except (TypeError, ValueError):
        conf = None
    overlap = _guess_token_overlap(
        out.get("task_domain_guess"),
        out.get("submission_domain_guess"),
    )

    # If LLM marks off-topic but capability markers strongly match, convert it to
    # "in-topic but weak implementation" instead of full mismatch.
    if off and capability_signal >= 0.55:
        off = False
        fulfils = False
        llm_f = max(llm_f, 0.62 if capability_signal >= 0.72 else 0.55)

    # A strongly matching code shape (CLI/API/OOP/BST etc.) means the submission is
    # aimed at the assignment even if the LLM thinks one deliverable is incomplete.
    # Completeness should be graded by the rubric, not converted into an off-topic cap.
    if (
        not off
        and not fulfils
        and out["programmatic_factor"] >= 0.95
        and capability_signal >= 0.80
    ):
        fulfils = True
        llm_f = max(llm_f, 0.75)

    # Opposite direction: if capability markers are clearly missing, do not allow
    # a high-fit verdict from LLM noise.
    if not off and capability_signal <= 0.24 and llm_f >= 0.50:
        off = True
        fulfils = False
        llm_f = min(llm_f, 0.22)

    # If LLM says low fit (without explicit off_topic) but confidence is low,
    # domain guesses overlap, or capability signal is strong, avoid over-collapse.
    if out["programmatic_factor"] >= 0.95 and llm_f < 0.45 and not off:
        if (conf is not None and conf < 0.62) or overlap or capability_signal >= 0.55:
            llm_f = max(llm_f, 0.68 if capability_signal >= 0.55 else 0.72)

    # High-capability and clearly fulfilling submissions should not drift too low
    # due model variance.
    if (
        out["programmatic_factor"] >= 0.95
        and not off
        and fulfils
        and capability_signal >= 0.80
        and llm_f < 0.75
    ):
        llm_f = 0.75

    out["llm_factor"] = llm_f
    out["factor"] = min(out["factor"], llm_f)
    out["llm_off_topic"] = off

    if off:
        if "llm_task_relevance_off_topic" not in reasons:
            reasons.append("llm_task_relevance_off_topic")
    elif not fulfils:
        if "llm_task_not_fulfilled" not in reasons:
            reasons.append("llm_task_not_fulfilled")
    elif llm_f <= 0.38:
        if "llm_low_task_fit" not in reasons:
            reasons.append("llm_low_task_fit")

    out["reasons"] = reasons
    return out
