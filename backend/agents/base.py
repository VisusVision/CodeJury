"""
Base agent interface -- LLM-primary agents with programmatic hints.

Programmatic analysis (AST, regex, sandbox counts) is passed to the LLM as factual hints
only; scores and narrative come from the LLM response. Objective facts (compile failure,
sandbox exit code, validated test pass/fail) may be enforced on the merged output.
When Ollama is disabled or the LLM call fails, agents fall back to programmatic output
or raise LLMInferenceError depending on the agent.
"""

import logging
import json
from abc import ABC, abstractmethod
from typing import Any

from backend.agents.json_output_schema import collect_validation_messages, normalize_instance_for_schema
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

    def _pre_schema_normalize(self, result: dict, output_json_schema: dict | None) -> dict:
        """Optional hook: coerce LLM JSON before schema validation."""
        return result

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        required_keys: list[str] | None = None,
        output_json_schema: dict | None = None,
        temperature: float = 0.0,
        num_predict: int | None = None,
        use_cache: bool = True,
        model: str | None = None,
    ) -> dict:
        """Ollama uzerinden JSON yanit alir; basarisizda `LLMInferenceError` firlatirir."""
        if not settings.ollama_enabled:
            raise LLMInferenceError(
                f"[{self.name}] Ollama is disabled (ollama_enabled=false); LLM is required."
            )
        try:
            result = await chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_hint=output_json_schema,
                temperature=temperature,
                num_predict=num_predict,
                model=model or settings.ollama_coder_model,
                use_cache=use_cache,
            )
        except Exception as exc:
            logger.warning("[%s] LLM cagrisi basarisiz: %s", self.name, exc)
            raise LLMInferenceError(f"[{self.name}] LLM call failed.") from exc

        if result is None:
            raise LLMInferenceError(f"[{self.name}] LLM returned an empty or unparseable response.")

        repaired = False
        schema_repair_count = 0
        guardrail_flags: list[str] = []
        if required_keys:
            result = self._unwrap_required_response(result, required_keys)
            # 1 ilk çağrı + en fazla 3 onarım çağrısı (eksik üst seviye anahtarlar).
            max_repair_attempts = 3
            for attempt in range(1, max_repair_attempts + 1):
                missing = [k for k in required_keys if k not in result]
                if not missing:
                    break
                repaired = True
                schema_repair_count += 1
                guardrail_flags.append("missing_required_keys_repair")
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
                    "Return ONLY valid JSON.\n"
                    f"Use this JSON skeleton exactly (fill values):\n{self._required_keys_scaffold(required_keys)}"
                )
                try:
                    repair_payload = await chat_json(
                        system_prompt=system_prompt,
                        user_prompt=repair_prompt,
                        schema_hint=output_json_schema,
                        temperature=0.1,
                        num_predict=num_predict,
                        model=model or settings.ollama_coder_model,
                        use_cache=False,
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] LLM onarim cagrisi basarisiz (deneme %d): %s",
                        self.name,
                        attempt,
                        exc,
                    )
                    repair_payload = None
                if isinstance(repair_payload, dict):
                    result = self._unwrap_required_response({**result, **repair_payload}, required_keys)
            missing = [k for k in required_keys if k not in result]
            if missing:
                raise LLMInferenceError(
                    f"[{self.name}] Missing required keys in LLM response: {', '.join(missing)}"
                )

        if output_json_schema:
            max_schema_repair_attempts = 3
            for attempt in range(max_schema_repair_attempts + 1):
                result = self._pre_schema_normalize(result, output_json_schema)
                result = normalize_instance_for_schema(result, output_json_schema)
                schema_msgs = collect_validation_messages(result, output_json_schema)
                if not schema_msgs:
                    break
                if attempt >= max_schema_repair_attempts:
                    raise LLMInferenceError(
                        f"[{self.name}] JSON Schema validation failed: "
                        + "; ".join(schema_msgs[:8])
                    )
                repaired = True
                schema_repair_count += 1
                guardrail_flags.append("json_schema_repair")
                logger.warning(
                    "[%s] JSON Schema ihlali; onarim denemesi %d/%d: %s",
                    self.name,
                    attempt + 1,
                    max_schema_repair_attempts,
                    "; ".join(schema_msgs[:4]),
                )
                repair_prompt = (
                    f"{user_prompt}\n\n"
                    "[SCHEMA REPAIR — JSON Schema]\n"
                    f"Attempt {attempt + 1}/{max_schema_repair_attempts}. Your JSON failed validation:\n"
                    + "\n".join(schema_msgs)
                    + "\nReturn the complete JSON object again, fully conforming to the schema described "
                    "in the system prompt. Fix types (booleans not strings, integers where required, "
                    "required object fields in each issue, enum values exactly as allowed). "
                    "Return ONLY valid JSON."
                )
                try:
                    repair_payload = await chat_json(
                        system_prompt=system_prompt,
                        user_prompt=repair_prompt,
                        schema_hint=output_json_schema,
                        temperature=0.1,
                        num_predict=num_predict,
                        model=model or settings.ollama_coder_model,
                        use_cache=False,
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] JSON Schema onarim cagrisi basarisiz (deneme %d): %s",
                        self.name,
                        attempt + 1,
                        exc,
                    )
                    repair_payload = None
                if isinstance(repair_payload, dict):
                    result = self._unwrap_required_response(
                        {**result, **repair_payload},
                        list(output_json_schema.get("required", [])),
                    )

        return self._with_contract_metadata(
            result,
            llm_status="repaired" if repaired else "ok",
            guardrail_flags=guardrail_flags,
            schema_repair_count=schema_repair_count,
        )

    @staticmethod
    def _with_contract_metadata(
        result: dict[str, Any],
        *,
        llm_status: str,
        guardrail_flags: list[str] | None = None,
        schema_repair_count: int = 0,
    ) -> dict[str, Any]:
        """Attach common, non-breaking agent metadata."""
        if not isinstance(result, dict):
            return result
        out = dict(result)
        out.setdefault("llm_status", llm_status)
        existing_flags = out.get("guardrail_flags")
        flags: list[str] = []
        if isinstance(existing_flags, list):
            flags.extend(str(flag) for flag in existing_flags if str(flag).strip())
        for flag in guardrail_flags or []:
            if flag not in flags:
                flags.append(flag)
        out["guardrail_flags"] = flags
        try:
            existing_repair_count = int(out.get("schema_repair_count") or 0)
        except (TypeError, ValueError):
            existing_repair_count = 0
        out["schema_repair_count"] = max(existing_repair_count, int(schema_repair_count or 0))
        # Confidence: yalnizca LLM gercekten 0-1 araliginda bir deger verdiyse koru.
        # Aksi halde yaniltici sahte 0.0 yerine None birak (UI gizler, JSON dururst kalir).
        conf = out.get("confidence")
        valid_conf: float | None = None
        if isinstance(conf, (int, float)) and not isinstance(conf, bool):
            c = float(conf)
            if 0.0 <= c <= 1.0:
                valid_conf = c
        out["confidence"] = valid_conf
        return out

    @staticmethod
    def _unwrap_required_response(result: dict[str, Any], required_keys: list[str]) -> dict[str, Any]:
        """Use a nested payload if a model wrapped the requested JSON object."""
        if not isinstance(result, dict) or not required_keys:
            return result
        top_matches = sum(1 for key in required_keys if key in result)
        if top_matches == len(required_keys):
            return result

        best: dict[str, Any] | None = None
        best_matches = top_matches
        stack: list[dict[str, Any]] = []
        for value in result.values():
            if isinstance(value, dict):
                stack.append(value)
            elif isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    stack.append(parsed)
        while stack:
            candidate = stack.pop(0)
            matches = sum(1 for key in required_keys if key in candidate)
            if matches > best_matches:
                best = candidate
                best_matches = matches
            for value in candidate.values():
                if isinstance(value, dict):
                    stack.append(value)
                elif isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        parsed = None
                    if isinstance(parsed, dict):
                        stack.append(parsed)

        if best is not None and best_matches >= max(1, top_matches):
            return {**result, **best}
        return result

    @staticmethod
    def _required_keys_scaffold(required_keys: list[str]) -> str:
        """Deterministic scaffold to stabilize repair prompts for small local models."""
        keys = set(required_keys or [])
        if {
            "final_score",
            "rubric_breakdown",
            "summary",
            "strengths",
            "weaknesses",
            "recommendations",
        }.issubset(keys):
            return (
                '{'
                '"final_score": 0,'
                '"rubric_breakdown": [{"criterion":"","label":"","weight":0,"score":0,"weighted_score":0,"justification":""}],'
                '"summary": "",'
                '"strengths": [],'
                '"weaknesses": [],'
                '"recommendations": []'
                '}'
            )
        return "{" + ", ".join(f'"{k}": null' for k in required_keys) + "}"

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
