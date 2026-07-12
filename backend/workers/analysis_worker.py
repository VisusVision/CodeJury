from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.agents.base import LLMInferenceError
from backend.core.config import settings
from backend.ops.worker_readiness import build_local_heartbeat, publish_worker_heartbeat
from backend.queue.analysis_jobs import (
    AnalysisJobNotFound,
    AnalysisJobStore,
    create_redis_client,
    fail_analysis_job,
    get_analysis_job,
    mark_analysis_job_completed,
    mark_analysis_job_running,
    update_analysis_job_result,
)
from backend.sandbox.errors import SandboxUnavailableError
from backend.sandbox.pool_manager import get_pool, initialize_pool, reinitialize_pool, shutdown_pool

logger = logging.getLogger(__name__)

PipelineCallable = Callable[..., Awaitable[dict[str, Any]]]
SAFE_ANALYSIS_ERROR = "Analiz tamamlanamadi. Lutfen tekrar deneyin."
PIPELINE_TIMEOUT_ERROR = "Analiz zaman asimina ugradi. Lutfen tekrar deneyin."
LLM_UNAVAILABLE_ERROR = (
    "AI analiz servisi kullanilamiyor. Ollama acik ve model kurulu oldugundan emin olun, "
    "sonra analizi tekrar baslatin."
)
SANDBOX_UNAVAILABLE_ERROR = (
    "Sandbox kullanılamıyor; Docker ve analysis worker pool durumunu kontrol edip tekrar deneyin."
)
_PIPELINE_RELOAD_MODULES = (
    "backend.agents.base",
    "backend.agents.json_output_schema",
    "backend.agents.code_quality",
    "backend.agents.algorithm",
    "backend.agents.ai_authorship",
    "backend.agents.guideline",
    "backend.agents.evidence",
    "backend.agents.seniority",
    "backend.agents.task_relevance",
    "backend.agents.master_evaluator",
    "backend.agents.test_agent",
    "backend.agents.security",
    "backend.sandbox.fixtures",
    "backend.sandbox.executor",
    "frontend.backend.main",
)


def worker_id() -> str:
    return os.getenv("ANALYSIS_WORKER_ID", "").strip() or f"{socket.gethostname()}-{os.getpid()}"


def worker_pool_ready() -> bool:
    pool = get_pool()
    return bool(pool is not None and pool.snapshot()["pool_ready"])


def _worker_reload_enabled() -> bool:
    return os.getenv("ANALYSIS_WORKER_RELOAD", "1").strip().lower() in {"1", "true", "yes", "on"}


def _reload_pipeline_modules() -> None:
    import importlib

    for name in _PIPELINE_RELOAD_MODULES:
        module = sys.modules.get(name)
        if module is not None:
            importlib.reload(module)


async def _default_pipeline(**kwargs: Any) -> dict[str, Any]:
    if _worker_reload_enabled():
        _reload_pipeline_modules()
    from frontend.backend.main import run_analysis_pipeline

    return await run_analysis_pipeline(**kwargs)


async def process_analysis_job(
    store: AnalysisJobStore,
    job_id: str,
    *,
    pipeline: PipelineCallable = _default_pipeline,
) -> dict[str, Any]:
    job = await mark_analysis_job_running(store, job_id)
    request = dict(job.get("request") or {})
    try:
        result = await asyncio.wait_for(
            pipeline(
                file_name=str(request.get("file_name") or "unknown.py"),
                file_content=str(request.get("file_content") or ""),
                assignment_id=request.get("assignment_id"),
                assignment_brief=str(request.get("assignment_brief") or ""),
                faculty_rubric_criteria=request.get("faculty_rubric_criteria") or [],
                report_language=str(request.get("report_language") or "tr"),
                progress_callback=lambda partial_result: update_analysis_job_result(
                    store,
                    job_id,
                    partial_result,
                    report_status="preparing",
                ),
            ),
            timeout=settings.analysis_pipeline_timeout_seconds,
        )
        return await mark_analysis_job_completed(store, job_id, result)
    except asyncio.TimeoutError:
        logger.exception("analysis job timed out: %s", job_id)
        return await fail_analysis_job(store, job_id, PIPELINE_TIMEOUT_ERROR)
    except LLMInferenceError:
        logger.exception("analysis job failed because LLM is unavailable: %s", job_id)
        return await fail_analysis_job(store, job_id, LLM_UNAVAILABLE_ERROR)
    except SandboxUnavailableError:
        logger.exception("analysis job failed because sandbox is unavailable: %s", job_id)
        return await fail_analysis_job(store, job_id, SANDBOX_UNAVAILABLE_ERROR)
    except Exception:
        logger.exception("analysis job failed: %s", job_id)
        return await fail_analysis_job(store, job_id, SAFE_ANALYSIS_ERROR)


