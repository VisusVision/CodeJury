"""Diagnose NVIDIA NIM connectivity, model availability, and latency."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load .env manually if dotenv not wired
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


async def main() -> int:
    import httpx
    from backend.core.config import settings
    from backend.llm.ollama_client import chat_json, chat_text

    base = settings.nvidia_nim_base_url.rstrip("/")
    key = settings.nvidia_nim_api_key.strip()
    model = settings.nvidia_nim_general_model
    timeout = settings.nvidia_nim_timeout

    print("=== NVIDIA NIM Config ===")
    print(f"base_url: {base}")
    print(f"model: {model}")
    print(f"timeout: {timeout}s")
    print(f"num_predict floor: {settings.nvidia_nim_num_predict}")
    print(f"max_concurrent: {settings.nvidia_nim_max_concurrent}")
    print(f"rpm_limit: {settings.nvidia_nim_rpm_limit}")
    print(f"api_key: {'set (' + str(len(key)) + ' chars)' if key else 'MISSING'}")

    if not key:
        print("ERROR: NVIDIA_NIM_API_KEY missing")
        return 1

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # 1) List models (optional endpoint)
    print("\n=== Test 1: models list ===")
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(30.0, connect=15.0)) as client:
            resp = await client.get("/models", headers=headers)
            elapsed = time.perf_counter() - t0
            print(f"HTTP {resp.status_code} in {elapsed:.1f}s")
            if resp.status_code == 200:
                data = resp.json()
                ids = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)]
                match = model in ids
                print(f"models count: {len(ids)}")
                print(f"configured model present: {match}")
                if not match:
                    close = [i for i in ids if i and ("deepseek" in i.lower() or "qwen" in i.lower())][:8]
                    print(f"similar models: {close}")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")

    # 2) Tiny chat completion
    print("\n=== Test 2: tiny chat (max_tokens=64) ===")
    payload_small = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 64,
        "temperature": 0,
    }
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(timeout, connect=30.0)) as client:
            resp = await client.post("/chat/completions", json=payload_small, headers=headers)
            elapsed = time.perf_counter() - t0
            print(f"HTTP {resp.status_code} in {elapsed:.1f}s")
            if resp.status_code != 200:
                print(resp.text[:500])
            else:
                content = (((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "")
                usage = resp.json().get("usage") or {}
                print(f"content: {content[:120]!r}")
                print(f"usage: {usage}")
    except httpx.TimeoutException:
        print(f"TIMEOUT after {time.perf_counter() - t0:.1f}s (limit {timeout}s)")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")

    # 3) JSON via app client (8192 floor like production)
    print("\n=== Test 3: chat_json via ollama_client (production path) ===")
    os.environ["LLM_PROVIDER"] = "nvidia_nim"
    os.environ["LLM_GENERAL_PROVIDER"] = "nvidia_nim"
    from backend.core.config import Settings

    # reload settings if cached - settings is usually singleton
    t0 = time.perf_counter()
    try:
        result = await chat_json(
            system_prompt='Reply ONLY JSON: {"status":"ok","value":1}',
            user_prompt="ping",
            temperature=0.0,
            num_predict=256,
            provider_override="nvidia_nim",
            use_cache=False,
        )
        elapsed = time.perf_counter() - t0
        print(f"elapsed: {elapsed:.1f}s")
        print(f"result: {result}")
        if result is None:
            print("RESULT IS None -> likely timeout or parse fail -> Ollama fallback may trigger")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")

    # 4) Medium JSON (simulates agent)
    print("\n=== Test 4: medium JSON agent-like prompt ===")
    t0 = time.perf_counter()
    try:
        result = await chat_json(
            system_prompt=(
                "You are a test agent. Reply ONLY valid JSON with keys: "
                "score (0-100 int), summary (string), items (array of 3 strings)."
            ),
            user_prompt="Evaluate this code: def add(a,b): return a+b",
            temperature=0.0,
            num_predict=1024,
            provider_override="nvidia_nim",
            use_cache=False,
        )
        elapsed = time.perf_counter() - t0
        print(f"elapsed: {elapsed:.1f}s")
        print(f"result keys: {list(result.keys()) if isinstance(result, dict) else result}")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
