"""Phase 2B cache smoke: Redis generation locks and PostgreSQL generated_test_sets."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TARGET_SERVICES = ("redis", "postgres")


def _asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def _running_compose_services() -> set[str]:
    result = subprocess.run(
        ["docker", "compose", "ps", "--services", "--filter", "status=running"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _start_compose_services(services: list[str]) -> None:
    if not services:
        return
    subprocess.run(
        ["docker", "compose", "up", "-d", *services],
        cwd=ROOT,
        check=True,
    )


def _stop_compose_services(services: list[str]) -> None:
    if not services:
        return
    subprocess.run(
        ["docker", "compose", "stop", *services],
        cwd=ROOT,
        check=False,
    )


async def _wait_redis(redis_url: str, timeout_s: float = 20.0) -> None:
    import redis.asyncio as redis

    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        client = redis.from_url(redis_url, decode_responses=True)
        try:
            if await client.ping():
                await client.aclose()
                return
        except Exception as exc:
            last_error = exc
        finally:
            try:
                await client.aclose()
            except Exception:
                pass
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Redis not reachable at {redis_url}: {last_error}")


async def _wait_postgres(database_url: str, timeout_s: float = 20.0) -> None:
    import asyncpg

    dsn = _asyncpg_dsn(database_url)
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = await asyncpg.connect(dsn=dsn)
            try:
                await conn.fetchval("SELECT 1")
                return
            finally:
                await conn.close()
        except Exception as exc:
            last_error = exc
        await asyncio.sleep(0.5)
    raise RuntimeError(f"PostgreSQL not reachable at {dsn}: {last_error}")


async def _redis_lock_smoke(redis_url: str) -> None:
    import redis.asyncio as redis

    from backend.testing.cache import (
        GenerationLockUnavailable,
        acquire_generation_lock,
        generation_lock,
        release_generation_lock,
    )

    client = redis.from_url(redis_url, decode_responses=True)
    try:
        assignment_id = f"qa-phase2b-{uuid.uuid4()}"
        cache_key = "a" * 64
        lock_key = f"testing:generation_lock:{assignment_id}:{cache_key}"

        token = await acquire_generation_lock(
            client, assignment_id, cache_key, ttl_seconds=30, max_attempts=1
        )
        try:
            await acquire_generation_lock(
                client, assignment_id, cache_key, ttl_seconds=30, max_attempts=1
            )
            raise AssertionError("expected GenerationLockUnavailable for contended lock")
        except GenerationLockUnavailable:
            pass

        wrong_token = "not-the-owner"
        await release_generation_lock(client, assignment_id, cache_key, wrong_token)
        still_held = await client.get(lock_key)
        if still_held != token:
            raise AssertionError("non-owner release must not drop the generation lock")

        await release_generation_lock(client, assignment_id, cache_key, token)
        if await client.get(lock_key) is not None:
            raise AssertionError("owner release must delete the generation lock")

        async with generation_lock(client, assignment_id, cache_key, ttl_seconds=30):
            inner_token = await client.get(lock_key)
            if inner_token is None:
                raise AssertionError("generation_lock context must hold the lock")
    finally:
        await client.aclose()


async def _postgres_store_smoke(database_url: str, run_tag: str) -> None:
    import asyncpg

    from backend.testing.contracts import FormalTestCase, GeneratedTestSet
    from backend.testing.store import PostgresGeneratedTestSetStore
    from frontend.backend import main

    dsn = _asyncpg_dsn(database_url)
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
    teacher_id: str | None = None
    course_id: str | None = None
    assignment_id: str | None = None

    try:
        await main._ensure_db_schema(pool)

        table_exists = await pool.fetchval(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'generated_test_sets'
            LIMIT 1
            """
        )
        if table_exists != 1:
            raise AssertionError("public.generated_test_sets table is missing after schema ensure")

        teacher_id = str(uuid.uuid4())
        course_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        email = f"{run_tag}@agentgrade.local"

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.teachers (id, first_name, last_name, email, password_hash)
                VALUES ($1::uuid, $2, $3, $4, $5)
                """,
                teacher_id,
                "QA",
                "Phase2B",
                email,
                "qa-smoke-hash",
            )
            await conn.execute(
                """
                INSERT INTO public.courses (id, name, code, created_by)
                VALUES ($1::uuid, $2, $3, $4::uuid)
                """,
                course_id,
                f"{run_tag}-course",
                f"{run_tag}-code",
                teacher_id,
            )
            await conn.execute(
                """
                INSERT INTO public.assignments (id, course_id, name, description, created_by)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5::uuid)
                """,
                assignment_id,
                course_id,
                f"{run_tag}-assignment",
                "QA smoke assignment",
                teacher_id,
            )

        store = PostgresGeneratedTestSetStore(pool)
        cache_key = "b" * 64
        base_set = GeneratedTestSet(
            id=str(uuid.uuid4()),
            assignment_id=assignment_id,
            cache_key=cache_key,
            version=1,
            difficulty="medium",
            cases=(
                FormalTestCase(
                    id="case-1",
                    name="smoke",
                    source="auto_generated",
                    oracle="llm_verified",
                ),
            ),
            provider="ollama",
            model="qwen2.5:7b",
            schema_version="test-set-v1",
            prompt_version="test-generator-v1",
        )

        first, second = await asyncio.gather(
            store.insert_verified_set(base_set),
            store.insert_verified_set(
                base_set.model_copy(update={"id": str(uuid.uuid4())})
            ),
        )
        if first.id != second.id or first.version != second.version:
            raise AssertionError(
                f"concurrent insert race must return same winner: "
                f"{first.id}/{first.version} vs {second.id}/{second.version}"
            )

        row_count = await pool.fetchval(
            """
            SELECT COUNT(*)::int
            FROM public.generated_test_sets
            WHERE assignment_id = $1::uuid AND cache_key = $2
            """,
            assignment_id,
            cache_key,
        )
        if row_count != 1:
            raise AssertionError(f"expected exactly one generated_test_sets row, got {row_count}")
    finally:
        if pool is not None:
            if assignment_id is not None:
                await pool.execute(
                    "DELETE FROM public.generated_test_sets WHERE assignment_id = $1::uuid",
                    assignment_id,
                )
                await pool.execute(
                    "DELETE FROM public.assignments WHERE id = $1::uuid",
                    assignment_id,
                )
            if course_id is not None:
                await pool.execute(
                    "DELETE FROM public.courses WHERE id = $1::uuid",
                    course_id,
                )
            if teacher_id is not None:
                await pool.execute(
                    "DELETE FROM public.teachers WHERE id = $1::uuid",
                    teacher_id,
                )
            await pool.close()


async def _run_smoke(*, manage_services: bool) -> int:
    from backend.core.config import settings

    started_by_script: list[str] = []
    if manage_services:
        already_running = _running_compose_services()
        to_start = [svc for svc in TARGET_SERVICES if svc not in already_running]
        if to_start:
            _start_compose_services(to_start)
            started_by_script = to_start
            await asyncio.sleep(2.0)

    try:
        await _wait_redis(settings.redis_url)
        await _wait_postgres(settings.database_url)
        await _redis_lock_smoke(settings.redis_url)
        run_tag = f"qa-phase2b-{uuid.uuid4()}"
        await _postgres_store_smoke(settings.database_url, run_tag)
        print("PASS", flush=True)
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", flush=True)
        return 1
    finally:
        if started_by_script:
            _stop_compose_services(started_by_script)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2B cache smoke checks")
    parser.add_argument(
        "--manage-services",
        action="store_true",
        help="Start docker compose redis/postgres if not already running",
    )
    args = parser.parse_args()
    return asyncio.run(_run_smoke(manage_services=args.manage_services))


if __name__ == "__main__":
    raise SystemExit(main())
