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
from typing import Any

import httpx

from backend.core.config import settings

logger = logging.getLogger(__name__)

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


def _provider_for_model(model: str | None) -> str:
    default = _llm_provider()
    general_provider = _normalize_provider(settings.llm_general_provider) or default
    coder_provider = _normalize_provider(settings.llm_coder_provider) or default
    if model == settings.ollama_coder_model:
        return coder_provider
    if model is None or model == settings.ollama_general_model:
        return general_provider
    return default


def _provider_is_nvidia_nim(provider: str) -> bool:
    return provider in {"nvidia_nim", "nim", "nvidia"}


def _select_nim_model(model: str | None) -> str:
    if model is None or model == settings.ollama_general_model:
        return settings.nvidia_nim_general_model
    if model == settings.ollama_coder_model:
        return settings.nvidia_nim_coder_model
    return model


def _cache_key(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    model: str,
    schema_hint: dict[str, Any] | None = None,
) -> str:
    schema_part = ""
    if schema_hint:
        schema_part = json.dumps(schema_hint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = f"{model}:{temperature}:{schema_part}:{system_prompt}:{user_prompt}"
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
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
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
                content = data.get("message", {}).get("content", "")

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


async def chat_json(
    system_prompt: str,
    user_prompt: str,
    schema_hint: dict[str, Any] | None = None,
    temperature: float = 0.3,
    num_predict: int | None = None,
    *,
    model: str | None = None,
    use_cache: bool = True,
) -> dict | None:
    """Ollama chat endpoint'ine istek gonderir ve JSON parse eder.

    Args:
        num_predict: Token limiti; None ise ayarlardan. Uzun JSON listeleri icin artirin.
        use_cache: False ise LRU onbellek atlanir (aynı prompt için yeni liste gibi senaryolar).
    """
    if not settings.ollama_enabled:
        return None

    provider_is_nim = _provider_is_nvidia_nim(_provider_for_model(model))
    provider_name = "nvidia_nim" if provider_is_nim else "ollama"
    selected_model = _select_nim_model(model) if provider_is_nim else (model or settings.ollama_general_model)
    if provider_is_nim:
        predict = int(num_predict) if num_predict is not None else int(settings.nvidia_nim_num_predict)
    else:
        predict = int(num_predict) if num_predict is not None else int(settings.ollama_num_predict)
    cache_key = _cache_key(f"{system_prompt}|np={predict}", user_prompt, temperature, selected_model, schema_hint)
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            _record_call_metadata(
                function="chat_json",
                provider=provider_name,
                model=selected_model,
                cache_hit=True,
                result_status="ok",
                response_format="json",
                max_tokens=predict,
            )
            return cached

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    if provider_is_nim:
        if not settings.nvidia_nim_api_key.strip():
            logger.warning("[nvidia-nim] API key missing; JSON request skipped")
            _record_call_metadata(
                function="chat_json",
                provider=provider_name,
                model=selected_model,
                cache_hit=False,
                result_status="skipped",
                response_format="json",
                max_tokens=predict,
                fallback_reason="missing_api_key",
            )
            return None
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": predict,
            "response_format": {"type": "json_object"},
        }
        result = await _do_nvidia_nim_request(payload)
    else:
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": predict,
            },
            "format": schema_hint if schema_hint else "json",
            "keep_alive": "30m",
        }
        result = await _do_request(payload)

    if result is not None and use_cache:
        _cache_put(cache_key, result)
    _record_call_metadata(
        function="chat_json",
        provider=provider_name,
        model=selected_model,
        cache_hit=False,
        result_status="ok" if result is not None else "failed",
        response_format="json",
        max_tokens=predict,
        fallback_reason="" if result is not None else "empty_or_unparseable",
    )
    return result


async def chat_text(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.45,
    num_predict: int | None = None,
    model: str | None = None,
) -> str | None:
    """Ollama chat — düz metin (JSON formatı yok). Eğitim asistanı ve sohbet botları için.

    ``messages``: OpenAI tarzı ``{"role": "system"|"user"|"assistant", "content": "..."}`` listesi.
    """
    if not settings.ollama_enabled:
        return None
    if not messages:
        return None

    predict = num_predict if num_predict is not None else min(int(settings.ollama_num_predict), 2048)
    provider_is_nim = _provider_is_nvidia_nim(_provider_for_model(model))
    provider_name = "nvidia_nim" if provider_is_nim else "ollama"
    selected_model = _select_nim_model(model) if provider_is_nim else (model or settings.ollama_general_model)

    if provider_is_nim:
        if not settings.nvidia_nim_api_key.strip():
            logger.warning("[nvidia-nim] API key missing; text request skipped")
            _record_call_metadata(
                function="chat_text",
                provider=provider_name,
                model=selected_model,
                cache_hit=False,
                result_status="skipped",
                response_format="text",
                max_tokens=predict,
                fallback_reason="missing_api_key",
            )
            return None
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": predict,
        }
        text_result = await _do_nvidia_nim_text_request(payload)
        _record_call_metadata(
            function="chat_text",
            provider=provider_name,
            model=selected_model,
            cache_hit=False,
            result_status="ok" if text_result else "failed",
            response_format="text",
            max_tokens=predict,
            fallback_reason="" if text_result else "empty_response",
        )
        return text_result

    payload: dict[str, Any] = {
        "model": selected_model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": predict,
        },
        "keep_alive": "30m",
    }

    client = _get_client()
    sem = _get_semaphore()

    for attempt in range(1 + settings.ollama_max_retries):
        async with sem:
            try:
                resp = await client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = (data.get("message") or {}).get("content") or ""
                text = content.strip()
                if text:
                    _record_call_metadata(
                        function="chat_text",
                        provider=provider_name,
                        model=selected_model,
                        cache_hit=False,
                        result_status="ok",
                        response_format="text",
                        max_tokens=predict,
                    )
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

    _record_call_metadata(
        function="chat_text",
        provider=provider_name,
        model=selected_model,
        cache_hit=False,
        result_status="failed",
        response_format="text",
        max_tokens=predict,
        fallback_reason="empty_or_failed",
    )
    return None
