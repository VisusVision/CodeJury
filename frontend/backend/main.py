"""
FastAPI backend -- Gercek multi-agent code review pipeline.
"""

import ast
import csv
import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
import traceback
import tracemalloc
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import asyncpg
from fastapi import FastAPI, HTTPException, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.agents.code_quality import CodeQualityAgent
from backend.agents.seniority import SeniorityAgent
from backend.agents.guideline import GuidelineAgent
from backend.agents.security import SecurityAgent
from backend.agents.test_agent import TestAgent
from backend.agents.evidence import EvidenceAgent
from backend.agents.master_evaluator import MasterEvaluatorAgent
from backend.agents.assignment_safety import AssignmentSafetyAgent
from backend.llm.ollama_client import chat_json

logger = logging.getLogger(__name__)

app = FastAPI(title="Multi-Agent Code Analysis API", version="2.1.0")

# API yaniti ve /api/health ile eslesir; frontend cache invalidasyonu icin
_ANALYSIS_ENGINE = "2.1.0-rubrik"
_MAIN_FILE = Path(__file__).resolve()
_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://semas:12345@localhost:5432/agent_db")
_DEMO_MODE = os.getenv("DEMO_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
_DB_POOL: asyncpg.Pool | None = None

_DEMO_STORE: dict[str, Any] = {
    "teachers": [
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "first_name": "Demo",
            "last_name": "Teacher",
            "email": "demo@agentgrade.local",
            "password_hash": "",
            "created_at": datetime.utcnow().isoformat(),
        }
    ],
    "students": [
        {
            "id": "22222222-2222-4222-8222-222222222222",
            "student_no": "20240001",
            "tc_no": "11111111111",
            "first_name": "Demo",
            "last_name": "Student",
            "class_year": 2,
            "department_id": "33333333-3333-4333-8333-333333333333",
            "created_at": datetime.utcnow().isoformat(),
        }
    ],
    "departments": [
        {
            "id": "33333333-3333-4333-8333-333333333333",
            "name": "Bilgisayar Muhendisligi",
            "created_by": "11111111-1111-4111-8111-111111111111",
            "created_at": datetime.utcnow().isoformat(),
        }
    ],
    "courses": [
        {
            "id": "44444444-4444-4444-8444-444444444444",
            "name": "Veri Yapilari",
            "code": "BLM201",
            "class_year": 2,
            "department_id": "33333333-3333-4333-8333-333333333333",
            "created_at": datetime.utcnow().isoformat(),
        }
    ],
    "assignments": [
        {
            "id": "55555555-5555-4555-8555-555555555555",
            "course_id": "44444444-4444-4444-8444-444444444444",
            "name": "Ikili Agac Odevi",
            "description": "Temel BST islemleri",
            "due_date": None,
            "created_at": datetime.utcnow().isoformat(),
        }
    ],
    "rubrics": [
        {
            "id": "66666666-6666-4666-8666-666666666666",
            "assignment_id": "55555555-5555-4555-8555-555555555555",
            "criteria": [
                {"name": "Fonksiyonellik", "description": "Gereksinimler", "max_score": 40},
                {"name": "Kod Kalitesi", "description": "Okunabilirlik", "max_score": 30},
                {"name": "Verimlilik", "description": "Algoritma secimi", "max_score": 30},
            ],
            "status": "approved",
            "created_by": "11111111-1111-4111-8111-111111111111",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
    ],
    "questions": [
        {
            "id": "77777777-7777-4777-8777-777777777777",
            "content": "Dogru sekilde hata kontrolu yapiliyor mu?",
            "color": "blue",
            "created_by": "11111111-1111-4111-8111-111111111111",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        },
        {
            "id": "88888888-8888-4888-8888-888888888888",
            "content": "Degisken isimlendirmesi tutarli mi?",
            "color": "green",
            "created_by": "11111111-1111-4111-8111-111111111111",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        },
        {
            "id": "99999999-9999-4999-8999-999999999999",
            "content": "Bellek sizdirmasi riski var mi?",
            "color": "pink",
            "created_by": "11111111-1111-4111-8111-111111111111",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        },
    ],
    "assignment_questions": {},
    "upload_history": [],
}

_DEMO_STORE_FILE = Path(
    os.getenv("DEMO_STORE_FILE", str(_MAIN_FILE.parent.parent.parent / ".demo_store.json"))
)
_ASSIGNMENT_SAFETY_AGENT = AssignmentSafetyAgent()


def _load_demo_store_from_disk() -> None:
    """DEMO_MODE icin RAM store'u diskten geri yukle (dev reload veri kaybettirmesin)."""
    global _DEMO_STORE
    if not _DEMO_MODE or not _DEMO_STORE_FILE.exists():
        return
    try:
        loaded = json.loads(_DEMO_STORE_FILE.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return
        # Yeni kodda eklenen anahtarlar kaybolmasin diye default store ile merge edilir.
        merged = dict(_DEMO_STORE)
        for key, value in loaded.items():
            if key in merged and isinstance(value, list):
                merged[key] = value
        _DEMO_STORE = merged
        print(f"[mentor-api] DEMO store yuklendi: {_DEMO_STORE_FILE}", flush=True)
    except Exception as exc:
        print(f"[mentor-api] DEMO store okunamadi ({_DEMO_STORE_FILE}): {exc}", flush=True)


def _save_demo_store_to_disk() -> None:
    """DEMO_MODE mutasyonlarini diske yaz; PostgreSQL yokken de kayitlar reload sonrasi kalsin."""
    if not _DEMO_MODE:
        return
    try:
        _DEMO_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DEMO_STORE_FILE.with_suffix(_DEMO_STORE_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(_DEMO_STORE, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_DEMO_STORE_FILE)
    except Exception as exc:
        print(f"[mentor-api] DEMO store yazilamadi ({_DEMO_STORE_FILE}): {exc}", flush=True)


@app.on_event("startup")
def _startup_log() -> None:
    """Hangi main.py yuklendigini terminale yazar (yanlis klasorden uvicorn tespiti)."""
    _load_demo_store_from_disk()
    if _DEMO_MODE and _DEMO_STORE["teachers"] and not _DEMO_STORE["teachers"][0].get("password_hash"):
        _DEMO_STORE["teachers"][0]["password_hash"] = _hash_password("demo123")
        _save_demo_store_to_disk()
    print(
        f"[mentor-api] OK | analysis_engine={_ANALYSIS_ENGINE} | main={_MAIN_FILE}",
        flush=True,
    )


@app.on_event("startup")
def _startup_sandbox_pool() -> None:
    """Sandbox container havuzunu arka planda başlat."""
    import threading
    def _init():
        try:
            from backend.sandbox.pool_manager import initialize_pool
            initialize_pool()
        except Exception as e:
            print(f"[mentor-api] Sandbox pool başlatılamadı (Docker açık mı?): {e}", flush=True)
    threading.Thread(target=_init, daemon=True).start()


@app.on_event("shutdown")
def _shutdown_sandbox_pool() -> None:
    """Sandbox container'larını kapat."""
    try:
        from backend.sandbox.pool_manager import shutdown_pool
        shutdown_pool()
    except Exception:
        pass


@app.on_event("startup")
async def _startup_db() -> None:
    global _DB_POOL
    if _DEMO_MODE:
        print("[mentor-api] DEMO_MODE aktif: PostgreSQL baglantisi atlandi", flush=True)
        return
    last_error: Exception | None = None
    for attempt in range(10):
        try:
            await _ensure_database_exists(_DATABASE_URL)
            _DB_POOL = await asyncpg.create_pool(dsn=_DATABASE_URL, min_size=1, max_size=5)
            await _ensure_db_schema(_DB_POOL)
            print("[mentor-api] PostgreSQL baglantisi ve schema hazir", flush=True)
            return
        except Exception as exc: 
            last_error = exc
            _DB_POOL = None
            if attempt < 9:
                await asyncio.sleep(1.5)
            else:
                raise RuntimeError(f"Veritabani baslatma hatasi: {exc}") from exc
    if last_error is not None:
        raise RuntimeError(f"Veritabani baslatma hatasi: {last_error}")


@app.on_event("shutdown")
async def _shutdown_db() -> None:
    global _DB_POOL
    if _DB_POOL is not None:
        await _DB_POOL.close()
        _DB_POOL = None


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalysisRequest(BaseModel):
    file_name: str
    file_content: str
    assignment_id: Optional[str] = None


class StudentLoginRequest(BaseModel):
    student_no: str
    tc_no: str


class UploadHistoryRequest(BaseModel):
    student_first_name: str
    student_last_name: str
    student_no: str
    uploaded_file_name: str
    assignment_id: str | None = None
    score: int | None = None
    has_error: bool = False


class TeacherRegisterRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str


class TeacherLoginRequest(BaseModel):
    email: str
    password: str


class DepartmentCreateRequest(BaseModel):
    name: str
    created_by: str | None = None


class CourseCreateRequest(BaseModel):
    name: str
    code: str
    class_year: int | None = None
    department_id: str | None = None


class AssignmentCreateRequest(BaseModel):
    course_id: str
    name: str
    description: str | None = None
    due_date: str | None = None


class RubricUpsertRequest(BaseModel):
    assignment_id: str
    criteria: list[dict[str, Any]]
    status: str = "draft"
    created_by: str | None = None


class RubricUpdateStatusRequest(BaseModel):
    status: str


class RubricSuggestionRequest(BaseModel):
    assignment_title: str
    assignment_description: str = ""
    criterion_count: int = 10


_RUBRIC_SUGGEST_SYSTEM = """\
You reply with a single JSON object only. No markdown, no code fences, no commentary.

You design grading rubric CRITERIA for an undergraduate programming assignment (Turkish UI).

JSON shape exactly:
{
  "criteria": [
    {
      "name": "short criterion name in Turkish",
      "description": "Plain Turkish, ONE short paragraph: what is graded and what excellent work looks like. No markdown.",
      "max_score": 10
    }
  ]
}

Rules:
- Produce EXACTLY the requested number of criteria.
- The requested criterion count will always be between 10 and 20.
- Each max_score MUST be an integer from 5 to 10 inclusive.
- The sum of all max_score values MUST equal exactly 100.
- Tailor names and descriptions to the assignment title and description (e.g. OOP, data structures, APIs, file I/O, tests).
- If the assignment mentions unit tests, pytest, unittest, or testing, include a dedicated testing criterion.
- If the assignment does NOT mention tests, do not invent a dedicated test criterion;
  you may mention testability inside correctness or maintainability instead.
- Do NOT invent presentation, slide, poster, video, or visual-design criteria unless the assignment explicitly asks for those deliverables.
- Every criterion should grade the submitted software/code artifact: correctness, requirements, tests, error handling, data model, algorithmic efficiency, style, documentation, security, or maintainability.
- Names must be distinct; avoid duplicate or near-duplicate criteria.
- Descriptions must be measurable: say what evidence earns full credit and what defects lose credit.
- Do not include vague criteria such as "Genel", "Sunum", "Sekil", or "Kalite" unless the description ties them to concrete code evidence.
"""


_RUBRIC_MIN_CRITERIA = 10
_RUBRIC_MAX_CRITERIA = 20
_RUBRIC_MIN_POINTS = 5
_RUBRIC_MAX_POINTS = 10
_RUBRIC_TOTAL_POINTS = 100

_RUBRIC_FALLBACK_NAMES = [
    "Gereksinimlere Uyum",
    "Sınıf Tasarımı",
    "Metot Kapsamı",
    "Veri Modeli",
    "Hata Yönetimi",
    "Çalışabilirlik",
    "Algoritmik Uygunluk",
    "Kod Okunabilirliği",
    "Kapsülleme",
    "Test Edilebilirlik",
    "Entegrasyon",
    "Kenar Durumlar",
    "Dokümantasyon",
    "Kullanıcı Akışı",
    "Güvenli Kullanım",
    "Bakım Kolaylığı",
    "Modülerlik",
    "Girdi Doğrulama",
    "Çıktı Doğruluğu",
    "Genel Kalite",
]

_RUBRIC_PRESENTATION_TOKENS = (
    "sunum",
    "slayt",
    "slide",
    "presentation",
    "poster",
    "video",
    "gorsel",
    "görsel",
    "resim",
)

_RUBRIC_WEAK_NAME_TOKENS = (
    "genel",
    "kalite",
    "sekil",
    "şekil",
    "sunum",
)

_RUBRIC_TEST_TOKENS = (
    "test",
    "pytest",
    "unittest",
    "birim test",
    "unit test",
)

_RUBRIC_DEDICATED_TEST_NAME_TOKENS = (
    "test",
    "testler",
    "testleri",
    "test durumu",
)

_RUBRIC_PROCESS_TOKENS = (
    "gelistirme sureci",
    "geliştirme süreci",
    "versiyon kontrol",
    "git",
    "commit",
    "surec",
    "süreç",
)

_RUBRIC_NON_CODE_ODD_TOKENS = (
    "yikimlilik",
    "yıkımlılık",
)

_RUBRIC_CONCRETE_DESC_TOKENS = (
    "api",
    "endpoint",
    "algorit",
    "arama",
    "agac",
    "ağaç",
    "veri",
    "girdi",
    "cikti",
    "çıktı",
    "test",
    "pytest",
    "unittest",
    "hata",
    "exception",
    "edge",
    "kose",
    "köşe",
    "fonksiyon",
    "metot",
    "sinif",
    "sınıf",
    "dosya",
    "sql",
    "sqlite",
    "guven",
    "güven",
    "performans",
    "karma",
    "pep",
    "dokuman",
    "doküm",
)


def _assignment_allows_presentation_criteria(title: str, description: str) -> bool:
    blob = f"{title}\n{description}".lower()
    return any(token in blob for token in _RUBRIC_PRESENTATION_TOKENS)


def _assignment_requires_testing(title: str, description: str) -> bool:
    blob = f"{title}\n{description}".lower()
    return any(token in blob for token in _RUBRIC_TEST_TOKENS)


def _assignment_requires_process_evidence(title: str, description: str) -> bool:
    blob = f"{title}\n{description}".lower()
    return any(token in blob for token in _RUBRIC_PROCESS_TOKENS)


def _next_rubric_replacement_name(used_names: set[str]) -> str:
    for candidate in _RUBRIC_FALLBACK_NAMES:
        key = candidate.lower()
        if key not in used_names:
            used_names.add(key)
            return candidate
    suffix = len(used_names) + 1
    name = f"Gereksinimlere Uyum {suffix}"
    used_names.add(name.lower())
    return name


def _rubric_description_is_concrete(description: str) -> bool:
    blob = (description or "").lower()
    return any(token in blob for token in _RUBRIC_CONCRETE_DESC_TOKENS)


def _rubric_name_is_too_weak(name: str, description: str) -> bool:
    blob = (name or "").strip().lower()
    return (
        bool(blob)
        and any(token in blob for token in _RUBRIC_WEAK_NAME_TOKENS)
        and not _rubric_description_is_concrete(description)
    )


def _rubric_is_unrequested_test_criterion(name: str, description: str, *, testing_required: bool) -> bool:
    if testing_required:
        return False
    name_blob = (name or "").lower()
    desc_blob = (description or "").lower()
    if any(token in name_blob for token in _RUBRIC_DEDICATED_TEST_NAME_TOKENS):
        return True
    return "pytest" in desc_blob or "unittest" in desc_blob or "birim test" in desc_blob


def _rubric_is_unrequested_process_criterion(
    name: str,
    description: str,
    *,
    process_required: bool,
) -> bool:
    blob = f"{name}\n{description}".lower()
    if process_required:
        return False
    return any(token in blob for token in _RUBRIC_PROCESS_TOKENS)


def _sanitize_rubric_scope(
    criteria: list[dict[str, Any]],
    *,
    assignment_title: str,
    assignment_description: str,
) -> list[dict[str, Any]]:
    """Remove LLM-invented, duplicate, or vague non-code rubric rows."""
    allow_presentation = _assignment_allows_presentation_criteria(
        assignment_title,
        assignment_description,
    )
    testing_required = _assignment_requires_testing(assignment_title, assignment_description)
    process_required = _assignment_requires_process_evidence(
        assignment_title,
        assignment_description,
    )

    used_names: set[str] = set()
    sanitized: list[dict[str, Any]] = []
    for criterion in criteria:
        name = str(criterion.get("name", "")).strip()
        desc = str(criterion.get("description", "")).strip()
        blob = f"{name}\n{desc}".lower()
        key = name.lower()
        should_replace = (
            not name
            or key in used_names
            or (not allow_presentation and any(token in blob for token in _RUBRIC_PRESENTATION_TOKENS))
            or _rubric_is_unrequested_test_criterion(
                name,
                desc,
                testing_required=testing_required,
            )
            or _rubric_is_unrequested_process_criterion(
                name,
                desc,
                process_required=process_required,
            )
            or any(token in blob for token in _RUBRIC_NON_CODE_ODD_TOKENS)
            or _rubric_name_is_too_weak(name, desc)
        )
        if should_replace:
            replacement = _next_rubric_replacement_name(used_names)
            criterion = {
                **criterion,
                "name": replacement,
                "description": (
                    f"{replacement} kriteri, odevin kod tabanli tesliminde beklenen kapsam, "
                    "dogruluk ve kalite gereksinimlerinin ne kadar karsilandigini olcer."
                ),
            }
        else:
            used_names.add(key)
        sanitized.append(criterion)
    return sanitized


def _clamp_rubric_count(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = _RUBRIC_MIN_CRITERIA
    return max(_RUBRIC_MIN_CRITERIA, min(_RUBRIC_MAX_CRITERIA, n))


def _rubric_weights_for_count(count: int) -> list[int]:
    """Return count integers, each 5..10, summing to 100."""
    count = _clamp_rubric_count(count)
    weights = [_RUBRIC_MIN_POINTS] * count
    remaining = _RUBRIC_TOTAL_POINTS - sum(weights)
    i = 0
    while remaining > 0:
        if weights[i] < _RUBRIC_MAX_POINTS:
            weights[i] += 1
            remaining -= 1
        i = (i + 1) % count
    return weights


def _ensure_rubric_constraints(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not (_RUBRIC_MIN_CRITERIA <= len(criteria) <= _RUBRIC_MAX_CRITERIA):
        raise HTTPException(
            status_code=400,
            detail=f"Rubrik {_RUBRIC_MIN_CRITERIA}-{_RUBRIC_MAX_CRITERIA} kriterden olusmalidir.",
        )

    cleaned: list[dict[str, Any]] = []
    total = 0
    for item in criteria:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Rubrik kriterleri gecersiz.")
        name = str(item.get("name", "")).strip()
        desc = str(item.get("description", "")).strip()
        try:
            score = int(round(float(item.get("max_score", 0))))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Kriter puanlari sayi olmalidir.")
        if not name:
            raise HTTPException(status_code=400, detail="Tum kriterlerin adi doldurulmalidir.")
        if not (_RUBRIC_MIN_POINTS <= score <= _RUBRIC_MAX_POINTS):
            raise HTTPException(
                status_code=400,
                detail=f"Her kriter puani {_RUBRIC_MIN_POINTS}-{_RUBRIC_MAX_POINTS} arasinda olmalidir.",
            )
        total += score
        cleaned.append({"name": name, "description": desc or name, "max_score": score})

    if total != _RUBRIC_TOTAL_POINTS:
        raise HTTPException(status_code=400, detail="Rubrik toplam puani 100 olmalidir.")
    return cleaned


def _criteria_from_llm_payload(result: dict[str, Any], criterion_count: int) -> list[dict[str, Any]]:
    target = _clamp_rubric_count(criterion_count)
    raw = result.get("criteria")
    if not isinstance(raw, list):
        raise ValueError("criteria invalid")
    cleaned: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        desc = str(item.get("description", "")).strip()
        try:
            ms = int(round(float(item.get("max_score", 0))))
        except (TypeError, ValueError):
            ms = 0
        if ms < 1:
            ms = 1
        cleaned.append({
            "name": name,
            "description": desc if desc else name,
            "max_score": ms,
        })
    if len(cleaned) < 1:
        raise ValueError("too few criteria after clean")

    cleaned = cleaned[:target]
    while len(cleaned) < target:
        i = len(cleaned)
        name = _RUBRIC_FALLBACK_NAMES[i % len(_RUBRIC_FALLBACK_NAMES)]
        cleaned.append({
            "name": name,
            "description": f"{name} kriteri, odevin beklenen kapsam ve kalite gereksinimlerini karsilama duzeyini degerlendirir.",
            "max_score": _RUBRIC_MIN_POINTS,
        })

    weights = _rubric_weights_for_count(target)
    for i, criterion in enumerate(cleaned):
        criterion["max_score"] = weights[i]
    return cleaned


class AssignmentAssistantSuggestionsRequest(BaseModel):
    """Öğretim üyesi için ödev konusu önerileri (yapılandırılmış JSON)."""

    course_hint: str = ""
    count: int = 5
    difficulty: str | None = None  # "easy" | "medium" | "hard"
    prefer_fresh: bool = False  # True → Ollama önbelleğini atl (yeniden öner)


_ASSIGNMENT_SUGGEST_SYSTEM = """\
You reply with a single JSON object only. No markdown, no # headings, no bullet markdown,
no code fences, no ** bold — plain text inside JSON string values only.

You invent homework topics for undergraduate programming courses (Turkish universities).
Friendly Turkish throughout: title, summary, description.

JSON shape exactly:
{
  "suggestions": [
    {
      "title": "short homework title",
      "summary": "one line under 160 characters",
      "description": "Plain Turkish, ONE paragraph only: spaces between sentences, NEVER raw line breaks inside this string. Learning goals, what to implement, I/O or constraints, deliverables. Under 1200 characters. No solution code; no markdown."
    }
  ]
}

ABSOLUTE RULE — HINT IS LAW:
The instructor's hint (course context + free-form keywords) is the primary directive.
EVERY single suggestion MUST be visibly tied to that hint. The hint topic MUST appear
in the title or in the first sentence of summary/description. Never produce generic
"linked list / queue / stack / interface / OOP demo" topics if the hint clearly points
elsewhere. If the hint is broad (e.g. a domain name like "matematik", "fizik", "web",
"oyun", "yapay zeka", "veri bilimi", "biyoloji", "kimya"), generate PROGRAMMING homework
that APPLIES that domain: numerical methods, simulation, data analysis, mini engine,
mini API, etc. Each suggestion must explicitly mention the domain in title.

If the hint contradicts itself (e.g. "matematik ama OOP istiyorum"), respect both —
generate object-oriented programming exercises modelled on math (e.g. Vector class,
Polynomial class, Matrix class, ComplexNumber class).

Generate varied subtopics under the hint umbrella (5 different angles), not 5 copies of
the same exercise. Each description should be detailed enough that an instructor can
paste it into a course page as the assignment briefing.

If the user message specifies a mandatory difficulty tier (easy / medium / hard),
you MUST follow that tier strictly: easy homework must genuinely be beginner-sized;
hard homework must noticeably exceed medium in scope (multi-part design, edge cases).

Turkish wording note: In programming homework, "sınıf / sınıflar / sinif" from an instructor
almost always means OOP "class" (defining classes, objects, __init__, methods), NOT school
classroom. If the user hint points to classes/OOP, EVERY suggestion must center on classes,
encapsulation, inheritance, composition, or interfaces — not standalone arrays/loops-only tasks.
"""


def _assignment_focus_extra(hint_raw: str) -> str:
    """Turkce ipucundan OOP / veri yapisi / domain odak metni turetir."""
    h = (hint_raw or "").lower()
    chunks: list[str] = []

    oop_markers = (
        "sınıf", "sinif", "sınıfla", "sinifla", "sınıflar", "siniflar",
        "nesne", "oop", "class", " kalıtım", "kalitim", "miras",
        "kapsül", "kapsul", "encapsulation", "çok biçim", "cok bicim",
        "soyut sınıf", "soyut sinif", "arayüz", "arayuz", "__init__",
    )
    if any(m in h for m in oop_markers):
        chunks.append(
            "ODAK (ZORUNLU): İpucu doğrultusunda nesne yönelimli programlama isteniyor. Her öneri "
            "birden fazla sınıf (class), nesne oluşturma, kurucu ve metotlar; mümkünse kalıtım veya "
            "bileşim (composition) içermeli. Sadece dizi, ham döngü veya yalnızca özyinelemeli "
            "fonksiyon odaklı ödevler ÖNERME; öneriler OOP merkezli olsun."
        )

    ds_markers = (
        "ağaç", "agac", "liste", "linked", "kuyruk", "stack", "yığın", "yigin",
        "hash", "graf", "öncelik", "oncelik", "heap", "bst",
    )
    if any(m in h for m in ds_markers):
        chunks.append(
            "ODAK: Veri yapisi odevi istendiyse her oneri ilgili yapinin insert/traverse/silme vb. "
            "islemlerini net gereksinim olarak belirtmeli."
        )

    math_markers = (
        "matematik", "matematı", "math", "sayisal", "sayısal", "numerik", "numerical",
        "matris", "vektör", "vektor", "polinom", "denklem", "integral", "türev",
        "turev", "lineer cebir", "lineer cebir", "istatistik",
    )
    if any(m in h for m in math_markers):
        chunks.append(
            "ODAK (ZORUNLU): Konu MATEMATİK uygulamalı programlama. Her öneri başlık ve özetinde "
            "matematiksel kavramı (matris, vektör, polinom, sayısal türev/integral, denklem çözümü, "
            "istatistik vb.) açıkça içermeli. Genel veri yapısı veya OOP demosu ÖNERME; öneriler "
            "matematik problemini kodla çözmeye odaklansın."
        )

    physics_markers = ("fizik", "physics", "simülasyon", "simulasyon", "kinematik", "dinamik")
    if any(m in h for m in physics_markers):
        chunks.append(
            "ODAK: Konu FİZİK simülasyonu. Her öneri fiziksel bir senaryoyu (sarkac, eğik atış, "
            "esnek çarpışma, yerçekimi, dalga vb.) sayısal olarak modelleyip simüle etmeli."
        )

    web_markers = ("web", "rest", "api", "fastapi", "flask", "django", "http", "frontend", "backend")
    if any(m in h for m in web_markers):
        chunks.append(
            "ODAK: Konu WEB/API geliştirme. Her öneri en az 3 endpoint, basit doğrulama, "
            "hata yönetimi ve kalıcı veri saklama (sqlite/json) içeren mini bir servis olmalı."
        )

    game_markers = ("oyun", "game", "pygame", "unity", "labirent")
    if any(m in h for m in game_markers):
        chunks.append(
            "ODAK: Konu OYUN programlama. Her öneri kullanıcı girişi, oyun döngüsü ve durum "
            "güncellemesi içeren mini bir oyun ya da oyun mekaniği olmalı."
        )

    ml_markers = ("yapay zeka", "yapay zekâ", "machine learning", "ml", "veri bilimi", "data science",
                  "regresyon", "siniflandirma", "sınıflandırma", "kümeleme", "kumeleme")
    if any(m in h for m in ml_markers):
        chunks.append(
            "ODAK: Konu MAKİNE ÖĞRENMESİ / VERİ BİLİMİ. Her öneri küçük bir veri setiyle eğitim, "
            "test bölme ve metrik raporlama içeren bir uygulama olmalı."
        )

    return "\n".join(chunks)


def _normalize_assignment_difficulty(raw: str | None) -> str:
    """API'den gelen zorluğu dahili üç kademeye indirger."""
    s = (raw or "").strip().lower()
    if s in {"easy", "kolay", "k", "e", "basit", "1"}:
        return "easy"
    if s in {"hard", "zor", "h", "z", "advanced", "3"}:
        return "hard"
    if s in {"medium", "orta", "o", "m", "normal", "2"}:
        return "medium"
    return "medium"


def _assignment_difficulty_prompt_block(tier: str) -> str:
    """LLM kullanıcı prompt'una eklenecek zorunlu zorluk bloğu."""
    if tier == "easy":
        return (
            "ZORUNLU ZORLUK SEVİYESİ: KOLAY (birinci öğretim, gerçekten basit).\n"
            "- Tek dosya veya iki dosyadan fazlası gerektiren çok-parçalı projeler yazma.\n"
            "-Öğrenci birkaç kısa fonksiyon veya çok küçük bir nesne yapısı ile bitirebilir (yaklaşık "
            "30–90 mantıklı kod satırı düzeyi; açıklamada gereksinimleri sıkı sınırlayıcı tut).\n"
            "-Matematik uygulamalı ise: faktoriyel, küçük N için tam bölünürlük/asallık kontrolü, iki "
            "tam sayının EBOB–EKOK’u, aritmetik/geometrik dizi ilk n terimi, ikinci derece denklem "
            "kökeni (diskriminant sıfır/tekil kök), basit ortalama–medyan modu gibi TEK kavram odaklı "
            "görevler üret. Matris/vektör varsa EN FAZLA 2x2 veya çok kısıtlı boyut; genel N boyutlu "
            "cebir kütüphanesi, sayısal integral/türev karşılaştırması, optimizasyon veya iteratif "
            "yakınsama analizi KOLAY seviyede YASAK.\n"
            "-OOP istenmiyorsa sadece fonksiyon + main yeter; OOP isteniyorsa en fazla 1–2 küçük sınıf, "
            "kalıtım zorunlu tutma.\n"
            "Beş önerinin hepsi bu KOLAY tanıma uysun; orta veya zor kapsamda öneri verme.\n"
        )
    if tier == "hard":
        return (
            "ZORUNLU ZORLUK SEVİYESİ: ZOR (yüksek çaba, çok parçalı).\n"
            "-Her öneri birden fazla alt görev, net test senaryoları, hata/kenar durumu veya tasarım "
            "tercihlerini gerekçelendirmeyi içersin (ör. modüler yapı, birim test listesi, rapor bölümü).\n"
            "-Matematik uygulamalı ise: örneğin trapez ve Simpson ile aynı integral için karşılaştırma ve "
            "hata eğilimi gözlemı; küçük boyutta Gauss eliminasyonu veya LU fikri (adımları açıkça "
            "tariflenmiş); gradient iniş ile mini regresyon; basit iteratif doğrusal sistem (Jacobi/"
            "Gauss–Seidel) yakınsaklık denemesi; küçük veri için PCA veya benzeri matris çarpımları "
            "zorunlu bileşenlerle — öğrenci algoritma adımlarını kodlamalı.\n"
            "-KOLAY ile karıştırma: tek fonksiyonluk oyuncak görevleri bu seviyede yeterli değildir.\n"
            "Beş önerinin hepsi ZOR çerçevesinde yoğunluklu olsun.\n"
        )
    # medium
    return (
        "ZORUNLU ZORLUK SEVİYESİ: ORTA (tipik homework).\n"
        "-Birkaç fonksiyon veya 2–3 sınıfa kadar makul yapı; belirgin ama tek parça kod tabanında "
        "bitebilen görev.\n"
        "-Küçük dosyadan giriş/çıkış ya da konsol ile net formatlı I/O kombinasyonu olabilir.\n"
        "-Matematik uygulamalı ise: iki fonksiyonun kökünü bisection/regula falsi ile bulma; 3×3 "
        "determinant ve küçük (en fazla 5 bilinmeyen) doğrusal sistem; Euler veya iki adımla basit "
        "ODE yaklaşımı; iki vektörün iç çarpımı, uzunluk ve aralarındaki açı (derece); basit doğrusal "
        "regresyon (çizgi uydurma) — klasik ara öğrenim iş yükünde kal.\n"
        "-Tam genel kütüphane veya araştırma projesi yazma.\n"
        "Beş önerinin hepsi ORTA tanıya uysun.\n"
    )


def _strip_md_leaks(text: str) -> str:
    """JSON icinde kalan # veya kalin isaretlerini yumusatir."""
    lines: list[str] = []
    for raw in text.replace("**", "").splitlines():
        s = raw.strip()
        while s.startswith("#"):
            s = s[1:].lstrip()
        if s.startswith(("- ", "* ")) and len(s) > 2:
            s = s[2:].strip()
        lines.append(s)
    return "\n".join(lines).strip()


def _suggestions_list_from_llm(result: dict[str, Any]) -> list[Any] | None:
    """LLM ciktisindaki liste alanini bul (model bazen anahtar adini degistirir)."""
    for key in ("suggestions", "oneriler", "items", "odevler", "topics", "assignments"):
        raw = result.get(key)
        if isinstance(raw, list):
            return raw
    return None


def _clean_assignment_suggestion_items(raw_list: list[Any], n: int) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    seen_lower: set[str] = set()
    for item in raw_list:
        if len(cleaned) >= n:
            break
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or str(item.get("baslik", item.get("konu", ""))).strip()
        summary = str(item.get("summary", item.get("ozet", ""))).strip()
        desc = _strip_md_leaks(str(item.get("description", item.get("aciklama", "")))).strip()
        if not title:
            continue
        if not desc:
            desc = summary
        if not desc:
            desc = (
                f"{title} konusunda ogrenciler problemi modullere bolmeli, "
                "kenar durumlarini test etmeli ve tasarim kararlarini kisa bir raporda aciklamalidir."
            )
        tl = title.lower()
        if tl in seen_lower:
            continue
        seen_lower.add(tl)
        cleaned.append({
            "title": title,
            "summary": summary[:200],
            "description": desc,
        })
    return cleaned


_OOP_FALLBACK_SUGGESTIONS: list[dict[str, str]] = [
    {
        "title": "Nesne yonelimli kutuphane katalogu",
        "summary": "Kitap, uye ve odunc siniflariyla basit kutuphane is akisi.",
        "description": (
            "Ogrenciler en az uc sinif tanimlar: Kitap (baslik, yazar, ISBN), Uye ve Kutuphane. "
            "Odunc alma ve iade metotlarla kapsullenir; mevcut olmayan kitap veya limit asimi gibi "
            "kenar durumlari hata mesajlariyla yonetilir. Komut satirindan ornek senaryolar calistirilir."
        ),
    },
    {
        "title": "E-ticaret sepeti ve siparis modeli",
        "summary": "Urun, Sepet ve Siparis siniflari; miktar ve stok kontrolu.",
        "description": (
            "Urun, SepetSatiri ve Siparis siniflari composition ile birlestirilir. Sepete ekleme, guncelleme "
            "ve checkout akisi kurulur. Stok ve negatif miktar kontrolleri sinif icinde tutulur; kisa test "
            "listesi teslim edilir."
        ),
    },
    {
        "title": "Basit sinif hiyerarsisi: Sekil ve alt siniflar",
        "summary": "Soyut Sekil, Dikdortgen, Daire; alan ve cevre hesabi.",
        "description": (
            "Sekil soyut sinifinda alan() ve cevre() icin arayuz belirlenir. Dikdortgen ve Daire opsiyonel "
            "olarak renk veya katman ozelligiyle genisletilir. Ornekleri main icinde cok bicimli cagriyla gosterin."
        ),
    },
    {
        "title": "Oyun karakteri ve seviye yonetimi (OOP)",
        "summary": "Oyuncu, NPC, esya arayuzu veya temel envanter.",
        "description": (
            "Oyuncu ve NPC ortak bir Karakter tabanindan turer; enerji, konum ve hareket metotlari ayrilir. "
            "Basit bir OyunMotoru sinifi turleri dondurur ve etkilesim olaylarini koordine eder."
        ),
    },
    {
        "title": "Ogrenci transkripti ve ders notu raporu",
        "summary": "Ders, Donem ve Ogrenci nesneleriyle not ortalamasi.",
        "description": (
            "Ders (kod, kredi, not), Ogrenci ve Transkript siniflari tasarlanir. Agirlikli GPA veya basit "
            "ortalama hesabi metotlara bolunur. Ayni dersten tekrar gibi kurallar yorum satiri veya "
            "kısa dokumanda aciklanir."
        ),
    },
]

_DS_FALLBACK_SUGGESTIONS: list[dict[str, str]] = [
    {
        "title": "Hash tablosu ile kelime frekans sayaci",
        "summary": "Metin dosyasinda kelime sayimi ve en sik N kelime.",
        "description": (
            "Ogrenciler acik adresleme veya zincirleme olmadan dilinin sozluk/map yapisini kullanabilir; "
            "niyet buyuk veri icin O(1) ortalama erisimdir. Noktalama ve buyuk/kucuk harf normalize edilir. "
            "Ornek girdi ve beklenen cikti aciklanir."
        ),
    },
    {
        "title": "Yigin tabanli ifade hesaplayici",
        "summary": "Postfix ifadelerinde iki yigin veya tek yigin algoritmasi.",
        "description": (
            "Oncelik ve parantez destegi istege bagli olarak kapsamlenir. Gecersiz ifade icin hata "
            "mesajlari verilir. Kisa birim testleri veya manuel test tablosu teslim edilir."
        ),
    },
    {
        "title": "Yonlu graf uzerinde BFS/DFS ile erisim",
        "summary": "Komsuluk listesi ve baslangictan ulasilabilir dugumler.",
        "description": (
            "Graf dugum ve kenarlardan olusur; BFS ve DFS ayri metotlar olarak kodlanir. Baslangic dugumunden "
            "ulasilabilen kume ve yol varligi sorusu cevaplanir. Ornek graf dosya veya kod icinde sabitlenebilir."
        ),
    },
    {
        "title": "Ikili arama agacinda sozluk",
        "summary": "Ekleme, silme, arama ve sirali gezinme.",
        "description": (
            "Anahtar olarak string veya tam sayi kullanilir. Silme durumunda uc durum (yaprak, tek cocuk, iki cocuk) "
            "aciklanir. Agacin dengelenmesi zorunlu degildir; ancak dengesiz giris icin ornek verilir."
        ),
    },
    {
        "title": "Bagli liste ile polinom temsili",
        "summary": "Terim derecesi ve katsayisi; toplama veya carpma.",
        "description": (
            "Her dugum bir terimi temsil eder; polinomlar dereceye gore siralanabilir. Sifir katsayili terimler "
            "temizlenir. Ornek polinomlar ve beklenen sonuc konsol ciktisiyla dogrulanir."
        ),
    },
]


_MATH_FALLBACK_BY_TIER: dict[str, list[dict[str, str]]] = {
    "easy": [
        {
            "title": "Basit faktoriyel ve tam bölünürlük kontrolü",
            "summary": "Küçük n için n! ve bölen listesi; konsol I/O.",
            "description": (
                "Öğrenci doğal sayı n okur, n! değerini (n üst sınırı küçük tutulur, taşma uyarısı yazılır) hesaplar "
                "ve ayrı bir sayının belirli küçük bölenlerini listeler. Fonksiyonlara bölünmüş iki–üç kısa işlev "
                "yeterli; tek ana program dosyası ile teslim. Kenar durumu: n sıfır, negatif giriş için net mesaj."
            ),
        },
        {
            "title": "Ikinci dereceden denklemin kökleri",
            "summary": "Diskriminant ile gerçek/tekil/kök yok durumları.",
            "description": (
                "Katsayılar a, b, c okunur; diskriminant ile kök sayısı ayırt edilir ve varsa kökler yazdırılır. "
                "Kök yok durumunda kullanıcıya açıklayıcı çıktı verilir. Fonksiyon tabanlı yapı; float girişleri "
                "kabul edilir. Örnek test değerleri açıklamada verilir."
            ),
        },
        {
            "title": "EBOB–EKOK hesaplayıcı",
            "summary": "İki pozitif tam sayı için öklid ve çarpım ilişkisi.",
            "description": (
                "İki pozitif tam sayı için EBOB (öklid) ve EKOK hesaplanır. Kullanıcı dostu hata mesajları; "
                "sıfır veya negatif için reddet. Sonuç tek satırda Özetlenir. Toplamda birkaç kısa fonksiyon ile "
                "sınırlı kapsamda tutulur."
            ),
        },
        {
            "title": "Fibonacci dizisinin ilk n terimi",
            "summary": "Döngü veya iki değişken; n üst sınırı küçük.",
            "description": (
                "n okunur (ör. en fazla 30), Fibonacci dizisi üretilir ve yazdırılır. Terimler liste veya dizi "
                "ile tutulabilir. n=0 veya 1 kenar durumları açıklamada tanımlı olmalıdır. Matematik ile ilgili "
                "saf ve kısa bir ödev olarak tasarlanır."
            ),
        },
        {
            "title": "Aritmetik dizi toplamı",
            "summary": "İlk terim, adım sayısı ve ortak fark ile sum(a1..an).",
            "description": (
                "Başlangıç terimi a1, ortak fark d ve terim sayısı k ile aritmetik dizinin ilk k teriminin toplamı "
                "hesaplanır. Formül n*(2*a1+(n-1)*d)/2 veya döngü ile doğrulanabilir gösterilir. Küçük tamsayı girişleri; "
                "kenar durumları k≤0 için mesaj verilir."
            ),
        },
    ],
    "medium": [
        {
            "title": "Bölme yöntemi ile kök bulma",
            "summary": "[a,b] aralığında sürekli f için iki uç işaret kontrolü ve iterasyon.",
            "description": (
                "Verilen sürekli f(x) (ör. polinom kodda sabit fonksiyon) için kullanıcı aralığı [a,b] girer; "
                "f(a)f(b)<0 değilse hata döner. Biseksiyon veya regula falsi ile köke yaklaşım, tolerans veya "
                "maksimum iterasyon ile durur. Adım sayısı ve son yaklaşık kök raporlanır."
            ),
        },
        {
            "title": "3×3 matris determinantı",
            "summary": "Sarrus veya küçük açılım formülü; dosya girişi opsiyonel.",
            "description": (
                "9 sayı konsoldan okunur, 3×3 determinant hesaplanır ve yazdırılır. Hatalı girişlerde doğrulama. "
                "İstenirse matris yazdırma fonksiyonu eklenir. Öğrenci formül seçimini açıklamada kısaca özetler."
            ),
        },
        {
            "title": "Euler yöntemi ile basit ODE",
            "summary": "y'=f(x,y), başlangıç ve adım ile birkaç adım çözüm.",
            "description": (
                "Örnek f(x,y) (örneğin y'=-y veya sabit düşük karmaşıklıkta ifade) verilir. x0,y0,h ve adım sayısı "
                "alındıktan sonra Euler güncellenmesi yapılır, her adımda (x,y) tablo şeklinde yazdırılır. "
                "Kanıt gerektirmeden nümerik yaklaşım odaklı ödevdir."
            ),
        },
        {
            "title": "İki vektörün iç çarpımı ve aradaki açı",
            "summary": "Uzunluk ve kosinüs yasası ile derece çıktısı.",
            "description": (
                "2D veya 3D iki vektör okunur; iç çarpım, normlar hesaplanır ve aradaki açı radyanı/derecesi olarak "
                "yazılır. Sıfır vektöründe uyarı üretilir. Fonksiyon modüler yazılır."
            ),
        },
        {
            "title": "Doğrusal regresyon: en küçük kareler doğrusu",
            "summary": "Nokta dizisi için eğim ve kesim katsayıları.",
            "description": (
                "Küçük n için (xi,yi) çiftleri okunur; ortalamalar kullanılarak en küçük kare doğrusunun eğimi ve "
                "kesiti hesaplanır. Sonuç y = mx + b biçiminde raporlanır. Görsel şart değildir ama özette "
                "formüller yazılmalıdır."
            ),
        },
    ],
    "hard": [
        {
            "title": "Trapéz ve Simpson kuralları karşılaştırması",
            "summary": "Aynı integrali iki yöntemle yaklaşıkla; düğüm sayısı varyasyonu.",
            "description": (
                "[a,b] üzerinde verilen sürekli f için kullanıcı n panel sayısı girer (çift gereksinimi Simpson için "
                "açıklamada sabitlenir). Trapéz ve Simpson yaklaşım değerleri hesaplanır, tabloda sunulur; panel sayısı "
                "artan iki senaryoda fark gözlenir ve kısa yorum teslim gereksinimi vardır. Modüller ve sabit kod "
                "yorumları ile çok dosya yapısı teşvik edilir."
            ),
        },
        {
            "title": "Jacobi veya Gauss–Seidel ile küçük doğrusal sistem",
            "summary": "3×3 veya 4×4 diyagonal baskın sistem; yakınsama takibi.",
            "description": (
                "Katı sıra koşulu sağlayan küçük A matrisi ve b vektörü verilir. İteratif yöntem uygulanır; "
                "her adımda çözüm vektörü ve uygun norm farkı kaydedilir. Toleransa veya maksimum iterasyona göre durur; "
                "yakınsamazsa uyarı yazılır. Öğrenci algoritma adımlarını kod olarak açıklar."
            ),
        },
        {
            "title": "Gradyan iniş ile basit doğrusal regresyon",
            "summary": "Maliyet fonksiyonu ve öğrenme oranı seçimi ile eğim-kesite yakınsama.",
            "description": (
                "(xi,yi) küçük veri kümesinde MSE küçültülerek m ve b güncellenir; iterasyon veya küçük adım dizisi "
                "çıktılır. Öğrenme oranı ve çıkış kriterleri açıklamada bağlanmış olmalı; son katsayıların analitik çözümle "
                "karşılaştırması istenir. Kenar örneklerde yakınsamama için kılavuz verilir."
            ),
        },
        {
            "title": "Boyut küçültme (mini PCA görünümü)",
            "summary": "Küçük X matrisi için kovaryans ve özvektör fikrine dayalı doğrusal dönüşüm.",
            "description": (
                "Öğrenci merkezi matris oluşturur, X^T X veya doğrudan özdeğer ayrışımına denk küçük adımlarla "
                "yüksek bilgi oranı bileşeni seçilir (Örn. ilk ana bileşene projeksiyon). Veri seti çok küçük tutulur (ör. "
                "5×3). Matematik adımların kodda uyumunu ve kısa yorum teslim şartını ekleyin."
            ),
        },
        {
            "title": "Sabit-nokta yinelemesi: iki g(x) ile yakınsama karşılaştırması",
            "summary": "x=g(x) biçimi için iki seçim ile yakınsama hızı.",
            "description": (
                "Aynı köke iki farklı g(x) seçimi tanımlanır; kullanıcı başlangıç ve tolerans verir; her seçim için "
                "iterasyon sayısı ve son değerler raporlanır. Yakınşamayan seçim için hata yakalama. Çok-parçalı "
                "işlev yapısı ve test senaryoları zorunludur."
            ),
        },
    ],
}


def _fallback_assignment_suggestions(course_hint: str, difficulty: str | None = None) -> list[dict[str, str]]:
    hint = (course_hint or "").lower()
    tier = _normalize_assignment_difficulty(difficulty)
    math_hint = any(
        m in hint
        for m in (
            "matematik", "matematı", "math", "matem", "sayisal", "sayısal", "numerik", "numerical",
            "matris", "vektör", "vektor", "polinom", "denklem", "integral", "türev", "turev", "lineer cebir",
        )
    )
    oop = any(
        m in hint
        for m in (
            "sinif", "sınıf", "siniflar", "sinifla", "nesne", "oop", "class",
            "kalitim", "kalıtım", "kapsul", "kapsül", "soyut", "arayuz", "arayüz",
        )
    )
    primary = list(_OOP_FALLBACK_SUGGESTIONS if oop else _DS_FALLBACK_SUGGESTIONS)
    secondary = list(_DS_FALLBACK_SUGGESTIONS if oop else _OOP_FALLBACK_SUGGESTIONS)
    merged = primary + [x for x in secondary if x["title"] not in {p["title"] for p in primary}]
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    tier_math_rows = list(_MATH_FALLBACK_BY_TIER.get(tier) or _MATH_FALLBACK_BY_TIER["medium"])
    if math_hint:
        for row in tier_math_rows:
            k = row["title"].lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(dict(row))
    for row in merged:
        k = row["title"].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(dict(row))
    return out


class TeacherEmailUpdateRequest(BaseModel):
    email: str


class TeacherPasswordUpdateRequest(BaseModel):
    current_password: str | None = None
    new_password: str


class StudentCreateRequest(BaseModel):
    student_no: str
    tc_no: str
    first_name: str
    last_name: str
    class_year: int | None = None
    department_id: str | None = None


class StudentUpdateRequest(BaseModel):
    student_no: str
    tc_no: str
    first_name: str
    last_name: str
    class_year: int | None = None
    department_id: str | None = None


# ---- Severity mapping: backend -> frontend ----

_SEVERITY_MAP = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "info",
    "suggestion": "info",
    "info": "info",
}


def _map_severity(sev: str) -> str:
    return _SEVERITY_MAP.get(sev, "info")


def _parse_class_year(raw_value: int | None) -> int:
    if raw_value is None:
        raise HTTPException(status_code=400, detail="Sinif secimi zorunludur")
    try:
        class_year = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Gecersiz sinif secimi") from exc
    if class_year not in {1, 2, 3, 4}:
        raise HTTPException(status_code=400, detail="Gecersiz sinif secimi")
    return class_year


async def _get_db_pool() -> asyncpg.Pool:
        if _DB_POOL is None:
                raise HTTPException(status_code=500, detail="Veritabani baglantisi hazir degil")
        return _DB_POOL


def _demo_now() -> str:
    return datetime.utcnow().isoformat()


def _demo_uuid() -> str:
    return str(uuid.uuid4())


def _parse_assignment_uuid_param(assignment_id: str) -> uuid.UUID:
    """Path parametresindeki odev kimligini UUID yapar (PostgreSQL ile tutarli karsilastirma)."""
    s = (assignment_id or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="Odev kimligi bos")
    try:
        return uuid.UUID(s)
    except ValueError:
        raise HTTPException(status_code=400, detail="Gecersiz odev kimligi")


def _build_dsn_with_database(dsn: str, database: str) -> str:
    parsed = urlparse(dsn)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("Gecersiz DATABASE_URL")

    auth = parsed.username or ""
    if parsed.password is not None:
        auth += f":{parsed.password}"
    if auth:
        auth += "@"

    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"

    return urlunparse((parsed.scheme, f"{auth}{host}", f"/{database}", parsed.params, parsed.query, parsed.fragment))


async def _ensure_database_exists(dsn: str) -> None:
    parsed = urlparse(dsn)
    target_database = parsed.path.lstrip("/") or "postgres"
    admin_dsn = _build_dsn_with_database(dsn, "postgres")

    admin_conn = await asyncpg.connect(dsn=admin_dsn)
    try:
        exists = await admin_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            target_database,
        )
        if not exists:
            await admin_conn.execute(f'CREATE DATABASE "{target_database}"')
            print(f"[mentor-api] Veritabani olusturuldu: {target_database}", flush=True)
    finally:
        await admin_conn.close()


async def _sync_course_to_all_students(pool: asyncpg.Pool, course_id: str) -> None:
    await pool.execute(
        """
        INSERT INTO public.student_courses (student_id, course_id)
        SELECT s.id, $1
        FROM public.students s
        JOIN public.courses c ON c.id = $1
        WHERE (c.department_id IS NULL OR c.department_id = s.department_id)
          AND (c.class_year IS NULL OR c.class_year = s.class_year)
        ON CONFLICT (student_id, course_id) DO NOTHING
        """,
        course_id,
    )


async def _sync_student_to_all_courses(pool: asyncpg.Pool, student_id: str) -> None:
    await pool.execute(
        """
        INSERT INTO public.student_courses (student_id, course_id)
        SELECT $1, c.id
        FROM public.courses c
        JOIN public.students s ON s.id = $1
        WHERE (c.department_id IS NULL OR c.department_id = s.department_id)
          AND (c.class_year IS NULL OR c.class_year = s.class_year)
        ON CONFLICT (student_id, course_id) DO NOTHING
        """,
        student_id,
    )


def _student_duplicate_message(
    student_no: str,
    tc_no: str,
    first_name: str,
    last_name: str,
    conflict_field: str | None = None,
) -> str:
    if conflict_field == "student_no":
        return f"{student_no} ogrenci no zaten kayitli oldugu icin eklenmedi"
    if conflict_field == "tc_no":
        return f"{tc_no} TC no zaten kayitli oldugu icin eklenmedi"
    return f"{student_no} / {tc_no} - {first_name} {last_name} zaten kayitli oldugu icin eklenmedi"


def _student_csv_message(
    student_no: str,
    tc_no: str,
    first_name: str,
    last_name: str,
    conflict_field: str | None = None,
) -> str:
    return _student_duplicate_message(student_no, tc_no, first_name, last_name, conflict_field)


_TC_NO_PATTERN = re.compile(r"^\d{11}$")


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _tr_lower(value: str) -> str:
    return value.translate(str.maketrans({"I": "ı", "İ": "i"})).lower()


def _tr_upper(value: str) -> str:
    return value.translate(str.maketrans({"i": "İ", "ı": "I"})).upper()


def _title_case_tr(value: str) -> str:
    normalized = _normalize_whitespace(value)
    if not normalized:
        return ""
    words = []
    for word in normalized.split(" "):
        lowered = _tr_lower(word)
        words.append((_tr_upper(lowered[:1]) + lowered[1:]) if lowered else "")
    return " ".join(words)


def _normalize_student_first_name(value: str) -> str:
    return _title_case_tr(value)


def _normalize_student_last_name(value: str) -> str:
    return _tr_upper(_normalize_whitespace(value))


def _normalize_department_title(value: str) -> str:
    return _title_case_tr(value)


def _is_valid_tc_no(value: str) -> bool:
    return _TC_NO_PATTERN.fullmatch(value) is not None


def _demo_student_conflict_field(
    students: list[dict[str, Any]],
    student_no: str,
    tc_no: str,
    exclude_id: str | None = None,
) -> str | None:
    for student in students:
        if exclude_id and student.get("id") == exclude_id:
            continue
        if student.get("student_no") == student_no:
            return "student_no"
        if student.get("tc_no") == tc_no:
            return "tc_no"
    return None


def _demo_department_name(department_id: str | None) -> str | None:
    if not department_id:
        return None
    department = next((d for d in _DEMO_STORE["departments"] if d["id"] == department_id), None)
    if not department:
        return None
    return _normalize_department_title(str(department["name"]))


def _normalize_student_record_department(student: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(student)
    department_name = normalized.get("department_name")
    if isinstance(department_name, str) and department_name.strip():
        normalized["department_name"] = _normalize_department_title(department_name)
    return normalized


def _demo_student_record(student: dict[str, Any]) -> dict[str, Any]:
    return {
        **student,
        "department_name": _demo_department_name(student.get("department_id")),
    }


async def _fetch_student_row(pool: asyncpg.Pool, student_id: str):
    return await pool.fetchrow(
        """
        SELECT s.id, s.student_no, s.tc_no, s.first_name, s.last_name, s.class_year, s.department_id,
               d.name AS department_name, s.created_at
        FROM public.students s
        LEFT JOIN public.departments d ON d.id = s.department_id
        WHERE s.id = $1
        LIMIT 1
        """,
        student_id,
    )


async def _student_conflict_field(
    pool: asyncpg.Pool,
    student_no: str,
    tc_no: str,
    exclude_id: str | None = None,
) -> str | None:
    if exclude_id:
        found = await pool.fetchrow(
            """
            SELECT student_no, tc_no
            FROM public.students
            WHERE (student_no = $1 OR tc_no = $2) AND id <> $3
            LIMIT 1
            """,
            student_no,
            tc_no,
            exclude_id,
        )
    else:
        found = await pool.fetchrow(
            """
            SELECT student_no, tc_no
            FROM public.students
            WHERE student_no = $1 OR tc_no = $2
            LIMIT 1
            """,
            student_no,
            tc_no,
        )
    if not found:
        return None
    if found["student_no"] == student_no:
        return "student_no"
    if found["tc_no"] == tc_no:
        return "tc_no"
    return None


async def _ensure_db_schema(pool: asyncpg.Pool) -> None:
        await pool.execute("""
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        CREATE TABLE IF NOT EXISTS public.students (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            student_no TEXT NOT NULL UNIQUE,
            tc_no TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            class_year SMALLINT NULL,
            department_id UUID NULL REFERENCES public.departments(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        ALTER TABLE public.students
            DROP CONSTRAINT IF EXISTS students_student_no_key;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'students_student_no_tc_no_key'
                  AND conrelid = 'public.students'::regclass
            ) THEN
                ALTER TABLE public.students
                    ADD CONSTRAINT students_student_no_tc_no_key UNIQUE (student_no, tc_no);
            END IF;
        END $$;

        CREATE TABLE IF NOT EXISTS public.courses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            class_year SMALLINT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS public.teachers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS public.departments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            created_by UUID REFERENCES public.teachers(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        ALTER TABLE public.students
            ADD COLUMN IF NOT EXISTS class_year SMALLINT;

        ALTER TABLE public.students
            ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES public.departments(id) ON DELETE SET NULL;

        ALTER TABLE public.courses
            ADD COLUMN IF NOT EXISTS class_year SMALLINT;

        ALTER TABLE public.courses
            ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES public.departments(id) ON DELETE SET NULL;

        CREATE TABLE IF NOT EXISTS public.student_courses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            student_id UUID NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
            course_id UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
            UNIQUE(student_id, course_id)
        );

        CREATE TABLE IF NOT EXISTS public.assignments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            course_id UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        ALTER TABLE public.assignments
            ADD COLUMN IF NOT EXISTS due_date TIMESTAMPTZ NULL;

        CREATE TABLE IF NOT EXISTS public.rubrics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
            criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
            created_by UUID REFERENCES public.teachers(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        ALTER TABLE public.rubrics
            ADD COLUMN IF NOT EXISTS criteria JSONB NOT NULL DEFAULT '[]'::jsonb;

        ALTER TABLE public.rubrics
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft';

        ALTER TABLE public.rubrics
            ADD COLUMN IF NOT EXISTS created_by UUID NULL REFERENCES public.teachers(id) ON DELETE SET NULL;

        ALTER TABLE public.rubrics
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

        CREATE TABLE IF NOT EXISTS public.student_upload_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            student_first_name TEXT NOT NULL,
            student_last_name TEXT NOT NULL,
            student_no TEXT NOT NULL,
            uploaded_file_name TEXT NOT NULL,
            assignment_id UUID NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
            score INTEGER NULL,
            has_error BOOLEAN NOT NULL DEFAULT false,
            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        ALTER TABLE public.student_upload_history
            ADD COLUMN IF NOT EXISTS assignment_id UUID NULL REFERENCES public.assignments(id) ON DELETE CASCADE;

        ALTER TABLE public.student_upload_history
            ADD COLUMN IF NOT EXISTS score INTEGER NULL;

        ALTER TABLE public.student_upload_history
            ADD COLUMN IF NOT EXISTS has_error BOOLEAN NOT NULL DEFAULT false;

        CREATE INDEX IF NOT EXISTS idx_student_upload_history_student_no
            ON public.student_upload_history(student_no);

        CREATE INDEX IF NOT EXISTS idx_student_upload_history_uploaded_at
            ON public.student_upload_history(uploaded_at DESC);

        CREATE INDEX IF NOT EXISTS idx_student_upload_history_assignment_id
            ON public.student_upload_history(assignment_id);

        CREATE INDEX IF NOT EXISTS idx_students_department_id
            ON public.students(department_id);

        CREATE INDEX IF NOT EXISTS idx_courses_department_id
            ON public.courses(department_id);

        CREATE INDEX IF NOT EXISTS idx_rubrics_assignment_id
            ON public.rubrics(assignment_id);

        CREATE TABLE IF NOT EXISTS public.question_bank (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT 'blue',
            created_by UUID NULL REFERENCES public.teachers(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        ALTER TABLE public.question_bank
            ADD COLUMN IF NOT EXISTS color TEXT NOT NULL DEFAULT 'blue';

        ALTER TABLE public.question_bank
            ADD COLUMN IF NOT EXISTS created_by UUID NULL REFERENCES public.teachers(id) ON DELETE SET NULL;

        ALTER TABLE public.question_bank
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

        ALTER TABLE public.question_bank
            DROP COLUMN IF EXISTS labels;

        CREATE TABLE IF NOT EXISTS public.assignment_questions (
            assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
            question_id UUID NOT NULL REFERENCES public.question_bank(id) ON DELETE CASCADE,
            display_order INTEGER NOT NULL DEFAULT 1,
            selected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (assignment_id, question_id)
        );

        CREATE INDEX IF NOT EXISTS idx_assignment_questions_assignment_id
            ON public.assignment_questions(assignment_id, display_order ASC, selected_at DESC);

        CREATE INDEX IF NOT EXISTS idx_assignment_questions_question_id
            ON public.assignment_questions(question_id);

        CREATE INDEX IF NOT EXISTS idx_question_bank_created_at
            ON public.question_bank(created_at DESC);
        """)


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 120000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iteration_text, salt, hash_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz tarih formatı") from exc


# ---- Sandbox simulation ----

def _simulate_sandbox(source_code: str) -> dict:
    """AST parse + subprocess ile basit sandbox simulasyonu."""
    result = {
        "stdout": "",
        "stderr": "",
        "exit_code": 0,
        "execution_time_ms": 0,
        "peak_memory_mb": 0.0,
        "compilation_success": False,
    }

    try:
        ast.parse(source_code)
        result["compilation_success"] = True
    except SyntaxError as e:
        result["stderr"] = f"SyntaxError: {e.msg} (line {e.lineno})"
        result["exit_code"] = 1
        return result

    try:
        proc = subprocess.run(
            [sys.executable, "-c", source_code],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=os.path.dirname(__file__) or ".",
        )
        result["stdout"] = proc.stdout
        result["stderr"] = proc.stderr
        result["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        result["stderr"] = "TimeoutError: Kod 10 saniye icinde tamamlanamadi"
        result["exit_code"] = 1
    except Exception as e:
        result["stderr"] = str(e)
        result["exit_code"] = 1

    return result


# ---- Ana pipeline ----


async def _fetch_assignment_brief_for_pipeline(assignment_id: str | None) -> str:
    """Ödev başlığı ve açıklamasını veritabanı veya demo store'dan yükler (analiz prompt'u)."""
    if not assignment_id or not str(assignment_id).strip():
        return ""
    aid = str(assignment_id).strip()
    try:
        uuid.UUID(aid)
    except (ValueError, AttributeError):
        return ""

    if _DEMO_MODE:
        for a in _DEMO_STORE.get("assignments", []):
            if str(a.get("id")) == aid:
                title = (a.get("name") or "").strip()
                desc = (a.get("description") or "").strip()
                parts: list[str] = []
                if title:
                    parts.append(f"Ödev başlığı / Assignment title: {title}")
                if desc:
                    parts.append(f"Ödev açıklaması / Assignment description:\n{desc}")
                return "\n\n".join(parts) if parts else ""
        return ""

    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT name, description
        FROM public.assignments
        WHERE id = $1::uuid
        LIMIT 1
        """,
        aid,
    )
    if not row:
        return ""
    title = (row["name"] or "").strip()
    desc = (row["description"] or "").strip() if row["description"] else ""
    parts = []
    if title:
        parts.append(f"Ödev başlığı / Assignment title: {title}")
    if desc:
        parts.append(f"Ödev açıklaması / Assignment description:\n{desc}")
    return "\n\n".join(parts) if parts else ""


async def _fetch_faculty_rubric_criteria_for_pipeline(assignment_id: str | None) -> list[dict[str, Any]]:
    """Ödev icin kayitli rubrik kriterlerini (name, description, max_score) yukler."""
    from backend.agents.master_evaluator import normalize_faculty_rubric_criteria

    if not assignment_id or not str(assignment_id).strip():
        return []
    aid = str(assignment_id).strip()
    try:
        uuid.UUID(aid)
    except (ValueError, AttributeError):
        return []

    if _DEMO_MODE:
        row = next((r for r in _DEMO_STORE.get("rubrics", []) if r.get("assignment_id") == aid), None)
        if not row:
            return []
        return normalize_faculty_rubric_criteria(row.get("criteria"))

    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT criteria
        FROM public.rubrics
        WHERE assignment_id = $1::uuid
        LIMIT 1
        """,
        aid,
    )
    if not row or row["criteria"] is None:
        return []
    crit = row["criteria"]
    if isinstance(crit, str):
        try:
            crit = json.loads(crit)
        except json.JSONDecodeError:
            return []
    return normalize_faculty_rubric_criteria(crit)


async def run_analysis_pipeline(
    file_name: str,
    file_content: str,
    *,
    assignment_brief: str = "",
    faculty_rubric_criteria: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tracemalloc.start()
    start_time = time.time()

    language = "python"
    if file_name.endswith((".c", ".cpp", ".h")):
        language = "c++"
    elif file_name.endswith(".java"):
        language = "java"

    brief = (assignment_brief or "").strip()
    fac = list(faculty_rubric_criteria) if faculty_rubric_criteria else []
    if fac:
        print(f"[pipeline] Ogretmen rubrigi: {len(fac)} kriter", flush=True)

    from backend.agents.assignment_alignment import (
        BRIEF_MIN_LEN,
        _rubric_criteria_text,
        compute_brief_code_alignment,
    )
    from backend.agents.task_relevance import assess_task_relevance_llm, merge_task_alignment

    prog_f, prog_rs = compute_brief_code_alignment(
        brief, file_content, rubric_criteria=fac if fac else None
    )
    llm_rel = await assess_task_relevance_llm(
        assignment_description=brief,
        source_code=file_content,
        rubric_criteria=fac if fac else None,
        report_language="tr",
    )
    task_alignment = merge_task_alignment(prog_f, prog_rs, llm_rel)
    if not task_alignment.get("llm_skipped"):
        print(
            f"[pipeline] Gorev uyumu: programatik={task_alignment['programmatic_factor']:.3f} "
            f"llm={task_alignment.get('llm_factor')} birlesik={task_alignment['factor']:.3f}",
            flush=True,
        )
    else:
        print(
            f"[pipeline] Gorev uyumu: programatik={task_alignment['programmatic_factor']:.3f} "
            f"(LLM atlandi veya baglam yetersiz)",
            flush=True,
        )

    inp = {
        "source_code": file_content,
        "language": language,
        "report_language": "tr",
        "assignment_description": brief,
        "task_alignment": task_alignment,
    }

    from backend.core.config import settings as _cfg
    print(f"[pipeline] OLLAMA_ENABLED={_cfg.ollama_enabled}, MODEL={_cfg.ollama_model}", flush=True)

    loop = asyncio.get_running_loop()
    from backend.sandbox.executor import run_in_sandbox

    # 1) Tum bagimsiz isler PARALEL: statik ajanlar + (sandbox -> TestAgent)
    print("[pipeline] Paralel katman basliyor (statik + sandbox->test)...", flush=True)

    async def _run_static():
        cq, sn, gl, sc = await asyncio.gather(
            CodeQualityAgent().analyze(inp),
            SeniorityAgent().analyze(inp),
            GuidelineAgent().analyze(inp),
            SecurityAgent().analyze(inp),
        )
        return cq, sn, gl, sc

    async def _run_sandbox_then_test():
        sb = await loop.run_in_executor(None, run_in_sandbox, file_content, language)
        ta = await TestAgent().analyze({
            "sandbox_result": sb,
            "expected_output": "",
            "source_code": file_content,
            "language": language,
            "report_language": "tr",
            "assignment_description": brief,
            "faculty_rubric_criteria": fac,
            "task_alignment": task_alignment,
        })
        return sb, ta

    (cq, sn, gl, sc), (sandbox_result, ta) = await asyncio.gather(
        _run_static(),
        _run_sandbox_then_test(),
    )
    print(f"[pipeline] Paralel katman bitti (CQ={cq.get('score')}, SN={sn.get('score')}, GL={gl.get('score')}, SC={sc.get('score')}, TA={ta.get('score')})", flush=True)

    # 2) Evidence Agent (tüm ajanlara bağımlı)
    print("[pipeline] EvidenceAgent basliyor...", flush=True)
    ev = await EvidenceAgent().analyze({
        "source_code": file_content,
        "language": language,
        "report_language": "tr",
        "assignment_description": brief,
        "agent_findings": {
            "code_quality": cq,
            "test_agent": ta,
            "seniority": sn,
            "guideline": gl,
            "security": sc,
        },
    })
    print(f"[pipeline] EvidenceAgent bitti (validated={ev.get('total_claims_validated')})", flush=True)

    # 3) Master Evaluator
    print("[pipeline] MasterEvaluator basliyor...", flush=True)
    me_payload: dict[str, Any] = {
        "evidence": ev,
        "sandbox_result": sandbox_result,
        "code_quality": cq,
        "test_agent": ta,
        "seniority": sn,
        "guideline": gl,
        "security": sc,
        "report_language": "tr",
        "language": language,
        "assignment_description": brief,
        "task_alignment": task_alignment,
    }
    if fac:
        me_payload["faculty_rubric_criteria"] = fac
    me_payload["source_code"] = file_content
    final = await MasterEvaluatorAgent().analyze(me_payload)
    print(f"[pipeline] MasterEvaluator bitti (final_score={final.get('final_score')})", flush=True)

    # Timing & memory
    elapsed_ms = int((time.time() - start_time) * 1000)
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # ---- Frontend ApiAnalysisResult formatina donustur ----

    # Rubric
    rubric = []
    for item in final.get("rubric_breakdown", []):
        w = int(item.get("weight", 100))
        raw_score = float(item.get("score", 0))
        # Default evaluator rows use 0..100 scores, faculty rows use 0..weight points.
        # The frontend expects points against maxScore=weight, so normalize percent-like rows.
        if w > 0 and raw_score > w:
            item_score = int(round(raw_score * w / 100.0))
        else:
            item_score = int(round(raw_score))
        item_score = max(0, min(w, item_score))
        rubric.append({
            "name": item.get("label", item.get("criterion", "")),
            "weight": w,
            "score": item_score,
            "maxScore": w,
        })

    # Agent raporlari
    agents_list = _build_agents_list(cq, sn, gl, sc, ta, ev)

    # Line evidence
    evidence_lines = _build_line_evidence(cq, gl, sc, ev, file_content)

    total_score = final.get("final_score", 0)
    total_score_rounded = int(round(float(total_score or 0)))

    _ctx = "\n".join(
        x for x in (brief, _rubric_criteria_text(fac if fac else None)) if x
    ).strip()
    _align_f = float(task_alignment.get("factor", 1.0) or 1.0)
    _llm_off_topic = bool(task_alignment.get("llm_off_topic"))
    _align_reasons = task_alignment.get("reasons", [])
    _has_off_topic_reason = isinstance(_align_reasons, list) and any(
        reason in {"llm_task_relevance_off_topic", "llm_task_not_fulfilled", "llm_low_task_fit"}
        for reason in _align_reasons
    )
    relevance_score_warning: str | None = None
    if len(_ctx) >= BRIEF_MIN_LEN and (_llm_off_topic or _align_f <= 0.20 or _has_off_topic_reason):
        relevance_score_warning = (
            "Gorev uyumu zayif: bu teslim buyuk olasilikla odev/rubrik ile alakasiz "
            "veya yanlis dosya olabilir. Kod dusuk puan almis olsa bile ana sorun konu uyumsuzlugu."
        )
        if not any(
            isinstance(item, dict) and item.get("agent") == "Gorev Uyumu"
            for item in evidence_lines
        ):
            evidence_lines.append({
                "line": 1,
                "agent": "Gorev Uyumu",
                "message": "Teslim odev/rubrik ile alakasiz gorunuyor (topic mismatch).",
                "severity": "warning",
            })
            evidence_lines.sort(key=lambda x: x["line"])
    elif (
        len(_ctx) >= BRIEF_MIN_LEN
        and total_score_rounded <= 20
        and _align_f <= 0.35
    ):
        relevance_score_warning = (
            "Nihai puan dusuk ve gorev uyumu da zayif: bu genelde teslimin odev/rubrikle ortusmedigi "
            "veya yanlis dosyanin yuklendigi anlamina gelebilir. Dusuk not her zaman alakasiz kod "
            "demek zorunda degildir; konu dogru olsa bile cozum zayifsa benzer aralikta kalinabilir."
        )

    return {
        "totalScore": total_score_rounded,
        "maxScore": 100,
        "rubric": rubric,
        "agents": agents_list,
        "evidence": evidence_lines,
        "fileName": file_name,
        "executionTimeMs": elapsed_ms,
        "memoryUsageMb": round(current_mem / 1024 / 1024, 1),
        "peakMemoryMb": round(peak_mem / 1024 / 1024, 1),
        "analysisEngine": _ANALYSIS_ENGINE,
        "relevanceScoreWarning": relevance_score_warning,
        "taskAlignment": task_alignment,
    }


def _build_agents_list(cq, sn, gl, sc, ta, ev) -> list[dict]:
    """Her ajan icin frontend'in beklegi formatta rapor olustur."""
    agents = []

    # Testing Agent
    test_findings = []
    for err in ta.get("runtime_errors", []):
        test_findings.append({
            "severity": "error", "message": err,
            "line": None, "agent": "Test Ajanı", "code": None,
        })
    for fail in ta.get("test_failures", []):
        test_findings.append({
            "severity": "error",
            "message": f"Test basarisiz: {fail.get('reason', fail.get('test_name', ''))}",
            "line": None, "agent": "Test Ajanı", "code": None,
        })
    edge_observed = ta.get("edge_cases_observed", []) or []
    if isinstance(edge_observed, list):
        for case in edge_observed[:6]:
            text = str(case).strip()
            if not text:
                continue
            test_findings.append({
                "severity": "info",
                "message": f"Uç durum: {text}",
                "line": None, "agent": "Test Ajanı", "code": None,
            })
    comp_ok = ta.get("compilation_success", False)
    runs_ok = ta.get("runs_successfully", False)
    passed = ta.get("passed_tests", 0)
    failed = ta.get("failed_tests", 0)
    edge_q = ta.get("edge_case_handling")
    if comp_ok and runs_ok:
        summary_ta = f"Derleme basarili, {passed} test gecti"
        if failed:
            summary_ta += f", {failed} basarisiz"
    elif comp_ok:
        summary_ta = "Derleme basarili, calisma hatasi"
    else:
        summary_ta = "Derleme hatasi"
    if isinstance(edge_q, str) and edge_q:
        summary_ta += f" • Uç durum: {edge_q}"
    agents.append({
        "id": "testing",
        "name": "Test Ajanı",
        "summary": summary_ta,
        "score": ta.get("score", 0),
        "maxScore": 100,
        "findings": test_findings,
    })

    # Code Quality Agent
    cq_findings = []
    for issue in cq.get("issues", []):
        cq_findings.append({
            "severity": _map_severity(issue.get("severity", "info")),
            "message": issue.get("description", ""),
            "line": issue.get("line"),
            "agent": "Kod Kalitesi Ajanı",
            "code": None,
        })
    agents.append({
        "id": "quality",
        "name": "Kod Kalitesi Ajanı",
        "summary": f"Karmasiklik: {cq.get('time_complexity', '?')}, Skor: {cq.get('score', 0)}/100",
        "score": cq.get("score", 0),
        "maxScore": 100,
        "findings": cq_findings,
    })

    # Seniority Agent
    sn_findings = []
    for ind in sn.get("immaturity_indicators", []):
        sn_findings.append({
            "severity": "warning", "message": ind,
            "line": None, "agent": "Kıdem Ajanı", "code": None,
        })
    for ind in sn.get("maturity_indicators", []):
        sn_findings.append({
            "severity": "info", "message": ind,
            "line": None, "agent": "Kıdem Ajanı", "code": None,
        })
    agents.append({
        "id": "seniority",
        "name": "Kıdem Ajanı",
        "summary": f"Seviye: {sn.get('estimated_level', '?')}, Skor: {sn.get('score', 0)}/100",
        "score": sn.get("score", 0),
        "maxScore": 100,
        "findings": sn_findings,
    })

    # Guideline Agent
    gl_findings = []
    for viol in gl.get("style_violations", []):
        gl_findings.append({
            "severity": _map_severity(viol.get("severity", "info")),
            "message": viol.get("description", viol.get("rule", "")),
            "line": None, "agent": "Standartlar Ajanı", "code": None,
        })
    agents.append({
        "id": "guideline",
        "name": "Standartlar Ajanı",
        "summary": f"Isimlendirme: {gl.get('naming_quality', '?')}, Skor: {gl.get('score', 0)}/100",
        "score": gl.get("score", 0),
        "maxScore": 100,
        "findings": gl_findings,
    })

    # Security Agent
    sc_findings = []
    for threat in sc.get("threats", []):
        sc_findings.append({
            "severity": _map_severity(threat.get("severity", "high")),
            "message": threat.get("description", ""),
            "line": threat.get("line"),
            "agent": "Güvenlik Ajanı",
            "code": None,
        })
    risk = sc.get("risk_level", "safe").upper()
    threat_count = sc.get("total_threats", 0)
    agents.append({
        "id": "security",
        "name": "Güvenlik Ajanı",
        "summary": f"Risk: {risk}, {threat_count} tehdit, Skor: {sc.get('score', 0)}/100",
        "score": sc.get("score", 0),
        "maxScore": 100,
        "findings": sc_findings,
    })

    # Evidence Agent
    ev_findings = []
    _NODE_TYPE_LABEL_TR = {
        "function": "Fonksiyon",
        "class": "Sınıf",
        "if": "If/elif bloğu",
        "for": "For döngüsü",
        "while": "While döngüsü",
        "try": "Try bloğu",
        "with": "With bloğu",
    }
    for claim in ev.get("validated_claims", []):
        line_range = claim.get("line_range") or []
        node_type = claim.get("node_type")
        symbol = claim.get("symbol")
        feedback = claim.get("feedback", "")
        if isinstance(line_range, list) and len(line_range) == 2:
            type_label = _NODE_TYPE_LABEL_TR.get(node_type or "", "Blok")
            sym_part = f" {symbol}" if symbol else ""
            feedback = (
                f"[{type_label}{sym_part} • satır {line_range[0]}-{line_range[1]}] {feedback}"
            )
        ev_findings.append({
            "severity": _map_severity(claim.get("severity", "info")),
            "message": feedback,
            "line": claim.get("lines", [None])[0] if claim.get("lines") else None,
            "agent": "Kanıtlandırma Ajanı",
            "code": claim.get("code_snippet"),
        })
    for rejected in (ev.get("rejected_claims", []) or [])[:4]:
        if isinstance(rejected, dict):
            text = str(
                rejected.get("reason")
                or rejected.get("feedback")
                or rejected.get("description")
                or rejected
            )
        else:
            text = str(rejected)
        text = text.strip()
        if not text:
            continue
        ev_findings.append({
            "severity": "info",
            "message": f"KanÄ±tlanamayan iddia reddedildi: {text}",
            "line": None,
            "agent": "KanÄ±tlandÄ±rma AjanÄ±",
            "code": None,
        })
    total_claims = ev.get("total_claims_received", 0)
    validated = ev.get("total_claims_validated", 0)
    rejected_count = len(ev.get("rejected_claims", []) or [])
    block_evidence = ev.get("block_evidence_count", 0) or sum(
        1 for c in ev.get("validated_claims", []) if isinstance(c, dict) and c.get("line_range")
    )
    line_evidence = max(0, validated - block_evidence)
    fallback = ev.get("llm_status") == "fallback_programmatic"
    evidence_score = 100 if total_claims == 0 or not fallback else 85

    if total_claims == 0:
        ev_summary = "Diğer ajanlardan eleştiri gelmedi; doğrulanacak bulgu yok."
    else:
        ev_summary = (
            f"{validated}/{total_claims} eleştiri kodda somut delille kanıtlandı "
            f"(blok: {block_evidence}, satır: {line_evidence}"
            + (f", reddedilen: {rejected_count}" if rejected_count else "")
            + "). Bu, doğrulama oranıdır; kod kalite puanı değildir."
        )
        if fallback:
            ev_summary += " (LLM yanıtı eksik geldi, programatik eşleştirme kullanıldı.)"

    agents.append({
        "id": "evidence",
        "name": "Kanıtlandırma Ajanı",
        "summary": ev_summary,
        "score": evidence_score,
        "maxScore": 100,
        "findings": ev_findings,
    })

    return agents


def _build_line_evidence(cq, gl, sc, ev, source_code: str) -> list[dict]:
    """Satir bazli evidence listesi olustur (frontend code editor icin)."""
    evidence = []
    seen: set[tuple[int, str]] = set()

    _AGENT_LABEL = {
        "code_quality": "Kod Kalitesi",
        "guideline": "Standartlar",
        "seniority": "Kıdem",
        "security": "Güvenlik",
        "test_agent": "Test",
    }

    def _norm_msg(m: str) -> str:
        return re.sub(r"\s+", " ", (m or "").strip())

    def _add(line: int | None, agent: str, msg: str, sev: str):
        if not line or line < 1:
            return
        msg = (msg or "").strip()
        if not msg:
            return
        key = (line, _norm_msg(msg))
        if key in seen:
            return
        seen.add(key)
        evidence.append({
            "line": line,
            "agent": agent,
            "message": msg,
            "severity": _map_severity(sev),
        })

    for issue in cq.get("issues", []):
        desc = issue.get("description", "")
        if not desc:
            desc = issue.get("type", "")
        line_nums = re.findall(r"satir\s*(\d+)", desc, re.IGNORECASE)
        line = int(line_nums[0]) if line_nums else issue.get("line")
        _add(line, "Kod Kalitesi", desc, issue.get("severity", "info"))

    for viol in gl.get("style_violations", []):
        line_hint = viol.get("line_hint", "")
        nums = re.findall(r"(\d+)", line_hint)
        if nums:
            _add(int(nums[0]), "Standartlar", viol.get("description", viol.get("rule", "")), viol.get("severity", "info"))

    for threat in sc.get("threats", []):
        _add(threat.get("line"), "Güvenlik", threat.get("description", ""), threat.get("severity", "high"))

    _NODE_TYPE_LABEL = {
        "function": "Fonksiyon",
        "class": "Sınıf",
        "if": "If/elif bloğu",
        "for": "For döngüsü",
        "while": "While döngüsü",
        "try": "Try bloğu",
        "with": "With bloğu",
    }

    for claim in ev.get("validated_claims", []):
        feedback = claim.get("feedback", "")
        lines = claim.get("lines", [])
        if not lines:
            continue
        src = claim.get("agent_source", "Evidence")
        label = _AGENT_LABEL.get(src, src)
        line_range = claim.get("line_range") or []
        node_type = claim.get("node_type")
        symbol = claim.get("symbol")
        prefix = ""
        if isinstance(line_range, list) and len(line_range) == 2:
            type_label = _NODE_TYPE_LABEL.get(node_type or "", "Blok")
            sym_part = f" {symbol}" if symbol else ""
            prefix = f"[{type_label}{sym_part} • satır {line_range[0]}-{line_range[1]}] "
        msg = f"{prefix}{feedback}" if prefix else feedback
        _add(lines[0], label, msg, claim.get("severity", "info"))

    evidence.sort(key=lambda x: x["line"])
    return evidence


# ---- Endpoints ----

@app.get("/api/health")
async def health(response: Response):
    """Eski surec: sadece version 2.0.0 + agents, analysis_engine YOK. O zaman yanlis/eskimi uvicorn calisiyor."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return {
        "status": "ok",
        "package": "frontend",
        "version": "2.1.0",
        "agents": 8,
        "analysis_engine": _ANALYSIS_ENGINE,
        "demo_mode": _DEMO_MODE,
        "main_py": str(_MAIN_FILE),
    }


@app.post("/api/analyze")
async def analyze_code(req: AnalysisRequest):
    try:
        brief = await _fetch_assignment_brief_for_pipeline(req.assignment_id)
        faculty = await _fetch_faculty_rubric_criteria_for_pipeline(req.assignment_id)
        result = await run_analysis_pipeline(
            req.file_name,
            req.file_content,
            assignment_brief=brief,
            faculty_rubric_criteria=faculty,
        )
        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/student/login")
async def student_login(req: StudentLoginRequest):
    if _DEMO_MODE:
        student_no = req.student_no.strip()
        tc_no = req.tc_no.strip()
        for student in _DEMO_STORE["students"]:
            if student["student_no"] == student_no and student["tc_no"] == tc_no:
                return _demo_student_record(student)
        raise HTTPException(status_code=404, detail="Ogrenci bulunamadi")

    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT s.id, s.student_no, s.tc_no, s.first_name, s.last_name, s.class_year, s.department_id,
               d.name AS department_name, s.created_at
        FROM public.students s
        LEFT JOIN public.departments d ON d.id = s.department_id
        WHERE student_no = $1 AND tc_no = $2
        LIMIT 1
        """,
        req.student_no.strip(),
        req.tc_no.strip(),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Ogrenci bulunamadi")
    await _sync_student_to_all_courses(pool, str(row["id"]))
    return dict(row)


@app.post("/api/teacher/register")
async def teacher_register(req: TeacherRegisterRequest):
    first_name = req.first_name.strip()
    last_name = req.last_name.strip()
    email = req.email.strip().lower()
    password = req.password.strip()

    if not first_name or not last_name or not email or not password:
        raise HTTPException(status_code=400, detail="Tum alanlar zorunludur")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Sifre en az 6 karakter olmali")

    if _DEMO_MODE:
        existing = next(
            (t for t in _DEMO_STORE["teachers"] if t["email"].lower() == email),
            None,
        )
        if existing:
            raise HTTPException(status_code=409, detail="Bu e-posta ile kayitli bir ogretmen var")
        teacher = {
            "id": _demo_uuid(),
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "password_hash": _hash_password(password),
            "created_at": _demo_now(),
        }
        _DEMO_STORE["teachers"].append(teacher)
        _save_demo_store_to_disk()
        return {
            "id": teacher["id"],
            "first_name": teacher["first_name"],
            "last_name": teacher["last_name"],
            "email": teacher["email"],
            "created_at": teacher["created_at"],
        }

    pool = await _get_db_pool()
    existing = await pool.fetchrow(
        """
        SELECT id FROM public.teachers
        WHERE lower(email) = $1
        LIMIT 1
        """,
        email,
    )
    if existing:
        raise HTTPException(status_code=409, detail="Bu e-posta ile kayitli bir ogretmen var")

    row = await pool.fetchrow(
        """
        INSERT INTO public.teachers (first_name, last_name, email, password_hash)
        VALUES ($1, $2, $3, $4)
        RETURNING id, first_name, last_name, email, created_at
        """,
        first_name,
        last_name,
        email,
        _hash_password(password),
    )
    return dict(row)


@app.post("/api/teacher/login")
async def teacher_login(req: TeacherLoginRequest):
    email = req.email.strip().lower()
    password = req.password.strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="E-posta ve sifre zorunludur")

    if _DEMO_MODE:
        for teacher in _DEMO_STORE["teachers"]:
            if teacher["email"].lower() == email and _verify_password(password, teacher["password_hash"]):
                return {
                    "id": teacher["id"],
                    "first_name": teacher["first_name"],
                    "last_name": teacher["last_name"],
                    "email": teacher["email"],
                    "created_at": teacher["created_at"],
                }
        raise HTTPException(status_code=401, detail="E-posta veya sifre hatali")

    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT id, first_name, last_name, email, password_hash, created_at
        FROM public.teachers
        WHERE lower(email) = $1
        LIMIT 1
        """,
        email,
    )
    if row is None or not _verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="E-posta veya sifre hatali")

    return {
        "id": str(row["id"]),
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


@app.get("/api/departments")
async def list_departments():
    if _DEMO_MODE:
        return _DEMO_STORE["departments"]

    pool = await _get_db_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, created_by, created_at
        FROM public.departments
        ORDER BY name
        """
    )
    return [dict(r) for r in rows]


@app.post("/api/departments")
async def create_department(req: DepartmentCreateRequest):
    name = _normalize_department_title(req.name)
    if not name:
        raise HTTPException(status_code=400, detail="Bolum adi zorunludur")
    if _DEMO_MODE:
        department = {
            "id": _demo_uuid(),
            "name": name,
            "created_by": req.created_by,
            "created_at": _demo_now(),
        }
        _DEMO_STORE["departments"].append(department)
        _save_demo_store_to_disk()
        return department

    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO public.departments (name, created_by)
        VALUES ($1, $2)
        RETURNING id, name, created_by, created_at
        """,
        name,
        req.created_by,
    )
    return dict(row)


@app.delete("/api/departments/{department_id}")
async def delete_department(department_id: str):
    if _DEMO_MODE:
        before = len(_DEMO_STORE["departments"])
        _DEMO_STORE["departments"] = [
            d for d in _DEMO_STORE["departments"] if d["id"] != department_id
        ]
        if len(_DEMO_STORE["departments"]) == before:
            raise HTTPException(status_code=404, detail="Bolum bulunamadi")
        _save_demo_store_to_disk()
        return {"status": "ok"}

    pool = await _get_db_pool()
    result = await pool.execute(
        """
        DELETE FROM public.departments
        WHERE id = $1
        """,
        department_id,
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Bolum bulunamadi")
    return {"status": "ok"}


@app.get("/api/courses")
async def list_courses():
    if _DEMO_MODE:
        return _DEMO_STORE["courses"]

    pool = await _get_db_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, code, class_year, department_id, created_at
        FROM public.courses
        ORDER BY name
        """
    )
    return [dict(r) for r in rows]


@app.post("/api/courses")
async def create_course(req: CourseCreateRequest):
    name = req.name.strip()
    code = req.code.strip()
    if not name or not code:
        raise HTTPException(status_code=400, detail="Ders adi ve kodu zorunludur")
    class_year = _parse_class_year(req.class_year)
    if _DEMO_MODE:
        if any(c["code"].lower() == code.lower() for c in _DEMO_STORE["courses"]):
            raise HTTPException(status_code=409, detail="Bu ders kodu zaten mevcut")
        if req.department_id and not any(d["id"] == req.department_id for d in _DEMO_STORE["departments"]):
            raise HTTPException(status_code=400, detail="Gecersiz bolum secimi")
        course = {
            "id": _demo_uuid(),
            "name": name,
            "code": code,
            "class_year": class_year,
            "department_id": req.department_id,
            "created_at": _demo_now(),
        }
        _DEMO_STORE["courses"].append(course)
        _save_demo_store_to_disk()
        return course

    pool = await _get_db_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO public.courses (name, code, class_year, department_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id, name, code, class_year, department_id, created_at
            """,
            name,
            code,
            class_year,
            req.department_id,
        )
        await _sync_course_to_all_students(pool, str(row["id"]))
        return dict(row)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="Bu ders kodu zaten mevcut") from exc
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz bolum secimi") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ders olusturma hatasi: {exc}") from exc


@app.delete("/api/courses/{course_id}")
async def delete_course(course_id: str):
    if _DEMO_MODE:
        before = len(_DEMO_STORE["courses"])
        _DEMO_STORE["courses"] = [c for c in _DEMO_STORE["courses"] if c["id"] != course_id]
        if len(_DEMO_STORE["courses"]) == before:
            raise HTTPException(status_code=404, detail="Ders bulunamadi")
        _DEMO_STORE["assignments"] = [a for a in _DEMO_STORE["assignments"] if a["course_id"] != course_id]
        _DEMO_STORE["rubrics"] = [
            r for r in _DEMO_STORE["rubrics"]
            if any(a["id"] == r.get("assignment_id") for a in _DEMO_STORE["assignments"])
        ]
        _save_demo_store_to_disk()
        return {"status": "ok"}

    pool = await _get_db_pool()
    result = await pool.execute(
        """
        DELETE FROM public.courses
        WHERE id = $1
        """,
        course_id,
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Ders bulunamadi")
    return {"status": "ok"}


@app.get("/api/assignments")
async def list_assignments():
    if _DEMO_MODE:
        return sorted(
            [dict(a) for a in _DEMO_STORE["assignments"]],
            key=lambda a: str(a.get("created_at") or ""),
            reverse=True,
        )

    pool = await _get_db_pool()
    rows = await pool.fetch(
        """
        SELECT id, course_id, name, description, due_date, created_at
        FROM public.assignments
        ORDER BY created_at DESC
        """
    )
    return [dict(r) for r in rows]


def _course_context_for_assignment_safety(course: dict[str, Any] | asyncpg.Record | None) -> str:
    if course is None:
        return ""
    record = dict(course)
    name = str(record.get("name", "")).strip()
    code = str(record.get("code", "")).strip()
    class_year = record.get("class_year")
    parts = [part for part in (name, code, f"{class_year}. sinif" if class_year else "") if part]
    return " ".join(parts)


async def _ensure_assignment_safety(name: str, description: str | None, course_context: str) -> None:
    result = await _ASSIGNMENT_SAFETY_AGENT.analyze_hybrid(
        title=name,
        description=description,
        course_context=course_context,
    )
    if not result.allowed:
        raise HTTPException(status_code=400, detail=result.to_api_error())


@app.post("/api/assignments")
async def create_assignment(req: AssignmentCreateRequest):
    name = req.name.strip()
    if not name or not req.course_id:
        raise HTTPException(status_code=400, detail="Odev adi ve ders zorunludur")
    description = req.description.strip() if req.description else None
    if _DEMO_MODE:
        course = next((c for c in _DEMO_STORE["courses"] if c["id"] == req.course_id), None)
        if course is None:
            raise HTTPException(status_code=400, detail="Gecersiz ders secimi")
        await _ensure_assignment_safety(name, description, _course_context_for_assignment_safety(course))
        assignment = {
            "id": _demo_uuid(),
            "course_id": req.course_id,
            "name": name,
            "description": description,
            "due_date": req.due_date,
            "created_at": _demo_now(),
        }
        _DEMO_STORE["assignments"].append(assignment)
        _save_demo_store_to_disk()
        return assignment

    pool = await _get_db_pool()
    try:
        course = await pool.fetchrow(
            """
            SELECT id, name, code, class_year
            FROM public.courses
            WHERE id = $1
            LIMIT 1
            """,
            req.course_id,
        )
        if course is None:
            raise HTTPException(status_code=400, detail="Gecersiz ders secimi")
        await _ensure_assignment_safety(name, description, _course_context_for_assignment_safety(course))
        due_date = _parse_optional_datetime(req.due_date)
        row = await pool.fetchrow(
            """
            INSERT INTO public.assignments (course_id, name, description, due_date)
            VALUES ($1, $2, $3, $4)
            RETURNING id, course_id, name, description, due_date, created_at
            """,
            req.course_id,
            name,
            description,
            due_date,
        )
        return dict(row)
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz ders secimi") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Odev olusturma hatasi: {exc}") from exc


@app.delete("/api/assignments/{assignment_id}")
async def delete_assignment(assignment_id: str):
    aid = assignment_id.strip()
    if _DEMO_MODE:
        before = len(_DEMO_STORE["assignments"])
        _DEMO_STORE["assignments"] = [a for a in _DEMO_STORE["assignments"] if str(a["id"]) != aid]
        if len(_DEMO_STORE["assignments"]) == before:
            raise HTTPException(status_code=404, detail="Odev bulunamadi")
        _DEMO_STORE["rubrics"] = [r for r in _DEMO_STORE["rubrics"] if str(r["assignment_id"]) != aid]
        _save_demo_store_to_disk()
        return {"status": "ok"}

    uid = _parse_assignment_uuid_param(aid)
    pool = await _get_db_pool()
    result = await pool.execute(
        """
        DELETE FROM public.assignments
        WHERE id = $1::uuid
        """,
        uid,
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Odev bulunamadi")
    return {"status": "ok"}


@app.get("/api/rubrics")
async def list_rubrics():
    if _DEMO_MODE:
        return _DEMO_STORE["rubrics"]

    pool = await _get_db_pool()
    rows = await pool.fetch(
        """
        SELECT id, assignment_id, criteria, status, created_by, created_at, updated_at
        FROM public.rubrics
        """
    )
    return [dict(r) for r in rows]


@app.get("/api/rubrics/by-assignment/{assignment_id}")
async def get_rubric_by_assignment(assignment_id: str):
    aid = assignment_id.strip()
    if _DEMO_MODE:
        return next(
            (r for r in _DEMO_STORE["rubrics"] if str(r["assignment_id"]) == aid),
            None,
        )

    uid = _parse_assignment_uuid_param(aid)
    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT id, assignment_id, criteria, status, created_by, created_at, updated_at
        FROM public.rubrics
        WHERE assignment_id = $1::uuid
        LIMIT 1
        """,
        uid,
    )
    if row is None:
        return None
    return dict(row)


@app.post("/api/rubrics/upsert")
async def upsert_rubric(req: RubricUpsertRequest):
    if req.status not in {"draft", "approved"}:
        raise HTTPException(status_code=400, detail="Gecersiz rubrik statusu")
    if not req.criteria:
        raise HTTPException(status_code=400, detail="En az bir kriter gerekli")
    criteria = _ensure_rubric_constraints(req.criteria)

    if _DEMO_MODE:
        aid = (req.assignment_id or "").strip()
        if not any(str(a["id"]) == aid for a in _DEMO_STORE["assignments"]):
            raise HTTPException(status_code=400, detail="Gecersiz odev veya ogretmen bilgisi")

        existing = next(
            (r for r in _DEMO_STORE["rubrics"] if str(r["assignment_id"]) == aid),
            None,
        )
        if existing:
            existing["criteria"] = criteria
            existing["status"] = req.status
            existing["updated_at"] = _demo_now()
            _save_demo_store_to_disk()
            return existing

        rubric = {
            "id": _demo_uuid(),
            "assignment_id": aid,
            "criteria": criteria,
            "status": req.status,
            "created_by": req.created_by,
            "created_at": _demo_now(),
            "updated_at": _demo_now(),
        }
        _DEMO_STORE["rubrics"].append(rubric)
        _save_demo_store_to_disk()
        return rubric

    pool = await _get_db_pool()
    auid = _parse_assignment_uuid_param((req.assignment_id or "").strip())
    a_ok = await pool.fetchval(
        """
        SELECT 1 FROM public.assignments WHERE id = $1::uuid LIMIT 1
        """,
        auid,
    )
    if a_ok is None:
        raise HTTPException(status_code=400, detail="Gecersiz odev veya ogretmen bilgisi")

    existing = await pool.fetchrow(
        """
        SELECT id
        FROM public.rubrics
        WHERE assignment_id = $1::uuid
        LIMIT 1
        """,
        auid,
    )

    if existing:
        try:
            row = await pool.fetchrow(
                """
                UPDATE public.rubrics
                SET criteria = $1::jsonb, status = $2, updated_at = now()
                WHERE id = $3
                RETURNING id, assignment_id, criteria, status, created_by, created_at, updated_at
                """,
                json.dumps(criteria),
                req.status,
                existing["id"],
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Rubrik guncelleme hatasi: {exc}") from exc
    else:
        try:
            row = await pool.fetchrow(
                """
                INSERT INTO public.rubrics (assignment_id, criteria, status, created_by)
                VALUES ($1::uuid, $2::jsonb, $3, $4)
                RETURNING id, assignment_id, criteria, status, created_by, created_at, updated_at
                """,
                auid,
                json.dumps(criteria),
                req.status,
                req.created_by,
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise HTTPException(status_code=400, detail="Gecersiz odev veya ogretmen bilgisi") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Rubrik olusturma hatasi: {exc}") from exc
    return dict(row)


@app.patch("/api/rubrics/by-assignment/{assignment_id}")
async def update_rubric_status(assignment_id: str, req: RubricUpdateStatusRequest):
    if req.status not in {"draft", "approved"}:
        raise HTTPException(status_code=400, detail="Gecersiz rubrik statusu")
    aid = assignment_id.strip()
    if _DEMO_MODE:
        row = next((r for r in _DEMO_STORE["rubrics"] if str(r["assignment_id"]) == aid), None)
        if row is None:
            raise HTTPException(status_code=404, detail="Rubrik bulunamadi")
        row["status"] = req.status
        row["updated_at"] = _demo_now()
        _save_demo_store_to_disk()
        return row

    uid = _parse_assignment_uuid_param(aid)
    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        UPDATE public.rubrics
        SET status = $1, updated_at = now()
        WHERE assignment_id = $2::uuid
        RETURNING id, assignment_id, criteria, status, created_by, created_at, updated_at
        """,
        req.status,
        uid,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Rubrik bulunamadi")
    return dict(row)


@app.post("/api/rubric/suggest")
async def suggest_rubric(req: RubricSuggestionRequest):
    from backend.core.config import settings as _llm_cfg

    if not _llm_cfg.ollama_enabled:
        raise HTTPException(
            status_code=503,
            detail="LLM su an kapali (ollama_enabled=false). Rubrik onerisi icin Ollama acilmali.",
        )

    title = (req.assignment_title or "").strip() or "Odev"
    desc = (req.assignment_description or "").strip()
    criterion_count = _clamp_rubric_count(req.criterion_count)

    user_prompt = (
        f"Assignment title: {title}\n"
        f"Assignment description (may be empty):\n{desc or '(none)'}\n\n"
        f"Requested criterion count: {criterion_count}\n"
        f"Generate rubric criteria JSON with exactly {criterion_count} criteria.\n"
        f"Each max_score must be between {_RUBRIC_MIN_POINTS} and {_RUBRIC_MAX_POINTS}; "
        f"sum of max_score must be {_RUBRIC_TOTAL_POINTS}."
    )

    result = await chat_json(
        system_prompt=_RUBRIC_SUGGEST_SYSTEM,
        user_prompt=user_prompt,
        temperature=0.42,
        num_predict=3072,
    )
    if not result:
        raise HTTPException(
            status_code=502,
            detail="LLM rubrik JSON ureteemedi. Ollama ve modeli kontrol edin.",
        )
    try:
        criteria = _criteria_from_llm_payload(result, criterion_count)
        criteria = _sanitize_rubric_scope(
            criteria,
            assignment_title=title,
            assignment_description=desc,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM rubrik ciktisi gecersiz: {exc}",
        ) from exc
    return {"criteria": criteria}


@app.post("/api/faculty/assignment-assistant/suggestions")
async def assignment_assistant_suggestions(req: AssignmentAssistantSuggestionsRequest):
    """Ollama ile yapilandirilmis odev konusu onerileri (markdown yok)."""
    from backend.core.config import settings as _llm_cfg

    if not _llm_cfg.ollama_enabled:
        raise HTTPException(
            status_code=503,
            detail="LLM su an kapali (ollama_enabled=false).",
        )

    n = max(3, min(8, int(req.count or 5)))
    hint = (req.course_hint or "").strip()
    focus = _assignment_focus_extra(hint)
    tier = _normalize_assignment_difficulty(req.difficulty)

    user_prompt = (
        f"Uretilecek oneri sayisi: {n}.\n"
        f"Secilen ZORLUK (internal): {tier}\n"
        f"Egitimci baglami (bos olabilir): {hint or '(yok)'}\n"
        f"{_assignment_difficulty_prompt_block(tier)}\n"
    )
    if focus:
        user_prompt += focus + "\n"
    user_prompt += (
        "Her oneri farkli bir teknik konu olsun. Turkce yaz. "
        "Egitimcinin yazdigi ipucuna uy: alakasiz genel konular onerme."
    )
    if req.prefer_fresh:
        user_prompt += (
            "\nBu çağrı YENİDEN ÖNERİ isteğidir: daha önce görülen başlıklardan farklı ve birbirinden "
            "ayırt edilebilir 5 tamamen yeni ödev konusu öner; tek bir konuyu küçük başlık değişiklikleriyle "
            "tekrar etme.\n"
        )

    result = await chat_json(
        system_prompt=_ASSIGNMENT_SUGGEST_SYSTEM,
        user_prompt=user_prompt,
        temperature=0.55,
        num_predict=4096,
        use_cache=not bool(req.prefer_fresh),
    )

    raw_list: list[Any] | None = None
    if result:
        raw_list = _suggestions_list_from_llm(result)
        if raw_list is None:
            logger.warning(
                "assignment-assistant: LLM JSON beklenen listede degil, anahtarlar=%s",
                list(result.keys())[:24],
            )
    else:
        logger.warning("assignment-assistant: LLM sonuc bos (Ollama yanit/timeout/parse); yedek oneriler kullanilacak")

    cleaned = _clean_assignment_suggestion_items(raw_list or [], n)

    merged: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    def _extend_unique(items: list[dict[str, str]]) -> None:
        for it in items:
            if len(merged) >= n:
                return
            k = it["title"].strip().lower()
            if k in seen_titles:
                continue
            seen_titles.add(k)
            merged.append(dict(it))

    _extend_unique(cleaned)
    if len(merged) < n:
        _extend_unique(_fallback_assignment_suggestions(hint, tier))

    if len(merged) < 2:
        logger.error("assignment-assistant: LLM ve yedek listesi hala yetersiz (n=%s)", n)
        raise HTTPException(
            status_code=502,
            detail="Oneriler hazirlanamadi. Tekrar deneyin veya Ollama baglantisini kontrol edin.",
        )

    return {
        "suggestions": [
            {
                "id": str(i + 1),
                "title": row["title"],
                "summary": row["summary"],
                "description": row["description"],
            }
            for i, row in enumerate(merged)
        ],
    }


@app.get("/api/questions")
async def list_questions():
    """Tum sorulari listele"""
    if _DEMO_MODE:
        return _DEMO_STORE.get("questions", [])
    
    pool = await _get_db_pool()
    rows = await pool.fetch(
        """
        SELECT id, content, color, created_by, created_at, updated_at
        FROM public.question_bank
        ORDER BY created_at DESC
        """
    )
    return [dict(row) for row in rows]


@app.post("/api/questions")
async def create_question(req: dict[str, Any]):
    """Yeni soru olustur"""
    content = req.get("content", "").strip()
    color = req.get("color", "blue")
    
    if not content:
        raise HTTPException(status_code=400, detail="Soru icerigi zorunludur")
    
    if color not in {"blue", "green", "pink", "yellow"}:
        color = "blue"
    
    question_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    if _DEMO_MODE:
        if "questions" not in _DEMO_STORE:
            _DEMO_STORE["questions"] = []
        now = datetime.utcnow().isoformat()
        question = {
            "id": question_id,
            "content": content,
            "color": color,
            "created_by": None,
            "created_at": now,
            "updated_at": now
        }
        _DEMO_STORE["questions"].append(question)
        return question
    
    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO public.question_bank (id, content, color)
        VALUES ($1, $2, $3)
        RETURNING id, content, color, created_by, created_at, updated_at
        """,
        question_id,
        content,
        color,
    )
    return dict(row) if row else {}


@app.delete("/api/questions/{question_id}")
async def delete_question(question_id: str):
    """Soruyu sil"""
    if _DEMO_MODE:
        if "questions" in _DEMO_STORE:
            _DEMO_STORE["questions"] = [q for q in _DEMO_STORE["questions"] if q["id"] != question_id]
        return {"status": "ok"}
    
    pool = await _get_db_pool()
    await pool.execute(
        "DELETE FROM public.question_bank WHERE id = $1",
        question_id
    )
    return {"status": "ok"}


@app.get("/api/assignments/{assignment_id}/questions")
async def get_assignment_questions(assignment_id: str):
    """Odev icin secili sorulari getir"""
    if _DEMO_MODE:
        assignment_questions = _DEMO_STORE.get("assignment_questions", {}).get(assignment_id, [])
        all_questions = _DEMO_STORE.get("questions", [])
        return [q for q in all_questions if q["id"] in assignment_questions]
    
    pool = await _get_db_pool()
    rows = await pool.fetch(
        """
        SELECT qb.id, qb.content, qb.color, qb.created_by, qb.created_at, qb.updated_at
        FROM public.question_bank qb
        INNER JOIN public.assignment_questions aq ON qb.id = aq.question_id
        WHERE aq.assignment_id = $1
        ORDER BY aq.display_order ASC
        """,
        assignment_id
    )
    return [dict(row) for row in rows]


@app.post("/api/assignment-questions/update")
async def update_assignment_questions(req: dict[str, Any]):
    """Odev icin sorulari guncelle"""
    assignment_id = req.get("assignment_id", "").strip()
    question_ids = req.get("question_ids", [])
    
    if not assignment_id:
        raise HTTPException(status_code=400, detail="assignment_id zorunludur")
    
    if _DEMO_MODE:
        if "assignment_questions" not in _DEMO_STORE:
            _DEMO_STORE["assignment_questions"] = {}
        _DEMO_STORE["assignment_questions"][assignment_id] = question_ids
        return {"status": "ok"}
    
    pool = await _get_db_pool()
    
    # Onceki sorulari sil
    await pool.execute(
        "DELETE FROM public.assignment_questions WHERE assignment_id = $1",
        assignment_id
    )
    
    # Yeni sorulari ekle
    for i, question_id in enumerate(question_ids):
        await pool.execute(
            """
            INSERT INTO public.assignment_questions (assignment_id, question_id, display_order)
            VALUES ($1, $2, $3)
            ON CONFLICT (assignment_id, question_id) DO NOTHING
            """,
            assignment_id,
            question_id,
            i + 1
        )
    
    return {"status": "ok"}


@app.patch("/api/teacher/{teacher_id}/email")
async def update_teacher_email(teacher_id: str, req: TeacherEmailUpdateRequest):
    email = req.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="E-posta zorunludur")
    if _DEMO_MODE:
        teacher = next((t for t in _DEMO_STORE["teachers"] if t["id"] == teacher_id), None)
        if teacher is None:
            raise HTTPException(status_code=404, detail="Ogretmen bulunamadi")
        teacher["email"] = email
        return {
            "id": teacher["id"],
            "first_name": teacher["first_name"],
            "last_name": teacher["last_name"],
            "email": teacher["email"],
            "created_at": teacher["created_at"],
        }

    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        UPDATE public.teachers
        SET email = $1
        WHERE id = $2
        RETURNING id, first_name, last_name, email, created_at
        """,
        email,
        teacher_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Ogretmen bulunamadi")
    return dict(row)


@app.patch("/api/teacher/{teacher_id}/password")
async def update_teacher_password(teacher_id: str, req: TeacherPasswordUpdateRequest):
    new_password = req.new_password.strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Sifre en az 6 karakter olmali")

    if _DEMO_MODE:
        teacher = next((t for t in _DEMO_STORE["teachers"] if t["id"] == teacher_id), None)
        if teacher is None:
            raise HTTPException(status_code=404, detail="Ogretmen bulunamadi")
        if req.current_password and not _verify_password(req.current_password, teacher["password_hash"]):
            raise HTTPException(status_code=401, detail="Mevcut sifre hatali")
        teacher["password_hash"] = _hash_password(new_password)
        return {"status": "ok"}

    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT id, password_hash
        FROM public.teachers
        WHERE id = $1
        LIMIT 1
        """,
        teacher_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Ogretmen bulunamadi")

    if req.current_password and not _verify_password(req.current_password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Mevcut sifre hatali")

    await pool.execute(
        """
        UPDATE public.teachers
        SET password_hash = $1
        WHERE id = $2
        """,
        _hash_password(new_password),
        teacher_id,
    )
    return {"status": "ok"}


@app.get("/api/students")
async def list_students():
    if _DEMO_MODE:
        students = [_demo_student_record(student) for student in _DEMO_STORE["students"]]
        return sorted(students, key=lambda student: (student["first_name"], student["last_name"], student["student_no"]))

    pool = await _get_db_pool()
    rows = await pool.fetch(
        """
        SELECT s.id, s.student_no, s.tc_no, s.first_name, s.last_name, s.class_year, s.department_id,
               d.name AS department_name, s.created_at
        FROM public.students s
        LEFT JOIN public.departments d ON d.id = s.department_id
        ORDER BY s.first_name, s.last_name, s.student_no
        """
    )
    return [_normalize_student_record_department(dict(row)) for row in rows]


@app.post("/api/students")
async def create_student(req: StudentCreateRequest):
    student_no = _normalize_whitespace(req.student_no)
    tc_no = _normalize_whitespace(req.tc_no)
    first_name = _normalize_student_first_name(req.first_name)
    last_name = _normalize_student_last_name(req.last_name)
    department_id = req.department_id.strip() if req.department_id else None

    if not student_no or not tc_no or not first_name or not last_name:
        raise HTTPException(status_code=400, detail="Tum alanlar zorunludur")
    if not _is_valid_tc_no(tc_no):
        raise HTTPException(status_code=400, detail="TC no 11 haneli sayisal olmalidir")
    if not department_id:
        raise HTTPException(status_code=400, detail="Bolum secimi zorunludur")
    class_year = _parse_class_year(req.class_year)

    if _DEMO_MODE:
        conflict_field = _demo_student_conflict_field(_DEMO_STORE["students"], student_no, tc_no)
        if conflict_field:
            raise HTTPException(status_code=409, detail=_student_duplicate_message(student_no, tc_no, first_name, last_name, conflict_field))
        if not any(d["id"] == department_id for d in _DEMO_STORE["departments"]):
            raise HTTPException(status_code=400, detail="Gecersiz bolum secimi")
        student = {
            "id": _demo_uuid(),
            "student_no": student_no,
            "tc_no": tc_no,
            "first_name": first_name,
            "last_name": last_name,
            "class_year": class_year,
            "department_id": department_id,
            "created_at": _demo_now(),
        }
        _DEMO_STORE["students"].append(student)
        return _demo_student_record(student)

    pool = await _get_db_pool()
    conflict_field = await _student_conflict_field(pool, student_no, tc_no)
    if conflict_field:
        raise HTTPException(status_code=409, detail=_student_duplicate_message(student_no, tc_no, first_name, last_name, conflict_field))

    try:
        row = await pool.fetchrow(
            """
            INSERT INTO public.students (student_no, tc_no, first_name, last_name, class_year, department_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            student_no,
            tc_no,
            first_name,
            last_name,
            class_year,
            department_id,
        )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz bolum secimi") from exc
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail=_student_duplicate_message(student_no, tc_no, first_name, last_name)) from exc

    student_row = await _fetch_student_row(pool, str(row["id"]))
    return _normalize_student_record_department(dict(student_row))


@app.patch("/api/students/{student_id}")
async def update_student(student_id: str, req: StudentUpdateRequest):
    student_no = _normalize_whitespace(req.student_no)
    tc_no = _normalize_whitespace(req.tc_no)
    first_name = _normalize_student_first_name(req.first_name)
    last_name = _normalize_student_last_name(req.last_name)
    department_id = req.department_id.strip() if req.department_id else None

    if not student_no or not tc_no or not first_name or not last_name:
        raise HTTPException(status_code=400, detail="Tum alanlar zorunludur")
    if not _is_valid_tc_no(tc_no):
        raise HTTPException(status_code=400, detail="TC no 11 haneli sayisal olmalidir")
    if not department_id:
        raise HTTPException(status_code=400, detail="Bolum secimi zorunludur")
    class_year = _parse_class_year(req.class_year)

    if _DEMO_MODE:
        student = next((s for s in _DEMO_STORE["students"] if s["id"] == student_id), None)
        if student is None:
            raise HTTPException(status_code=404, detail="Ogrenci bulunamadi")
        conflict_field = _demo_student_conflict_field(_DEMO_STORE["students"], student_no, tc_no, exclude_id=student_id)
        if conflict_field:
            raise HTTPException(status_code=409, detail=_student_duplicate_message(student_no, tc_no, first_name, last_name, conflict_field))
        if not any(d["id"] == department_id for d in _DEMO_STORE["departments"]):
            raise HTTPException(status_code=400, detail="Gecersiz bolum secimi")
        student.update({
            "student_no": student_no,
            "tc_no": tc_no,
            "first_name": first_name,
            "last_name": last_name,
            "class_year": class_year,
            "department_id": department_id,
        })
        return _demo_student_record(student)

    pool = await _get_db_pool()
    existing = await pool.fetchrow(
        """
        SELECT id
        FROM public.students
        WHERE id = $1
        LIMIT 1
        """,
        student_id,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Ogrenci bulunamadi")

    conflict_field = await _student_conflict_field(pool, student_no, tc_no, exclude_id=student_id)
    if conflict_field:
        raise HTTPException(status_code=409, detail=_student_duplicate_message(student_no, tc_no, first_name, last_name, conflict_field))

    try:
        await pool.execute(
            """
            UPDATE public.students
            SET student_no = $1,
                tc_no = $2,
                first_name = $3,
                last_name = $4,
                class_year = $5,
                department_id = $6
            WHERE id = $7
            """,
            student_no,
            tc_no,
            first_name,
            last_name,
            class_year,
            department_id,
            student_id,
        )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz bolum secimi") from exc

    student_row = await _fetch_student_row(pool, student_id)
    return _normalize_student_record_department(dict(student_row))


@app.delete("/api/students/{student_id}")
async def delete_student(student_id: str):
    if _DEMO_MODE:
        before = len(_DEMO_STORE["students"])
        _DEMO_STORE["students"] = [student for student in _DEMO_STORE["students"] if student["id"] != student_id]
        if len(_DEMO_STORE["students"]) == before:
            raise HTTPException(status_code=404, detail="Ogrenci bulunamadi")
        return {"status": "ok"}

    pool = await _get_db_pool()
    result = await pool.execute(
        """
        DELETE FROM public.students
        WHERE id = $1
        """,
        student_id,
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Ogrenci bulunamadi")
    return {"status": "ok"}


@app.post("/api/students/import-csv")
async def import_students_csv(file: UploadFile = File(...)):
    raw_bytes = await file.read()
    try:
        csv_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = raw_bytes.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV dosyasi bos ya da basliksiz")

    def _norm_key(value: str) -> str:
        text = value.strip().lower()
        text = text.replace("ç", "c").replace("ğ", "g").replace("ı", "i").replace("ö", "o").replace("ş", "s").replace("ü", "u")
        return re.sub(r"[^a-z0-9]+", "_", text).strip("_")

    normalized_headers = {_norm_key(header): header for header in reader.fieldnames if header}

    def _get(row: dict[str, str | None], *names: str) -> str:
        for name in names:
          header = normalized_headers.get(_norm_key(name))
          if header is None:
              continue
          value = row.get(header)
          if value is None:
              continue
          text = str(value).strip()
          if text:
              return text
        return ""

    def _parse_class_year_text(raw_value: str) -> int | None:
        if raw_value is None:
            return None
        match = re.search(r"\d+", str(raw_value))
        if not match:
            return None
        try:
            return _parse_class_year(int(match.group(0)))
        except HTTPException:
            return None

    if _DEMO_MODE:
        department_map = { _norm_key(dep["name"]): dep["id"] for dep in _DEMO_STORE["departments"] }
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for row in reader:
            student_no = _normalize_whitespace(_get(row, "student_no", "student no", "ogrenci_no", "ogrenci no"))
            tc_no = _normalize_whitespace(_get(row, "tc_no", "tc", "tc kimlik no", "tc kimlik numarasi"))
            first_name = _normalize_student_first_name(_get(row, "first_name", "ad", "adi"))
            last_name = _normalize_student_last_name(_get(row, "last_name", "soyad", "soyadi"))
            department_name = _normalize_department_title(_get(row, "department", "department_name", "bolum", "bölüm"))
            class_year_text = _get(row, "class_year", "class", "sinif", "sınıf")

            if not student_no or not tc_no or not first_name or not last_name or not department_name or not class_year_text:
                skipped.append({
                    "student_no": student_no,
                    "tc_no": tc_no,
                    "first_name": first_name,
                    "last_name": last_name,
                    "department_name": department_name,
                    "reason": "Eksik alan nedeniyle kaydedilmedi",
                })
                continue

            if not _is_valid_tc_no(tc_no):
                skipped.append({
                    "student_no": student_no,
                    "tc_no": tc_no,
                    "first_name": first_name,
                    "last_name": last_name,
                    "department_name": department_name,
                    "reason": "TC no 11 haneli sayisal olmalidir",
                })
                continue

            class_year = _parse_class_year_text(class_year_text)
            if class_year is None:
                skipped.append({
                    "student_no": student_no,
                    "tc_no": tc_no,
                    "first_name": first_name,
                    "last_name": last_name,
                    "department_name": department_name,
                    "reason": "Gecersiz sinif degeri",
                })
                continue

            department_id = department_map.get(_norm_key(department_name))
            if not department_id:
                skipped.append({
                    "student_no": student_no,
                    "tc_no": tc_no,
                    "first_name": first_name,
                    "last_name": last_name,
                    "department_name": department_name,
                    "reason": "Bolum bulunamadi",
                })
                continue

            conflict_field = _demo_student_conflict_field(_DEMO_STORE["students"], student_no, tc_no)
            if conflict_field:
                skipped.append({
                    "student_no": student_no,
                    "tc_no": tc_no,
                    "first_name": first_name,
                    "last_name": last_name,
                    "department_name": department_name,
                    "reason": _student_csv_message(student_no, tc_no, first_name, last_name, conflict_field),
                })
                continue

            student = {
                "id": _demo_uuid(),
                "student_no": student_no,
                "tc_no": tc_no,
                "first_name": first_name,
                "last_name": last_name,
                "class_year": class_year,
                "department_id": department_id,
                "created_at": _demo_now(),
            }
            _DEMO_STORE["students"].append(student)
            created.append(_demo_student_record(student))

        return {"created": created, "skipped": skipped}

    pool = await _get_db_pool()
    departments = await pool.fetch("SELECT id, name FROM public.departments ORDER BY name")
    department_map = {_norm_key(str(dep["name"])): str(dep["id"]) for dep in departments}
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in reader:
        student_no = _normalize_whitespace(_get(row, "student_no", "student no", "ogrenci_no", "ogrenci no"))
        tc_no = _normalize_whitespace(_get(row, "tc_no", "tc", "tc kimlik no", "tc kimlik numarasi"))
        first_name = _normalize_student_first_name(_get(row, "first_name", "ad", "adi"))
        last_name = _normalize_student_last_name(_get(row, "last_name", "soyad", "soyadi"))
        department_name = _normalize_department_title(_get(row, "department", "department_name", "bolum", "bölüm"))
        class_year_text = _get(row, "class_year", "class", "sinif", "sınıf")

        if not student_no or not tc_no or not first_name or not last_name or not department_name or not class_year_text:
            skipped.append({
                "student_no": student_no,
                "tc_no": tc_no,
                "first_name": first_name,
                "last_name": last_name,
                "department_name": department_name,
                "reason": "Eksik alan nedeniyle kaydedilmedi",
            })
            continue

        if not _is_valid_tc_no(tc_no):
            skipped.append({
                "student_no": student_no,
                "tc_no": tc_no,
                "first_name": first_name,
                "last_name": last_name,
                "department_name": department_name,
                "reason": "TC no 11 haneli sayisal olmalidir",
            })
            continue

        class_year = _parse_class_year_text(class_year_text)
        if class_year is None:
            skipped.append({
                "student_no": student_no,
                "tc_no": tc_no,
                "first_name": first_name,
                "last_name": last_name,
                "department_name": department_name,
                "reason": "Gecersiz sinif degeri",
            })
            continue

        department_id = department_map.get(_norm_key(department_name))
        if not department_id:
            skipped.append({
                "student_no": student_no,
                "tc_no": tc_no,
                "first_name": first_name,
                "last_name": last_name,
                "department_name": department_name,
                "reason": "Bolum bulunamadi",
            })
            continue

        conflict_field = await _student_conflict_field(pool, student_no, tc_no)
        if conflict_field:
            skipped.append({
                "student_no": student_no,
                "tc_no": tc_no,
                "first_name": first_name,
                "last_name": last_name,
                "department_name": department_name,
                "reason": _student_csv_message(student_no, tc_no, first_name, last_name, conflict_field),
            })
            continue

        try:
            row_result = await pool.fetchrow(
                """
                INSERT INTO public.students (student_no, tc_no, first_name, last_name, class_year, department_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                student_no,
                tc_no,
                first_name,
                last_name,
                class_year,
                department_id,
            )
        except asyncpg.ForeignKeyViolationError:
            skipped.append({
                "student_no": student_no,
                "tc_no": tc_no,
                "first_name": first_name,
                "last_name": last_name,
                "department_name": department_name,
                "reason": "Bolum bulunamadi",
            })
            continue
        except asyncpg.UniqueViolationError:
            skipped.append({
                "student_no": student_no,
                "tc_no": tc_no,
                "first_name": first_name,
                "last_name": last_name,
                "department_name": department_name,
                "reason": _student_csv_message(student_no, tc_no, first_name, last_name),
            })
            continue

        student_row = await _fetch_student_row(pool, str(row_result["id"]))
        created.append(_normalize_student_record_department(dict(student_row)))

    return {"created": created, "skipped": skipped}


@app.get("/api/student/{student_id}/courses")
async def student_courses(student_id: str):
    if _DEMO_MODE:
        student = next((s for s in _DEMO_STORE["students"] if s["id"] == student_id), None)
        if student is None:
            return []
        department_id = student.get("department_id")
        class_year = student.get("class_year")
        return [
            dict(c)
            for c in _DEMO_STORE["courses"]
            if (c.get("department_id") is None or c.get("department_id") == department_id)
            and (c.get("class_year") is None or c.get("class_year") == class_year)
        ]

    pool = await _get_db_pool()
    await _sync_student_to_all_courses(pool, student_id)
    rows = await pool.fetch(
        """
        SELECT c.id, c.name, c.code, c.class_year, c.created_at
        FROM public.student_courses sc
        JOIN public.courses c ON c.id = sc.course_id
                JOIN public.students s ON s.id = sc.student_id
                WHERE sc.student_id = $1
                    AND (c.department_id IS NULL OR c.department_id = s.department_id)
                    AND (c.class_year IS NULL OR c.class_year = s.class_year)
        ORDER BY c.name
        """,
        student_id,
    )
    return [dict(r) for r in rows]


@app.get("/api/courses/{course_id}")
async def course_detail(course_id: str):
    if _DEMO_MODE:
        row = next((c for c in _DEMO_STORE["courses"] if c["id"] == course_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="Ders bulunamadi")
        return row

    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, code, class_year, created_at
        FROM public.courses
        WHERE id = $1
        LIMIT 1
        """,
        course_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Ders bulunamadi")
    return dict(row)


@app.get("/api/courses/{course_id}/assignments")
async def course_assignments(course_id: str):
    if _DEMO_MODE:
        approved_assignment_ids = {
            r["assignment_id"] for r in _DEMO_STORE["rubrics"] if r["status"] == "approved"
        }
        rows = [
            dict(a)
            for a in _DEMO_STORE["assignments"]
            if a["course_id"] == course_id and a["id"] in approved_assignment_ids
        ]
        return sorted(rows, key=lambda a: str(a.get("created_at") or ""), reverse=True)

    pool = await _get_db_pool()
    rows = await pool.fetch(
        """
                SELECT a.id, a.course_id, a.name, a.description, a.due_date, a.created_at
                FROM public.assignments a
                WHERE a.course_id = $1
                    AND EXISTS (
                        SELECT 1
                        FROM public.rubrics r
                        WHERE r.assignment_id = a.id
                            AND r.status = 'approved'
                    )
                ORDER BY a.created_at DESC
        """,
        course_id,
    )
    return [dict(r) for r in rows]


@app.get("/api/assignments/{assignment_id}")
async def assignment_detail(assignment_id: str):
    aid = assignment_id.strip()
    if _DEMO_MODE:
        row = next((a for a in _DEMO_STORE["assignments"] if str(a["id"]) == aid), None)
        if row is None:
            raise HTTPException(status_code=404, detail="Odev bulunamadi")
        return row

    uid = _parse_assignment_uuid_param(aid)
    pool = await _get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT id, course_id, name, description, due_date, created_at
        FROM public.assignments
        WHERE id = $1::uuid
        LIMIT 1
        """,
        uid,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Odev bulunamadi")
    return dict(row)


@app.post("/api/upload-history")
async def create_upload_history(req: UploadHistoryRequest):
    if _DEMO_MODE:
        _DEMO_STORE["upload_history"].append(
            {
                "id": _demo_uuid(),
                "student_first_name": req.student_first_name.strip(),
                "student_last_name": req.student_last_name.strip(),
                "student_no": req.student_no.strip(),
                "uploaded_file_name": req.uploaded_file_name.strip(),
                "assignment_id": req.assignment_id,
                "score": req.score,
                "has_error": req.has_error,
                "uploaded_at": _demo_now(),
            }
        )
        return {"status": "ok"}

    pool = await _get_db_pool()
    await pool.execute(
        """
        INSERT INTO public.student_upload_history
          (student_first_name, student_last_name, student_no, uploaded_file_name, assignment_id, score, has_error)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        req.student_first_name.strip(),
        req.student_last_name.strip(),
        req.student_no.strip(),
        req.uploaded_file_name.strip(),
        req.assignment_id,
        req.score,
        req.has_error,
    )
    return {"status": "ok"}


@app.get("/api/upload-history")
async def list_upload_history(student_no: str, assignment_id: str | None = None):
    if _DEMO_MODE:
        rows = [
            dict(r)
            for r in _DEMO_STORE["upload_history"]
            if r["student_no"] == student_no.strip()
            and (assignment_id is None or r["assignment_id"] == assignment_id)
        ]
        rows.sort(key=lambda r: r.get("uploaded_at", ""), reverse=True)
        return rows

    pool = await _get_db_pool()
    if assignment_id:
        rows = await pool.fetch(
            """
            SELECT id, student_first_name, student_last_name, student_no, uploaded_file_name,
                   assignment_id, score, has_error, uploaded_at
            FROM public.student_upload_history
            WHERE student_no = $1 AND assignment_id = $2
            ORDER BY uploaded_at DESC
            """,
            student_no.strip(),
            assignment_id,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, student_first_name, student_last_name, student_no, uploaded_file_name,
                   assignment_id, score, has_error, uploaded_at
            FROM public.student_upload_history
            WHERE student_no = $1
            ORDER BY uploaded_at DESC
            """,
            student_no.strip(),
        )
    return [dict(r) for r in rows]


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Dosya metin olarak okunamadi.")
    result = await run_analysis_pipeline(file.filename or "unknown.py", text_content)
    return result
