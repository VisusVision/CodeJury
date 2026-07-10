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


def get_local_sandbox_pool_snapshot() -> dict[str, Any]:
    """This process's own local sandbox pool snapshot (diagnostics only)."""
    try:
        from backend.sandbox.pool_manager import get_pool

        pool = get_pool()
    except Exception:
        pool = None

    if pool is None:
        return {
            "mode": "unavailable",
            "state": "unavailable",
            "pool_ready": False,
            "container_count": 0,
            "available_count": 0,
        }

    snapshot = pool.snapshot()
    return {
        "mode": "pool" if snapshot["pool_ready"] else "unavailable",
        "state": snapshot["state"],
        "pool_ready": snapshot["pool_ready"],
        "container_count": snapshot["container_count"],
        "available_count": snapshot["available_count"],
    }


def build_analysis_runtime_meta(
    *,
    pipeline_ms: int,
    sandbox_backend: str | None = None,
) -> dict[str, Any]:
    """Per-analysis runtime block embedded in agentDiagnostics."""
    sandbox = get_local_sandbox_pool_snapshot()
    execution = str(sandbox_backend or sandbox["mode"]).strip().lower()
    if execution not in {"pool", "unavailable"}:
        execution = "unavailable" if execution in {"", "unknown", "simulation"} else execution

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
    if pool is not None and pool.snapshot()["pool_ready"]:
        return "pool"
    return "unavailable"
