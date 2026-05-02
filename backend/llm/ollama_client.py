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

_cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()
_CACHE_MAX_SIZE = 128
_CACHE_TTL_SECONDS = 600


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.ollama_max_concurrent)
    return _semaphore


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.ollama_timeout, connect=30.0),
        )
    return _client


def _cache_key(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    schema_hint: dict[str, Any] | None = None,
) -> str:
    schema_part = ""
    if schema_hint:
        schema_part = json.dumps(schema_hint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = f"{settings.ollama_model}:{temperature}:{schema_part}:{system_prompt}:{user_prompt}"
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
    try:
        client = _get_client()
        resp = await client.post("/api/chat", json={
            "model": settings.ollama_model,
            "messages": [{"role": "user", "content": "warmup"}],
            "stream": False,
            "keep_alive": "30m",
        })
        resp.raise_for_status()
        logger.info("[ollama] Model bellege yuklendi ve 30dk tutulacak")
        return True
    except Exception as exc:
        logger.warning("[ollama] Warmup basarisiz: %s", exc)
        return False


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


async def chat_json(
    system_prompt: str,
    user_prompt: str,
    schema_hint: dict[str, Any] | None = None,
    temperature: float = 0.3,
    num_predict: int | None = None,
    *,
    use_cache: bool = True,
) -> dict | None:
    """Ollama chat endpoint'ine istek gonderir ve JSON parse eder.

    Args:
        num_predict: Token limiti; None ise ayarlardan. Uzun JSON listeleri icin artirin.
        use_cache: False ise LRU onbellek atlanir (aynı prompt için yeni liste gibi senaryolar).
    """
    if not settings.ollama_enabled:
        return None

    predict = int(num_predict) if num_predict is not None else int(settings.ollama_num_predict)
    cache_key = _cache_key(f"{system_prompt}|np={predict}", user_prompt, temperature, schema_hint)
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    payload: dict[str, Any] = {
        "model": settings.ollama_model,
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
    return result


async def chat_text(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.45,
    num_predict: int | None = None,
) -> str | None:
    """Ollama chat — düz metin (JSON formatı yok). Eğitim asistanı ve sohbet botları için.

    ``messages``: OpenAI tarzı ``{"role": "system"|"user"|"assistant", "content": "..."}`` listesi.
    """
    if not settings.ollama_enabled:
        return None
    if not messages:
        return None

    predict = num_predict if num_predict is not None else min(int(settings.ollama_num_predict), 2048)

    payload: dict[str, Any] = {
        "model": settings.ollama_model,
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
