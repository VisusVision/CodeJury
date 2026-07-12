"""
Ollama REST API istemcisi.

Tum ajanlar bu modul uzerinden LLM cagrisi yapar.
JSON mode ile structured output alir, timeout ve retry destekler.

Optimizasyonlar:
- Semaphore ile kontrollü paralellik (CPU contention önleme)
- In-memory LRU cache (aynı prompt tekrar çağrılmaz)
- Otomatik retry (geçici hatalar için)
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from backend.core.config import settings

logger = logging.getLogger(__name__)

LLMRole = Literal["general", "coder"]


@dataclass(frozen=True)
class ChatJsonResult:
    data: dict[str, Any] | None
    provider: str
    model: str
    fallback_used: bool
    error: str | None = None
    cache_hit: bool = False
    max_tokens: int = 0
    fallback_reason: str = ""
    role: LLMRole = "general"

_client: httpx.AsyncClient | None = None
_semaphore: asyncio.Semaphore | None = None
_nim_client: httpx.AsyncClient | None = None
_nim_semaphore: asyncio.Semaphore | None = None
_nim_rate_lock: asyncio.Lock | None = None
_last_nim_request_at: float = 0.0

_cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()
_CACHE_MAX_SIZE = 128
_CACHE_TTL_SECONDS = 600
_last_call_metadata: dict[str, Any] = {}


def _record_call_metadata(**metadata: Any) -> None:
    """Store safe, prompt-free diagnostics for the most recent LLM call."""
    global _last_call_metadata
    allowed = {
        "function",
        "provider",
        "model",
        "cache_hit",
        "result_status",
        "response_format",
        "max_tokens",
        "fallback_reason",
        "role",
    }
    _last_call_metadata = {key: value for key, value in metadata.items() if key in allowed}


def get_llm_diagnostics_snapshot() -> dict[str, Any]:
    """Return safe metadata for diagnostics; never includes prompts or secrets."""
    return dict(_last_call_metadata)


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.ollama_max_concurrent)
    return _semaphore


def _get_nim_semaphore() -> asyncio.Semaphore:
    global _nim_semaphore
    if _nim_semaphore is None:
        _nim_semaphore = asyncio.Semaphore(settings.nvidia_nim_max_concurrent)
    return _nim_semaphore


def _get_nim_rate_lock() -> asyncio.Lock:
    global _nim_rate_lock
    if _nim_rate_lock is None:
        _nim_rate_lock = asyncio.Lock()
    return _nim_rate_lock


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.ollama_timeout, connect=30.0),
        )
    return _client


def _get_nim_client() -> httpx.AsyncClient:
    global _nim_client
    if _nim_client is None or _nim_client.is_closed:
        _nim_client = httpx.AsyncClient(
            base_url=settings.nvidia_nim_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.nvidia_nim_timeout, connect=30.0),
        )
    return _nim_client


def _normalize_provider(value: str | None) -> str:
    return str(value or "").strip().lower()


def _llm_provider() -> str:
    return _normalize_provider(settings.llm_provider) or "ollama"


def _resolve_role(model: str | None, role: LLMRole | None) -> LLMRole:
    if role in {"general", "coder"}:
        return role
    if (
        model is not None
        and settings.ollama_coder_model != settings.ollama_general_model
        and model == settings.ollama_coder_model
    ):
        return "coder"
    return "general"


def _provider_for_role(role: LLMRole) -> str:
    default = _llm_provider()
    if role == "coder":
        return _normalize_provider(settings.llm_coder_provider) or default
    return _normalize_provider(settings.llm_general_provider) or default


def _provider_is_nvidia_nim(provider: str) -> bool:
    return provider in {"nvidia_nim", "nim", "nvidia"}


def _model_for_role(role: LLMRole, *, nim: bool) -> str:
    if nim:
        return settings.nvidia_nim_coder_model if role == "coder" else settings.nvidia_nim_general_model
    return settings.ollama_coder_model if role == "coder" else settings.ollama_general_model


def _local_model_for_request(model: str | None, role: LLMRole) -> str:
    if model is None or model in {settings.ollama_general_model, settings.ollama_coder_model}:
        return _model_for_role(role, nim=False)
    return model


def _is_gpt_oss_model(model: str | None) -> bool:
    return "gpt-oss" in str(model or "").lower()


def _ollama_predict_for_model(model: str | None, num_predict: int | None) -> int:
    base = int(num_predict) if num_predict is not None else int(settings.ollama_num_predict)
    if _is_gpt_oss_model(model):
        return max(base, int(settings.ollama_gpt_oss_num_predict))
    return base


def _ollama_inference_options(
    model: str,
    temperature: float,
    num_predict: int,
    *,
    role: LLMRole,
) -> dict[str, Any]:
    """Ollama /api/chat options; coder model gets AgentGrade Modelfile tuning."""
    options: dict[str, Any] = {
        "temperature": temperature,
        "num_predict": num_predict,
    }
    if role == "coder":
        options.update(
            {
                "temperature": settings.ollama_coder_temperature,
                "num_ctx": settings.ollama_coder_num_ctx,
                "top_p": settings.ollama_coder_top_p,
                "repeat_penalty": settings.ollama_coder_repeat_penalty,
                "num_gpu": settings.ollama_coder_num_gpu,
            }
        )
    return options


def _apply_gpt_oss_chat_options(payload: dict[str, Any], *, json_mode: bool) -> None:
    """GPT-OSS needs a higher token budget; thinking is disabled for JSON mode."""
    model = str(payload.get("model") or "")
    if not _is_gpt_oss_model(model):
        return
    think = str(settings.ollama_gpt_oss_think or "").strip().lower()
    if json_mode:
        # Ollama: format=json and think are mutually exclusive for structured agent output.
        return
    if think in {"low", "medium", "high"}:
        payload["think"] = think


def _ollama_message_text(data: dict[str, Any]) -> str:
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    content = str(message.get("content") or "").strip()
    if content:
        return content
    # Some thinking models may leave content empty on malformed runs; never parse thinking as JSON.
    return ""


def _cache_key(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    model: str,
    schema_hint: dict[str, Any] | None = None,
    role: LLMRole = "general",
) -> str:
    schema_part = ""
    if schema_hint:
        schema_part = json.dumps(schema_hint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = f"{role}:{model}:{temperature}:{schema_part}:{system_prompt}:{user_prompt}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> dict | None:
    if key in _cache:
        result, ts = _cache[key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            _cache.move_to_end(key)
            logger.info("[ollama-cache] HIT")
            return result
        del _cache[key]
    return None


def _cache_put(key: str, result: dict) -> None:
    _cache[key] = (result, time.time())
    if len(_cache) > _CACHE_MAX_SIZE:
        _cache.popitem(last=False)


async def warmup() -> bool:
    """Modeli bellegee yukler ve orada tutar. Uygulama baslangicinda cagirilmali."""
    if not settings.ollama_enabled:
        return False
    if _provider_is_nvidia_nim(_llm_provider()):
        return bool(settings.nvidia_nim_api_key.strip())
    models = list(dict.fromkeys([
        settings.ollama_general_model,
        settings.ollama_coder_model,
    ]))
    warmed = False
    try:
        client = _get_client()
        for model in models:
            resp = await client.post("/api/chat", json={
                "model": model,
                "messages": [{"role": "user", "content": "warmup"}],
                "stream": False,
                "keep_alive": "30m",
            })
            resp.raise_for_status()
            warmed = True
            logger.info("[ollama] Model bellege yuklendi ve 30dk tutulacak: %s", model)
    except Exception as exc:
        logger.warning("[ollama] Warmup basarisiz: %s", exc)
    return warmed


def _extract_json(text: str) -> dict | None:
    """LLM ciktisindaki ilk JSON nesnesini cikarir (fence, fazla metin).

    Brace sayimi string icindeki '}' ile hata yapabilir; json.JSONDecoder.raw_decode kullanilir.
    """
    # Sadece tum yanit bir kod blogu icine sarilmissa fence soy. Aksi halde JSON string
    # degeri icindeki ``` (orn. ornek ciktidaki kod blogu) yanlislikla yakalanir.
    stripped = text.strip()
    if stripped.startswith("```"):
        fence = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL)
        if fence:
            text = fence.group(1).strip()

    decoder = json.JSONDecoder()
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{":
            try:
                obj, _end = decoder.raw_decode(text, i)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        i += 1
    return None


async def _do_request(payload: dict[str, Any]) -> dict | None:
    """Tek bir Ollama isteği gönderir (semaphore korumalı, retry destekli)."""
    client = _get_client()
    sem = _get_semaphore()
    last_exc: Exception | None = None

    for attempt in range(1 + settings.ollama_max_retries):
        async with sem:
            try:
                resp = await client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = _ollama_message_text(data)

                if not content:
                    logger.warning("[ollama] Bos yanit alindi (attempt %d)", attempt + 1)
                    return None

                result = _extract_json(content)
                if result is None:
                    logger.warning("[ollama] JSON parse edilemedi (attempt %d): %s", attempt + 1, content[:200])
                    if attempt < settings.ollama_max_retries:
                        await asyncio.sleep(settings.ollama_retry_delay)
                        continue
                return result

            except httpx.TimeoutException:
                logger.warning("[ollama] Timeout (attempt %d/%d, %ss)", attempt + 1, 1 + settings.ollama_max_retries, settings.ollama_timeout)
                last_exc = None
            except httpx.HTTPStatusError as exc:
                logger.warning("[ollama] HTTP %s (attempt %d)", exc.response.status_code, attempt + 1)
                last_exc = exc
            except Exception as exc:
                logger.warning("[ollama] Hata (attempt %d): %s", attempt + 1, exc)
                last_exc = exc

        if attempt < settings.ollama_max_retries:
            await asyncio.sleep(settings.ollama_retry_delay * (attempt + 1))

    return None


async def _throttle_nvidia_nim() -> None:
    global _last_nim_request_at
    rpm = max(0, int(settings.nvidia_nim_rpm_limit))
    if rpm <= 0:
        return
    min_interval = 60.0 / rpm
    lock = _get_nim_rate_lock()
    async with lock:
        now = time.monotonic()
        wait_for = min_interval - (now - _last_nim_request_at)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        _last_nim_request_at = time.monotonic()


def _nvidia_nim_headers() -> dict[str, str] | None:
    api_key = settings.nvidia_nim_api_key.strip()
    if not api_key:
        logger.warning("[nvidia-nim] API key missing; set NVIDIA_NIM_API_KEY or switch LLM_PROVIDER=ollama")
        return None
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def _post_nvidia_nim(payload: dict[str, Any]) -> str | None:
    headers = _nvidia_nim_headers()
    if headers is None:
        return None

    client = _get_nim_client()
    sem = _get_nim_semaphore()

    for attempt in range(1 + settings.nvidia_nim_max_retries):
        async with sem:
            await _throttle_nvidia_nim()
            try:
                resp = await client.post("/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    logger.warning("[nvidia-nim] Bos choices alindi (attempt %d)", attempt + 1)
                    return None
                content = ((choices[0].get("message") or {}).get("content") or "").strip()
                if content:
                    return content
                logger.warning("[nvidia-nim] Bos yanit alindi (attempt %d)", attempt + 1)
                return None
            except httpx.TimeoutException:
                logger.warning(
                    "[nvidia-nim] Timeout (attempt %d/%d, %ss)",
                    attempt + 1,
                    1 + settings.nvidia_nim_max_retries,
                    settings.nvidia_nim_timeout,
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                logger.warning("[nvidia-nim] HTTP %s (attempt %d)", status_code, attempt + 1)
                if status_code not in {408, 409, 425, 429, 500, 502, 503, 504}:
                    return None
            except Exception as exc:
                logger.warning("[nvidia-nim] Hata (attempt %d): %s", attempt + 1, exc)

        if attempt < settings.nvidia_nim_max_retries:
            await asyncio.sleep(settings.nvidia_nim_retry_delay * (attempt + 1))

    return None


async def _do_nvidia_nim_request(payload: dict[str, Any]) -> dict | None:
    content = await _post_nvidia_nim(payload)
    if not content:
        return None

    result = _extract_json(content)
    if result is None:
        logger.warning("[nvidia-nim] JSON parse edilemedi: %s", content[:200])
    return result


async def _do_nvidia_nim_text_request(payload: dict[str, Any]) -> str | None:
    return await _post_nvidia_nim(payload)

async def _do_ollama_text_request(payload: dict[str, Any]) -> str | None:
    """Tek bir Ollama chat istegi gonderir (duz metin, retry destekli)."""
    client = _get_client()
    sem = _get_semaphore()

    for attempt in range(1 + settings.ollama_max_retries):
        async with sem:
            try:
                resp = await client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = _ollama_message_text(data)
                text = content
                if text:
                    return text
                logger.warning("[ollama] chat_text bos yanit (attempt %d)", attempt + 1)
            except httpx.TimeoutException:
                logger.warning(
                    "[ollama] chat_text timeout (attempt %d/%d)",
                    attempt + 1,
                    1 + settings.ollama_max_retries,
                )
            except httpx.HTTPStatusError as exc:
                logger.warning("[ollama] chat_text HTTP %s", exc.response.status_code)
            except Exception as exc:
                logger.warning("[ollama] chat_text hata: %s", exc)

        if attempt < settings.ollama_max_retries:
            await asyncio.sleep(settings.ollama_retry_delay * (attempt + 1))

    return None


async def _chat_json_request(
    system_prompt: str,
    user_prompt: str,
    schema_hint: dict[str, Any] | None = None,
    temperature: float = 0.0,
    num_predict: int | None = None,
    *,
    model: str | None = None,
    role: LLMRole | None = None,
    use_cache: bool = True,
    provider_override: str | None = None,
) -> ChatJsonResult:
    resolved_role = _resolve_role(model, role)
    provider = _normalize_provider(provider_override) or _provider_for_role(resolved_role)
    provider_is_nim = _provider_is_nvidia_nim(provider)
    provider_name = "nvidia_nim" if provider_is_nim else "ollama"
    selected_model = (
        _model_for_role(resolved_role, nim=True)
        if provider_is_nim
        else _local_model_for_request(model, resolved_role)
    )
    if provider_is_nim:
        # Reasoning modelleri (orn. DeepSeek) max_tokens butcesinin bir kismini dusunmeye
        # harcar; cagiranin istedigi degeri NIM tabaniyla yukseltip JSON'in kirpilmasini onle.
        nim_floor = int(settings.nvidia_nim_num_predict)
        predict = max(int(num_predict), nim_floor) if num_predict is not None else nim_floor
    else:
        predict = _ollama_predict_for_model(selected_model, num_predict)
    cache_key = _cache_key(
        f"{system_prompt}|np={predict}",
        user_prompt,
        temperature,
        selected_model,
        schema_hint,
        resolved_role,
    )
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return ChatJsonResult(
                data=cached,
                provider=provider_name,
                model=selected_model,
                fallback_used=False,
                cache_hit=True,
                max_tokens=predict,
                role=resolved_role,
            )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    fallback_reason = ""
    fallback_used = False
    if provider_is_nim:
        result: dict | None = None
        if settings.nvidia_nim_api_key.strip():
            nim_payload: dict[str, Any] = {
                "model": selected_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": predict,
                "response_format": {"type": "json_object"},
            }
            result = await _do_nvidia_nim_request(nim_payload)
        else:
            logger.warning("[nvidia-nim] API key missing; falling back to local Ollama")
            fallback_reason = "missing_api_key"

        if result is None:
            ollama_model = _local_model_for_request(model, resolved_role)
            ollama_predict = _ollama_predict_for_model(ollama_model, num_predict)
            ollama_payload = {
                "model": ollama_model,
                "messages": messages,
                "stream": False,
                "options": _ollama_inference_options(
                    ollama_model,
                    temperature,
                    ollama_predict,
                    role=resolved_role,
                ),
                "format": "json",
                "keep_alive": "30m",
            }
            _apply_gpt_oss_chat_options(ollama_payload, json_mode=True)
            result = await _do_request(ollama_payload)
            if result is not None:
                provider_name = "ollama"
                selected_model = ollama_model
                predict = ollama_predict
                fallback_used = True
                if not fallback_reason:
                    fallback_reason = "nim_failed_ollama_fallback"
                logger.info("[ollama] nvidia-nim JSON request fell back to local Ollama")
            elif fallback_reason == "missing_api_key":
                fallback_used = True
    else:
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "options": _ollama_inference_options(
                selected_model,
                temperature,
                predict,
                role=resolved_role,
            ),
            "format": "json",
            "keep_alive": "30m",
        }
        _apply_gpt_oss_chat_options(payload, json_mode=True)
        result = await _do_request(payload)

    if result is not None and use_cache:
        _cache_put(cache_key, result)

    error = None if result is not None else (fallback_reason or "empty_or_unparseable")
    return ChatJsonResult(
        data=result,
        provider=provider_name,
        model=selected_model,
        fallback_used=fallback_used,
        error=error,
        max_tokens=predict,
        fallback_reason=fallback_reason,
        role=resolved_role,
    )


async def chat_json(
    system_prompt: str,
    user_prompt: str,
    schema_hint: dict[str, Any] | None = None,
    temperature: float = 0.0,
    num_predict: int | None = None,
    *,
    model: str | None = None,
    role: LLMRole | None = None,
    use_cache: bool = True,
    provider_override: str | None = None,
) -> dict | None:
    """Ollama chat endpoint'ine istek gonderir ve JSON parse eder.

    Args:
        num_predict: Token limiti; None ise ayarlardan. Uzun JSON listeleri icin artirin.
        use_cache: False ise LRU onbellek atlanir (aynı prompt için yeni liste gibi senaryolar).
    """
    if not settings.ollama_enabled:
        return None

    result = await _chat_json_request(
        system_prompt,
        user_prompt,
        schema_hint,
        temperature,
        num_predict,
        model=model,
        role=role,
        use_cache=use_cache,
        provider_override=provider_override,
    )
    if result.cache_hit:
        _record_call_metadata(
            function="chat_json",
            provider=result.provider,
            model=result.model,
            cache_hit=True,
            result_status="ok",
            response_format="json",
            max_tokens=result.max_tokens,
            role=result.role,
        )
        return result.data

    metadata_fallback = (
        ""
        if result.data is not None and not result.fallback_reason
        else (result.fallback_reason or "empty_or_unparseable")
    )
    _record_call_metadata(
        function="chat_json",
        provider=result.provider,
        model=result.model,
        cache_hit=False,
        result_status="ok" if result.data is not None else "failed",
        response_format="json",
        max_tokens=result.max_tokens,
        fallback_reason=metadata_fallback,
        role=result.role,
    )
    return result.data


async def chat_json_with_metadata(
    system_prompt: str,
    user_prompt: str,
    schema_hint: dict[str, Any] | None = None,
    temperature: float = 0.0,
    num_predict: int | None = None,
    *,
    model: str | None = None,
    role: LLMRole | None = None,
    use_cache: bool = True,
    provider_override: str | None = None,
) -> ChatJsonResult:
    if not settings.ollama_enabled:
        return ChatJsonResult(
            data=None,
            provider="",
            model=model or "",
            fallback_used=False,
            error="ollama_disabled",
            role=_resolve_role(model, role),
        )
    return await _chat_json_request(
        system_prompt,
        user_prompt,
        schema_hint,
        temperature,
        num_predict,
        model=model,
        role=role,
        use_cache=use_cache,
        provider_override=provider_override,
    )


async def chat_text(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.45,
    num_predict: int | None = None,
    model: str | None = None,
    role: LLMRole | None = None,
) -> str | None:
    """Ollama chat — düz metin (JSON formatı yok). Eğitim asistanı ve sohbet botları için.

    ``messages``: OpenAI tarzı ``{"role": "system"|"user"|"assistant", "content": "..."}`` listesi.
    """
    if not settings.ollama_enabled:
        return None
    if not messages:
        return None

    resolved_role = _resolve_role(model, role)
    predict = num_predict if num_predict is not None else min(int(settings.ollama_num_predict), 2048)
    provider_is_nim = _provider_is_nvidia_nim(_provider_for_role(resolved_role))
    provider_name = "nvidia_nim" if provider_is_nim else "ollama"
    selected_model = (
        _model_for_role(resolved_role, nim=True)
        if provider_is_nim
        else _local_model_for_request(model, resolved_role)
    )
    if not provider_is_nim:
        predict = _ollama_predict_for_model(selected_model, num_predict)

    fallback_reason = ""
    if provider_is_nim:
        text_result: str | None = None
        # Reasoning modelleri icin NIM token tabanini uygula.
        nim_predict = max(int(predict), int(settings.nvidia_nim_num_predict))
        if settings.nvidia_nim_api_key.strip():
            nim_payload: dict[str, Any] = {
                "model": selected_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": nim_predict,
            }
            text_result = await _do_nvidia_nim_text_request(nim_payload)
        else:
            logger.warning("[nvidia-nim] API key missing; falling back to local Ollama")
            fallback_reason = "missing_api_key"

        if text_result:
            _record_call_metadata(
                function="chat_text",
                provider=provider_name,
                model=selected_model,
                cache_hit=False,
                result_status="ok",
                response_format="text",
                max_tokens=nim_predict,
                role=resolved_role,
            )
            return text_result

        ollama_model = _local_model_for_request(model, resolved_role)
        ollama_predict = _ollama_predict_for_model(ollama_model, num_predict)
        ollama_payload: dict[str, Any] = {
            "model": ollama_model,
            "messages": messages,
            "stream": False,
            "options": _ollama_inference_options(
                ollama_model,
                temperature,
                ollama_predict,
                role=resolved_role,
            ),
            "keep_alive": "30m",
        }
        _apply_gpt_oss_chat_options(ollama_payload, json_mode=False)
        text_result = await _do_ollama_text_request(ollama_payload)
        if text_result:
            if not fallback_reason:
                fallback_reason = "nim_failed_ollama_fallback"
            _record_call_metadata(
                function="chat_text",
                provider="ollama",
                model=ollama_model,
                cache_hit=False,
                result_status="ok",
                response_format="text",
                max_tokens=ollama_predict,
                fallback_reason=fallback_reason,
                role=resolved_role,
            )
            logger.info("[ollama] nvidia-nim text request fell back to local Ollama")
            return text_result

        _record_call_metadata(
            function="chat_text",
            provider=provider_name,
            model=selected_model,
            cache_hit=False,
            result_status="failed",
            response_format="text",
            max_tokens=predict,
            fallback_reason=fallback_reason or "empty_response",
            role=resolved_role,
        )
        return None

    payload: dict[str, Any] = {
        "model": selected_model,
        "messages": messages,
        "stream": False,
        "options": _ollama_inference_options(
            selected_model,
            temperature,
            predict,
            role=resolved_role,
        ),
        "keep_alive": "30m",
    }
    _apply_gpt_oss_chat_options(payload, json_mode=False)

    text_result = await _do_ollama_text_request(payload)
    if text_result:
        _record_call_metadata(
            function="chat_text",
            provider=provider_name,
            model=selected_model,
            cache_hit=False,
            result_status="ok",
            response_format="text",
            max_tokens=predict,
            role=resolved_role,
        )
        return text_result

    _record_call_metadata(
        function="chat_text",
        provider=provider_name,
        model=selected_model,
        cache_hit=False,
        result_status="failed",
        response_format="text",
        max_tokens=predict,
        fallback_reason="empty_or_failed",
        role=resolved_role,
    )
    return None