async def sandbox_pool_recovery_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        if not worker_pool_ready():
            try:
                await asyncio.to_thread(reinitialize_pool)
            except Exception:
                logger.exception("analysis worker sandbox pool recovery failed")
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.analysis_worker_sandbox_retry_seconds,
            )
        except asyncio.TimeoutError:
            pass


async def worker_heartbeat_loop(
    redis: Any,
    current_worker_id: str,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            heartbeat = build_local_heartbeat(
                current_worker_id,
                analysis_engine=os.getenv("ANALYSIS_ENGINE_VERSION", "2.1.0-rubrik"),
            )
            await publish_worker_heartbeat(
                redis,
                heartbeat,
                ttl_s=settings.analysis_worker_heartbeat_ttl_seconds,
            )
        except Exception:
            logger.exception("analysis worker heartbeat publish failed")
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.analysis_worker_heartbeat_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass


async def ensure_consumer_group(redis: Any, stream_name: str, group_name: str) -> None:
    try:
        await redis.xgroup_create(stream_name, group_name, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def consume_analysis_jobs(
    store: AnalysisJobStore,
    *,
    group_name: str = "group:analysis_workers",
    consumer_name: str | None = None,
    block_ms: int = 5000,
) -> None:
    consumer = consumer_name or f"worker-{os.getpid()}"
    await ensure_consumer_group(store.redis, store.stream_name, group_name)
    logger.info("analysis worker listening stream=%s group=%s consumer=%s", store.stream_name, group_name, consumer)
    while True:
        if not worker_pool_ready():
            await asyncio.sleep(1)
            continue
        response = await store.redis.xreadgroup(
            group_name,
            consumer,
            {store.stream_name: ">"},
            count=1,
            block=block_ms,
        )
        if not response:
            continue
        for stream, messages in response:
            for message_id, fields in messages:
                job_id = fields.get("job_id") if isinstance(fields, dict) else None
                if isinstance(job_id, bytes):
                    job_id = job_id.decode("utf-8")
                if not job_id:
                    await store.redis.xack(stream, group_name, message_id)
                    continue
                try:
                    await process_analysis_job(store, str(job_id))
                except AnalysisJobNotFound:
                    logger.warning("analysis job missing: %s", job_id)
                finally:
                    await store.redis.xack(stream, group_name, message_id)


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from frontend.backend.main import _startup_db

    await _startup_db()
    await asyncio.to_thread(initialize_pool)
    redis = create_redis_client(settings.redis_url)
    await redis.ping()
    store = AnalysisJobStore(
        redis,
        stream_name=settings.analysis_queue_name,
        job_ttl_seconds=settings.analysis_job_ttl_seconds,
    )
    stop_event = asyncio.Event()
    recovery = asyncio.create_task(sandbox_pool_recovery_loop(stop_event))
    heartbeat = asyncio.create_task(worker_heartbeat_loop(redis, worker_id(), stop_event))
    try:
        await consume_analysis_jobs(
            store,
            group_name=settings.analysis_consumer_group,
            block_ms=settings.analysis_worker_poll_timeout_seconds * 1000,
        )
    finally:
        stop_event.set()
        await asyncio.gather(recovery, heartbeat, return_exceptions=True)
        shutdown_pool()
        await redis.aclose()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
