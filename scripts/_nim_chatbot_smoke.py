"""Quick NIM chatbot smoke test."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip()


async def main() -> None:
    from backend.core.config import settings
    from backend.llm.ollama_client import chat_json

    print(f"general_provider={settings.llm_general_provider}")
    print(f"nim_model={settings.nvidia_nim_general_model}")
    result = await chat_json(
        system_prompt='{"suggestions":[{"title":"t","summary":"s","description":"d"}]} JSON only.',
        user_prompt="Tek oneri: CSV dosyasindan not okuyup rapor yazan CLI programi odevi.",
        temperature=0.2,
        num_predict=512,
        model=settings.ollama_general_model,
        use_cache=False,
    )
    print("ok", bool(result))
    if isinstance(result, dict):
        row = (result.get("suggestions") or [{}])[0]
        print("title", str(row.get("title", ""))[:100])


if __name__ == "__main__":
    asyncio.run(main())
