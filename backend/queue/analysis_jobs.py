from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol


class RedisLike(Protocol):
    def hset(self, key: str, mapping: dict[str, str | int]) -> Awaitable[Any]: ...
    def hgetall(self, key: str) -> Awaitable[dict[Any, Any]]: ...
    def expire(self, key: str, seconds: int) -> Awaitable[Any]: ...
    def xadd(self, stream: str, fields: dict[str, str]) -> Awaitable[Any]: ...
    def set(self, key: str, value: str, ex: int | None = None) -> Awaitable[Any]: ...
    def get(self, key: str) -> Awaitable[Any]: ...
    def scan_iter(self, match: str) -> Any: ...


class AnalysisJobNotFound(Exception):
    """Raised when a requested analysis job does not exist."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_id() -> str:
    return str(uuid.uuid4())


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads_optional(raw: Any) -> Any:
    raw = _decode(raw)
    if raw in (None, ""):
        return None
    return json.loads(str(raw))


class AnalysisJobStore:
    def __init__(
        self,
        redis: RedisLike,
        *,
        stream_name: str = "stream:analysis_jobs",
        job_ttl_seconds: int = 86400,
        id_factory: Callable[[], str] = _default_id,
        clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.redis = redis
        self.stream_name = stream_name
        self.job_ttl_seconds = job_ttl_seconds
        self.id_factory = id_factory
        self.clock = clock

    def key(self, job_id: str) -> str:
        return f"analysis_job:{job_id}"


async def create_analysis_job(store: AnalysisJobStore, request: dict[str, Any]) -> dict[str, Any]:
    job_id = store.id_factory()
    now = store.clock()
    key = store.key(job_id)
    await store.redis.hset(
        key,
        mapping={
            "job_id": job_id,
            "status": "queued",
            "request": _json_dumps(request),
            "created_at": now,
            "updated_at": now,
            "attempts": 0,
        },
    )
    await store.redis.expire(key, store.job_ttl_seconds)
    await store.redis.xadd(store.stream_name, {"job_id": job_id})
    return {"job_id": job_id, "status": "queued", "created_at": now, "updated_at": now}


async def get_analysis_job(store: AnalysisJobStore, job_id: str) -> dict[str, Any]:
    raw = await store.redis.hgetall(store.key(job_id))
    if not raw:
        raise AnalysisJobNotFound(job_id)

    decoded = {str(_decode(k)): _decode(v) for k, v in raw.items()}
    job: dict[str, Any] = {
        "job_id": str(decoded.get("job_id", job_id)),
        "status": str(decoded.get("status", "queued")),
        "created_at": decoded.get("created_at"),
        "updated_at": decoded.get("updated_at"),
        "attempts": int(decoded.get("attempts") or 0),
    }
    for field in ("started_at", "finished_at", "error", "report_status"):
        if decoded.get(field):
            job[field] = decoded[field]
    request = _loads_optional(decoded.get("request"))
    if request is not None:
        job["request"] = request
    result = _loads_optional(decoded.get("result"))
    if result is not None:
        job["result"] = result
    return job


async def mark_analysis_job_running(store: AnalysisJobStore, job_id: str) -> dict[str, Any]:
    job = await get_analysis_job(store, job_id)
    attempts = int(job.get("attempts", 0)) + 1
    now = store.clock()
    await store.redis.hset(
        store.key(job_id),
        mapping={
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "attempts": attempts,
            "report_status": "preparing",
        },
    )
    await store.redis.expire(store.key(job_id), store.job_ttl_seconds)
    return await get_analysis_job(store, job_id)


async def update_analysis_job_result(
    store: AnalysisJobStore,
    job_id: str,
    result: dict[str, Any],
    *,
    report_status: str = "preparing",
) -> dict[str, Any]:
    now = store.clock()
    await store.redis.hset(
        store.key(job_id),
        mapping={"result": _json_dumps(result), "report_status": report_status, "updated_at": now},
    )
    await store.redis.expire(store.key(job_id), store.job_ttl_seconds)
    return await get_analysis_job(store, job_id)


async def mark_analysis_job_completed(store: AnalysisJobStore, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    now = store.clock()
    await store.redis.hset(
        store.key(job_id),
        mapping={
            "status": "completed",
            "result": _json_dumps(result),
            "finished_at": now,
            "updated_at": now,
            "report_status": "ready",
        },
    )
    await store.redis.expire(store.key(job_id), store.job_ttl_seconds)
    return await get_analysis_job(store, job_id)


async def fail_analysis_job(store: AnalysisJobStore, job_id: str, error: str) -> dict[str, Any]:
    job = await get_analysis_job(store, job_id)
    attempts = max(1, int(job.get("attempts", 0)))
    now = store.clock()
    await store.redis.hset(
        store.key(job_id),
        mapping={"status": "failed", "error": error, "finished_at": now, "updated_at": now, "attempts": attempts},
    )
    await store.redis.expire(store.key(job_id), store.job_ttl_seconds)
    return await get_analysis_job(store, job_id)


def create_redis_client(redis_url: str):
    from redis.asyncio import Redis

    return Redis.from_url(redis_url, decode_responses=True)
