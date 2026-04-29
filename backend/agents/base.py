"""
Base agent interface -- tam LLM tabanli ajanlar.

Programatik analiz (AST, regex, sandbox sayimlari) yalnizca LLM prompt'una ipucu olarak verilir;
nihai skor, bulgular ve metinler yalnizca LLM yanitindan gelir. Ollama kapali veya cagri basarisizsa
ajan `LLMInferenceError` firlatirir; programatik fallback yoktur.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from backend.core.config import settings
from backend.llm.ollama_client import chat_json

logger = logging.getLogger(__name__)


class LLMInferenceError(RuntimeError):
    """LLM zorunlu; Ollama kullanilamaz veya gecerli JSON yanit uretilemedi."""


# Locale code (BCP47-ish) -> natural language name for English system prompts
_REPORT_LANG_NAMES_EN: dict[str, str] = {
    "tr": "Turkish",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ar": "Arabic",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
}


def normalize_report_language(code: str | None) -> str:
    """Primary language subtag; default Turkish for empty/unknown."""
    if code is None or not str(code).strip():
        return "tr"
    primary = str(code).strip().lower().replace("_", "-").split("-", 1)[0]
    return primary if primary else "tr"


def report_language_name_for_prompt(locale: str | None) -> str:
    """English name of the UI/report locale, for instructing the model."""
    loc = normalize_report_language(locale)
    return _REPORT_LANG_NAMES_EN.get(loc, "Turkish")


def build_llm_user_suffix(*, report_language: str = "tr") -> str:
    """English instructions appended to user prompts (Qwen reads English reliably).

    Human-readable JSON fields must follow the site's ``report_language`` (default Turkish).
    """
    lang = report_language_name_for_prompt(report_language)
    return (
        "\n\n[IMPORTANT — follow these rules]\n"
        "Final scores and all narrative judgments must come from your own analysis of the code "
        "(and sandbox facts where provided). Static or heuristic hints above are non-binding; "
        "do not copy their scores blindly. When in doubt, trust the source code and these rules.\n"
        "Return only valid, complete JSON as specified; do not invent execution results.\n\n"
        f"[OUTPUT LANGUAGE] Write every human-readable string in the JSON "
        f"(descriptions, explanations, suggestions, summaries, justifications, feedback, "
        f"reason strings, analysis paragraphs, list items like strengths/weaknesses/recommendations, etc.) "
        f"in {lang}. "
        "Keep structured enums and symbols exactly as required (e.g. severity levels, "
        "risk_level, Big-O notation, code identifiers). "
        "If the UI locale is ambiguous, use Turkish."
    )


# Backward compatibility
LLM_PRIMARY_SUFFIX_TR = build_llm_user_suffix(report_language="tr")


def format_assignment_context_for_prompt(
    assignment_brief: str | None, *, max_chars: int = 6000
) -> str:
    """Instructor brief (title + description) appended to agent user prompts when non-empty."""
    raw = (assignment_brief or "").strip()
    if not raw:
        return ""
    if len(raw) > max_chars:
        raw = raw[: max_chars - 24].rstrip() + "\n[... truncated ...]"
    return (
        "\n\n[ASSIGNMENT BRIEF — judge fit to this, not only local code quality]\n"
        "The course staff stated the following. Decide whether the submission actually fulfills "
        "this assignment (topic, required concepts, deliverables).\n\n"
        f"{raw}\n\n"
        "If the work is off-topic, uses the wrong paradigm (e.g. no OOP when the brief requires "
        "classes/objects), or ignores stated requirements, state that clearly and lower the score "
        "for relevance / brief compliance in your findings."
    )


class BaseAgent(ABC):
    """All agents must extend this class."""

    name: str = "base"
    description: str = ""

    @abstractmethod
    async def analyze(self, input_data: dict) -> dict:
        """Run this agent's analysis (LLM zorunlu).

        Args:
            input_data: Agent-specific input dict (see schemas.py for contracts).

        Returns:
            Structured dict matching the agent's output schema.

        Raises:
            LLMInferenceError: Ollama kapali veya LLM yaniti alinamadi / sema ihlali.
        """
        ...

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        required_keys: list[str] | None = None,
        temperature: float = 0.3,
        num_predict: int | None = None,
    ) -> dict:
        """Ollama uzerinden JSON yanit alir; basarisizda `LLMInferenceError` firlatirir."""
        if not settings.ollama_enabled:
            raise LLMInferenceError(
                f"[{self.name}] Ollama devre disi (ollama_enabled=false); LLM zorunlu."
            )
        try:
            result = await chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                num_predict=num_predict,
            )
        except Exception as exc:
            logger.warning("[%s] LLM cagrisi basarisiz: %s", self.name, exc)
            raise LLMInferenceError(f"[{self.name}] LLM cagrisi basarisiz.") from exc

        if result is None:
            raise LLMInferenceError(f"[{self.name}] LLM bos veya cozumlenemeyen yanit dondu.")

        if required_keys:
            # Doküman Bölüm 5 -- "3. denemede başarısız olursa Error bayrağı".
            # 1 ilk çağrı + 2 schema-repair retry = toplam 3 deneme.
            max_repair_attempts = 2
            for attempt in range(1, max_repair_attempts + 1):
                missing = [k for k in required_keys if k not in result]
                if not missing:
                    break
                logger.warning(
                    "[%s] LLM yanitinda eksik alanlar: %s; onarim denemesi %d/%d",
                    self.name,
                    ", ".join(missing),
                    attempt,
                    max_repair_attempts,
                )
                repair_prompt = (
                    f"{user_prompt}\n\n"
                    "[SCHEMA REPAIR]\n"
                    f"Attempt {attempt}/{max_repair_attempts}. Your previous JSON response was "
                    f"missing these required top-level keys: {', '.join(missing)}.\n"
                    "Return the complete JSON object again, with ALL required top-level keys present. "
                    "Do not omit arrays; use [] when there are no items. Do not omit counts; use 0 when needed. "
                    "Return ONLY valid JSON."
                )
                try:
                    repaired = await chat_json(
                        system_prompt=system_prompt,
                        user_prompt=repair_prompt,
                        temperature=0.1,
                        num_predict=num_predict,
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] LLM onarim cagrisi basarisiz (deneme %d): %s",
                        self.name,
                        attempt,
                        exc,
                    )
                    repaired = None
                if isinstance(repaired, dict):
                    result = {**result, **repaired}
            missing = [k for k in required_keys if k not in result]
            if missing:
                raise LLMInferenceError(
                    f"[{self.name}] LLM yanitinda eksik alanlar: {', '.join(missing)}"
                )

        return result

    @staticmethod
    def _truncate_code(code: str, max_lines: int = 300) -> str:
        """Cok uzun kodlari LLM prompt'u icin kisaltir."""
        lines = code.splitlines()
        if len(lines) <= max_lines:
            return code
        half = max_lines // 2
        return "\n".join(
            lines[:half]
            + [f"\n... ({len(lines) - max_lines} satir kisaltildi) ...\n"]
            + lines[-half:]
        )

    @staticmethod
    def _safe_int(value: Any, default: int, minimum: int = 0, maximum: int = 100) -> int:
        """LLM'den gelen skoru guvenli int'e cevirir."""
        try:
            v = int(round(float(value)))
            return max(minimum, min(maximum, v))
        except (TypeError, ValueError):
            return default
