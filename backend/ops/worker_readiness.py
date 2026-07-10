"""Worker heartbeat publishing and readiness aggregation.

Redis TTL is the staleness mechanism — expired heartbeat keys disappear from
``scan_iter`` results and cannot satisfy ``analysis_ready``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.sandbox.pool_manager import get_pool

HEARTBEAT_PREFIX = "analysis_worker:heartbeat:"
DEFAULT_TTL_SECONDS = 15


def heartbeat_key(worker_id: str) -> str:
    return f"{HEARTBEAT_PREFIX}{worker_id}"


def build_local_heartbeat(worker_id: str, *, analysis_engine: str) -> dict[str, object]:
    pool = get_pool()
    if pool is None:
        snapshot = {
            "state": "unavailable",
            "pool_ready": False,
            "container_count": 0,
            "available_count": 0,
            "target_size": 0,
            "last_error_code": "pool_missing",
        }
    else:
        snapshot = pool.snapshot()
    return {
        "worker_id": worker_id,
        "status": snapshot["state"],
        "pool_ready": bool(snapshot["pool_ready"]),
        "container_count": int(snapshot["container_count"]),
        "available_count": int(snapshot["available_count"]),
        "target_size": int(snapshot["target_size"]),
        "last_error_code": snapshot["last_error_code"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_engine": analysis_engine,
    }


async def publish_worker_heartbeat(
    redis: Any,
    heartbeat: dict[str, object],
    *,
    ttl_s: int = DEFAULT_TTL_SECONDS,
) -> None:
    worker_id = str(heartbeat["worker_id"])
    await redis.set(
        heartbeat_key(worker_id),
        json.dumps(heartbeat, ensure_ascii=False, separators=(",", ":")),
        ex=ttl_s,
    )


async def get_worker_readiness(redis: Any) -> dict[str, object]:
    workers: list[dict[str, object]] = []
    async for key in redis.scan_iter(match=f"{HEARTBEAT_PREFIX}*"):
        raw = await redis.get(key)
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            workers.append(item)

    usable = [
        row for row in workers
        if bool(row.get("pool_ready")) and int(row.get("container_count", 0)) > 0
    ]
    analysis_ready = bool(usable)
    fully_ready = (
        analysis_ready
        and len(usable) == len(workers)
        and all(row.get("status") == "ready" for row in usable)
    )
    return {
        "status": "ok" if fully_ready else "degraded",
        "analysis_ready": analysis_ready,
        "worker_count": len(workers),
        "ready_worker_count": len(usable),
        "sandbox": {
            "mode": "pool" if analysis_ready else "unavailable",
            "pool_ready": analysis_ready,
            "container_count": sum(int(row.get("container_count", 0)) for row in usable),
            "available_count": sum(int(row.get("available_count", 0)) for row in usable),
            "target_size": sum(int(row.get("target_size", 0)) for row in usable),
        },
    }
