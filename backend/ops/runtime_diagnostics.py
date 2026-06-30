"""Read-only runtime snapshots for health checks and analysis diagnostics."""

from __future__ import annotations

import os
from typing import Any

from backend.core.config import settings


def get_llm_config_snapshot() -> dict[str, Any]:
    """Active LLM configuration from env (not pinned in code)."""
    provider = (settings.llm_provider or "ollama").strip().lower()
    return {
        "enabled": bool(settings.ollama_enabled),
        "provider": provider,
        "general_model": settings.ollama_general_model,
        "coder_model": settings.ollama_coder_model,
        "base_url": settings.ollama_base_url,
        "max_concurrent": int(settings.ollama_max_concurrent),
    }


def get_sandbox_pool_snapshot() -> dict[str, Any]:
    """Docker sandbox pool status; simulation when pool is absent or not ready."""
    try:
        from backend.sandbox.pool_manager import get_pool

        pool = get_pool()
    except Exception:
        pool = None

    if pool is None or not pool.is_ready:
        return {
            "mode": "simulation",
            "pool_ready": False,
            "container_count": 0,
            "available_count": 0,
        }

    return {
        "mode": "pool",
        "pool_ready": True,
        "container_count": len(pool._slots),
        "available_count": pool.available_count,
    }


def build_analysis_runtime_meta(
    *,
    pipeline_ms: int,
    sandbox_backend: str | None = None,
) -> dict[str, Any]:
    """Per-analysis runtime block embedded in agentDiagnostics."""
    sandbox = get_sandbox_pool_snapshot()
    execution = str(sandbox_backend or sandbox["mode"]).strip().lower()
    if execution not in {"pool", "simulation"}:
        execution = "simulation" if execution in {"", "unknown"} else execution

    return {
        "llm": get_llm_config_snapshot(),
        "sandbox": {
            **sandbox,
            "execution_backend": execution,
        },
        "pipeline_ms": max(0, int(pipeline_ms)),
    }


def try_initialize_sandbox_pool(
    *,
    pool_size: int,
    base_port: int,
    timeout_s: float,
) -> str:
    """Start Docker sandbox pool from env overrides; return execution mode label."""
    os.environ["SANDBOX_POOL_SIZE"] = str(pool_size)
    os.environ["SANDBOX_POOL_BASE_PORT"] = str(base_port)
    os.environ["SANDBOX_POOL_TIMEOUT"] = str(timeout_s)
    from backend.sandbox.pool_manager import get_pool, initialize_pool

    initialize_pool()
    pool = get_pool()
    if pool is not None and pool.is_ready:
        return "pool"
    return "simulation"
