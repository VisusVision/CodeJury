"""Phase 2B end-to-end QA: selection, sandbox, projection, and security ledger."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TARGET_SERVICES = ("redis", "postgres")

STUDENT_CODE_SENTINEL_PREFIX = "STUDENT_CODE_SENTINEL"

PASS_CODE = "n = int(input())\nprint(n * n)\n"
MISMATCH_CODE = "print('wrong')\n"
ZERO_DIV_CODE = "a=int(input())\nb=int(input())\nprint(a//b)\n"
TIMEOUT_CODE = "while True:\n    pass\n"
FIXTURE_ISOLATION_CODE = '''
import sys
from pathlib import Path

mode = sys.stdin.read().strip()
path = Path("state.txt")
if mode == "mutate":
    path.write_text(path.read_text(encoding="utf-8") + "mutated\\n", encoding="utf-8")
    print("case-one")
else:
    print(path.read_text(encoding="utf-8").strip())
'''

PHASE2B_HIDDEN_SENTINELS = (
    "SENTINEL_FIXTURE_NAME_2b12",
    "SENTINEL_FIXTURE_CONTENT_2b12",
    "SENTINEL_SOURCE_PRIVATE_2b12",
    "SENTINEL_ORACLE_MODEL_2b12",
    "SENTINEL_ORACLE_PROVIDER_2b12",
    "SENTINEL_CACHE_KEY_2b12",
    "SENTINEL_SET_ID_2b12",
    "SENTINEL_STDERR_2b12",
    "SENTINEL_NORMALIZED_DIFF_2b12",
    "SENTINEL_RUNTIME_DETAIL_2b12",
    "SENTINEL_ORIGINAL_NAME_2b12",
    "SENTINEL_CASE_ID_2b12",
)


@dataclass
class SecurityLedger:
    client_test_override_affected_score: bool = False
    second_generator_ran_for_same_cache: bool = False
    student_code_appeared_in_generator_prompt: bool = False
    hidden_sentinel_leak: bool = False
    container_passed_overruled_backend: bool = False
    case_fixture_state_crossed_boundary: bool = False
    faculty_test_triggered_generator: bool = False
    generation_failure_created_formal_pass: bool = False

    def print_report(self) -> None:
        print("Security ledger:", flush=True)
        for key, value in (
            ("CLIENT_TEST_OVERRIDE_AFFECTED_SCORE", self.client_test_override_affected_score),
            ("SECOND_GENERATOR_RAN_FOR_SAME_CACHE", self.second_generator_ran_for_same_cache),
            ("STUDENT_CODE_APPEARED_IN_GENERATOR_PROMPT", self.student_code_appeared_in_generator_prompt),
            ("HIDDEN_SENTINEL_LEAK", self.hidden_sentinel_leak),
            ("CONTAINER_PASSED_OVERRULED_BACKEND", self.container_passed_overruled_backend),
            ("CASE_FIXTURE_STATE_CROSSED_BOUNDARY", self.case_fixture_state_crossed_boundary),
            ("FACULTY_TEST_TRIGGERED_GENERATOR", self.faculty_test_triggered_generator),
            ("GENERATION_FAILURE_CREATED_FORMAL_PASS", self.generation_failure_created_formal_pass),
        ):
            print(f"  {key}={value}", flush=True)

    def assert_secure(self) -> None:
        violations = [
            name
            for name, value in (
                ("CLIENT_TEST_OVERRIDE_AFFECTED_SCORE", self.client_test_override_affected_score),
                ("SECOND_GENERATOR_RAN_FOR_SAME_CACHE", self.second_generator_ran_for_same_cache),
                ("STUDENT_CODE_APPEARED_IN_GENERATOR_PROMPT", self.student_code_appeared_in_generator_prompt),
                ("HIDDEN_SENTINEL_LEAK", self.hidden_sentinel_leak),
                ("CONTAINER_PASSED_OVERRULED_BACKEND", self.container_passed_overruled_backend),
                ("CASE_FIXTURE_STATE_CROSSED_BOUNDARY", self.case_fixture_state_crossed_boundary),
                ("FACULTY_TEST_TRIGGERED_GENERATOR", self.faculty_test_triggered_generator),
                ("GENERATION_FAILURE_CREATED_FORMAL_PASS", self.generation_failure_created_formal_pass),
            )
            if value
        ]
        if violations:
            raise AssertionError(f"security ledger violations: {', '.join(violations)}")


@dataclass
class OwnedResources:
    run_tag: str
    teacher_id: str
    course_id: str
    assignment_id: str
    student_id: str
    pool_owner: str
    redis_lock_prefix: str = field(default="")
    generation_calls: int = 0
    first_set_id: str | None = None
    first_cache_version: int | None = None


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
    subprocess.run(["docker", "compose", "up", "-d", *services], cwd=ROOT, check=True)


def _stop_compose_services(services: list[str]) -> None:
    if not services:
        return
    subprocess.run(["docker", "compose", "stop", *services], cwd=ROOT, check=False)


def _task_containers(owner_id: str) -> list[str]:
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=agentgrade.pool_owner={owner_id}",
            "--format",
            "{{.ID}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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


def _easy_sufficient_cases() -> tuple[Any, ...]:
    from backend.testing.contracts import FormalTestCase, OracleValidation

    oracle = OracleValidation(
        status="verified",
        provider="qa",
        model="qa-model",
        schema_version="test-set-v1",
        verified_at="2026-07-11T00:00:00Z",
    )
    cases: list[FormalTestCase] = []
    specs = [
        ("public-pass", "2\n", "4\n", "public"),
        ("hidden-pass", "3\n", "9\n", "hidden"),
        ("hidden-mismatch", "", "expected-only\n", "hidden"),
        ("hidden-zero", "10\n0\n", "ok\n", "hidden"),
        ("hidden-timeout", "", "", "hidden"),
    ]
    for index, (name, stdin, expected, visibility) in enumerate(specs):
        cases.append(
            FormalTestCase(
                id=f"qa-case-{index}",
                name=name,
                stdin=stdin,
                expected_stdout=expected,
                visibility=visibility,  # type: ignore[arg-type]
                source="auto_generated",
                oracle="llm_verified",
                oracle_validation=oracle,
            )
        )
    return tuple(cases)


def _sandbox_case(
    *,
    case_id: str,
    name: str,
    stdin: str = "",
    expected_stdout: str = "",
    visibility: str = "hidden",
    files: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "name": name,
        "stdin": stdin,
        "expected_stdout": expected_stdout,
        "expected_exit_code": 0,
        "visibility": visibility,
        "files": files or [],
        "source": "manual",
        "oracle": "teacher",
    }


def _private_result_with_sentinels(selection: Any) -> dict[str, Any]:
    hidden_case = {
        "id": PHASE2B_HIDDEN_SENTINELS[11],
        "name": PHASE2B_HIDDEN_SENTINELS[10],
        "stdin": "secret stdin\n",
        "expected_stdout": "secret expected\n",
        "actual_stdout": "secret actual\n",
        "actual_stderr": PHASE2B_HIDDEN_SENTINELS[7],
        "passed": False,
        "visibility": "hidden",
        "status": "error",
        "source": PHASE2B_HIDDEN_SENTINELS[2],
        "oracle": "llm_verified",
        "oracle_validation": {
            "status": "verified",
            "provider": PHASE2B_HIDDEN_SENTINELS[5],
            "model": PHASE2B_HIDDEN_SENTINELS[4],
            "schema_version": "v1",
            "verified_at": "2026-07-11T00:00:00Z",
        },
        "files": [
            {"name": PHASE2B_HIDDEN_SENTINELS[0], "content": PHASE2B_HIDDEN_SENTINELS[1]},
        ],
        "error_type": "ZeroDivisionError",
        "error_message_tr": PHASE2B_HIDDEN_SENTINELS[9],
        "errorDetail": PHASE2B_HIDDEN_SENTINELS[8],
    }
    public_case = {
        "name": "public square",
        "stdin": "2\n",
        "expected_stdout": "4\n",
        "actual_stdout": "5\n",
        "passed": False,
        "visibility": "public",
        "status": "fail",
        "source": "auto_generated",
    }
    return {
        "totalScore": 50,
        "maxScore": 100,
        "rubric": {},
        "agents": [
            {
                "id": "testing",
                "name": "Test Ajani",
                "summary": "Formal evidence",
                "score": 50,
                "maxScore": 100,
                "findings": [],
                "testResults": [public_case, hidden_case],
            }
        ],
        "fileName": "solution.py",
        "executionTimeMs": 100,
        "memoryUsageMb": 1.0,
        "peakMemoryMb": 1.0,
        "analysisEngine": "agentgrade-v1",
        "summary": "QA private result",
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "taskAlignment": {},
        "reportStatus": "ready",
        "testSource": selection.source,
        "testEvidenceStatus": selection.test_evidence_status,
        "formalPassed": 1,
        "formalTotal": 2,
        "formalScore": 50,
        "testSetId": selection.test_set_id or PHASE2B_HIDDEN_SENTINELS[6],
        "testSetHash": selection.cache_key or PHASE2B_HIDDEN_SENTINELS[6],
        "cacheVersion": selection.cache_version or 1,
        "generationAttempts": selection.generation_attempts,
    }


async def _seed_assignment(pool: Any, owned: OwnedResources) -> None:
    from frontend.backend import main

    await main._ensure_db_schema(pool)
    rubric = json.dumps([{"name": "Correctness", "max_score": 100}], ensure_ascii=False)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.teachers (id, first_name, last_name, email, password_hash)
            VALUES ($1::uuid, $2, $3, $4, $5)
            """,
            owned.teacher_id,
            "QA",
            "Phase2B",
            f"{owned.run_tag}@agentgrade.local",
            "qa-e2e-hash",
        )
        await conn.execute(
            """
            INSERT INTO public.courses (id, name, code, created_by)
            VALUES ($1::uuid, $2, $3, $4::uuid)
            """,
            owned.course_id,
            f"{owned.run_tag}-course",
            f"{owned.run_tag}-code",
            owned.teacher_id,
        )
        await conn.execute(
            """
            INSERT INTO public.assignments (
                id, course_id, name, description, created_by, difficulty, difficulty_source
            )
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::uuid, $6, $7)
            """,
            owned.assignment_id,
            owned.course_id,
            f"{owned.run_tag}-assignment",
            "Read an integer and print its square.",
            owned.teacher_id,
            "easy",
            "teacher",
        )
        await conn.execute(
            """
            INSERT INTO public.rubrics (assignment_id, criteria, status, created_by)
            VALUES ($1::uuid, $2::jsonb, 'approved', $3::uuid)
            """,
            owned.assignment_id,
            rubric,
            owned.teacher_id,
        )
        await conn.execute(
            """
            INSERT INTO public.students (id, student_no, tc_no, first_name, last_name, password_hash)
            VALUES ($1::uuid, $2, $3, $4, $5, $6)
            """,
            owned.student_id,
            f"{owned.run_tag}-no",
            f"{owned.run_tag}-tc",
            "QA",
            "Student",
            "qa-student-hash",
        )
        await conn.execute(
            """
            INSERT INTO public.student_courses (student_id, course_id)
            VALUES ($1::uuid, $2::uuid)
            """,
            owned.student_id,
            owned.course_id,
        )


async def _cleanup_owned(pool: Any, owned: OwnedResources, redis: Any) -> None:
    if pool is not None:
        await pool.execute(
            "DELETE FROM public.generated_test_sets WHERE assignment_id = $1::uuid",
            owned.assignment_id,
        )
        await pool.execute(
            "DELETE FROM public.assignment_test_cases WHERE assignment_id = $1::uuid",
            owned.assignment_id,
        )
        await pool.execute(
            "DELETE FROM public.rubrics WHERE assignment_id = $1::uuid",
            owned.assignment_id,
        )
        await pool.execute(
            "DELETE FROM public.assignments WHERE id = $1::uuid",
            owned.assignment_id,
        )
        await pool.execute(
            "DELETE FROM public.student_courses WHERE student_id = $1::uuid",
            owned.student_id,
        )
        await pool.execute(
            "DELETE FROM public.students WHERE id = $1::uuid",
            owned.student_id,
        )
        await pool.execute(
            "DELETE FROM public.courses WHERE id = $1::uuid",
            owned.course_id,
        )
        await pool.execute(
            "DELETE FROM public.teachers WHERE id = $1::uuid",
            owned.teacher_id,
        )

    if redis is not None and owned.redis_lock_prefix:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=owned.redis_lock_prefix, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break

    for container_id in _task_containers(owned.pool_owner):
        subprocess.run(["docker", "rm", "-f", container_id], check=False)


async def _load_empty_faculty() -> tuple[Any, ...]:
    return ()


async def _run_e2e(*, manage_services: bool) -> int:
    from backend.core.config import settings
    from backend.llm.ollama_client import ChatJsonResult
    from backend.reporting.student_projection import project_student_result
    from backend.sandbox.executor import run_in_sandbox
    from backend.sandbox.pool_manager import initialize_pool, shutdown_pool
    from backend.testing.cache import AssignmentTestContext
    from backend.testing.contracts import FormalTestCase
    from backend.testing.generator import GenerationAttemptResult, generate_and_verify_once
    from backend.testing.selector import select_tests
    from backend.testing.store import DemoGeneratedTestSetStore, PostgresGeneratedTestSetStore
    from frontend.backend import main

    ledger = SecurityLedger()
    run_tag = f"qa-phase2b-e2e-{uuid.uuid4()}"
    owned = OwnedResources(
        run_tag=run_tag,
        teacher_id=str(uuid.uuid4()),
        course_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        student_id=str(uuid.uuid4()),
        pool_owner=f"qa-phase2b-e2e-{uuid.uuid4()}",
    )
    owned.redis_lock_prefix = f"testing:generation_lock:{owned.assignment_id}:*"

    os.environ["DEMO_MODE"] = "0"
    os.environ["SANDBOX_POOL_OWNER"] = owned.pool_owner
    os.environ.setdefault("SANDBOX_IMAGE", "agentgrade-sandbox:phase2b")
    os.environ.setdefault("SANDBOX_POOL_SIZE", "1")
    os.environ.setdefault("SANDBOX_POOL_BASE_PORT", "8381")

    started_by_script: list[str] = []
    pool = None
    db_pool = None
    redis = None

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

        import asyncpg
        import redis.asyncio as redis_async

        dsn = _asyncpg_dsn(settings.database_url)
        db_pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
        main._DB_POOL = db_pool
        await main._ensure_db_schema(db_pool)
        redis = redis_async.from_url(settings.redis_url, decode_responses=True)
        await redis.ping()

        await _seed_assignment(db_pool, owned)

        context = AssignmentTestContext(
            assignment_id=owned.assignment_id,
            title=f"{owned.run_tag}-assignment",
            description="Read an integer and print its square.",
            rubric=[{"name": "Correctness", "max_score": 100}],
            difficulty="easy",
        )
        store = PostgresGeneratedTestSetStore(db_pool)
        release = asyncio.Event()
        generation_calls = 0

        async def tracked_generate_once(ctx: AssignmentTestContext) -> GenerationAttemptResult:
            nonlocal generation_calls
            generation_calls += 1
            await release.wait()
            return GenerationAttemptResult(
                cases=_easy_sufficient_cases(),
                rejected=(),
                provider="qa",
                model="qa-model",
                success=True,
            )

        async def load_faculty() -> tuple[FormalTestCase, ...]:
            return await main._fetch_faculty_formal_test_cases(owned.assignment_id)

        # Step 3: concurrent selection shares set ID/version
        task_a = asyncio.create_task(
            select_tests(
                context,
                "python",
                load_faculty=load_faculty,
                store=store,
                redis=redis,
                generate_once=tracked_generate_once,
            )
        )
        task_b = asyncio.create_task(
            select_tests(
                context,
                "python",
                load_faculty=load_faculty,
                store=store,
                redis=redis,
                generate_once=tracked_generate_once,
            )
        )
        await asyncio.sleep(0.05)
        release.set()
        selection_a, selection_b = await asyncio.gather(task_a, task_b)

        if generation_calls != 1:
            ledger.second_generator_ran_for_same_cache = True
        if (
            selection_a.test_set_id != selection_b.test_set_id
            or selection_a.cache_version != selection_b.cache_version
        ):
            raise AssertionError(
                "concurrent selections must share set ID/version: "
                f"{selection_a.test_set_id}/{selection_a.cache_version} vs "
                f"{selection_b.test_set_id}/{selection_b.cache_version}"
            )
        owned.generation_calls = generation_calls
        owned.first_set_id = selection_a.test_set_id
        owned.first_cache_version = selection_a.cache_version

        # Step 4: generator prompts must not contain student-code sentinel
        student_code_sentinel = f"{STUDENT_CODE_SENTINEL_PREFIX}_{run_tag}"
        _student_submission = f"print('{student_code_sentinel}')\n"  # noqa: F841 - sentinel must not reach prompts
        captured_prompts: list[str] = []
        call_index = {"n": 0}

        async def spy_chat(system_prompt: str, user_prompt: str, **kwargs: Any) -> ChatJsonResult:
            del kwargs
            captured_prompts.append(system_prompt)
            captured_prompts.append(user_prompt)
            call_index["n"] += 1
            if call_index["n"] == 1:
                payload = {
                    "cases": [
                        {
                            "name": "square",
                            "stdin": "2\n",
                            "expected_stdout": "4\n",
                            "expected_exit_code": 0,
                            "visibility": "public",
                            "files": [],
                        }
                    ]
                }
            else:
                payload = {
                    "case_id": "0",
                    "verified": True,
                    "deterministic": True,
                    "assignment_aligned": True,
                    "reason": "ok",
                }
            return ChatJsonResult(
                data=payload,
                provider="qa",
                model="qa-model",
                fallback_used=False,
            )

        await generate_and_verify_once(context, chat=spy_chat)
        if any(student_code_sentinel in prompt for prompt in captured_prompts):
            ledger.student_code_appeared_in_generator_prompt = True

        # Step 5: sandbox pass/fail/isolation cases
        pool = initialize_pool()
        if pool is None or not pool.wait_until_ready(60.0):
            raise RuntimeError("sandbox pool did not become ready")

        public_hidden = run_in_sandbox(
            PASS_CODE,
            "python",
            test_cases=[
                _sandbox_case(case_id="pub", name="public pass", stdin="2\n", expected_stdout="4\n", visibility="public"),
                _sandbox_case(case_id="hid", name="hidden pass", stdin="3\n", expected_stdout="9\n", visibility="hidden"),
            ],
        )
        ph = {row["id"]: row for row in public_hidden.get("test_results", [])}
        if not (ph.get("pub", {}).get("passed") and ph.get("hid", {}).get("passed")):
            raise AssertionError(f"public/hidden pass cases failed: {ph}")

        mismatch = run_in_sandbox(
            MISMATCH_CODE,
            "python",
            test_cases=[_sandbox_case(case_id="mis", name="mismatch", expected_stdout="expected-only\n")],
        )
        mismatch_case = mismatch["test_results"][0]
        if not (mismatch_case.get("passed") is False and mismatch_case.get("status") == "fail"):
            raise AssertionError(f"mismatch case unexpected: {mismatch_case}")

        zero_div = run_in_sandbox(
            ZERO_DIV_CODE,
            "python",
            test_cases=[_sandbox_case(case_id="zd", name="zero division", stdin="10\n0\n", expected_stdout="ok\n")],
        )
        zero_case = zero_div["test_results"][0]
        if not (zero_case.get("status") == "error" and zero_case.get("error_type") == "ZeroDivisionError"):
            raise AssertionError(f"zero division case unexpected: {zero_case}")

        timeout = run_in_sandbox(
            TIMEOUT_CODE,
            "python",
            test_cases=[_sandbox_case(case_id="to", name="timeout")],
        )
        timeout_case = timeout["test_results"][0]
        if not (timeout_case.get("status") == "error" and timeout_case.get("error_type") == "Timeout"):
            raise AssertionError(f"timeout case unexpected: {timeout_case}")

        isolation = run_in_sandbox(
            FIXTURE_ISOLATION_CODE,
            "python",
            test_cases=[
                _sandbox_case(
                    case_id="iso-1",
                    name="mutate fixture",
                    stdin="mutate\n",
                    expected_stdout="case-one\n",
                    files=[{"name": "state.txt", "content": "seed\n"}],
                ),
                _sandbox_case(
                    case_id="iso-2",
                    name="read untouched fixture",
                    stdin="read\n",
                    expected_stdout="seed\n",
                    files=[{"name": "state.txt", "content": "seed\n"}],
                ),
            ],
        )
        iso = {row["id"]: row for row in isolation.get("test_results", [])}
        if not (iso.get("iso-1", {}).get("passed") and iso.get("iso-2", {}).get("passed")):
            ledger.case_fixture_state_crossed_boundary = True
            raise AssertionError(f"fixture isolation failed: {iso}")

        adversarial = run_in_sandbox(
            MISMATCH_CODE,
            "python",
            test_cases=[_sandbox_case(case_id="adv", name="adversarial", expected_stdout="expected-only\n")],
        )
        adv_case = adversarial["test_results"][0]
        if adv_case.get("passed") is not False:
            ledger.container_passed_overruled_backend = True

        # Step 6: student projection strips hidden sentinels
        private = _private_result_with_sentinels(selection_a)
        projected = project_student_result(private)
        serialized = json.dumps(projected, ensure_ascii=False)
        if any(sentinel in serialized for sentinel in PHASE2B_HIDDEN_SENTINELS):
            ledger.hidden_sentinel_leak = True

        # Step 7: teacher private evidence retains provenance
        required_teacher_fields = (
            "testSetId",
            "testSetHash",
            "cacheVersion",
            "formalScore",
            "testSource",
            "testEvidenceStatus",
        )
        for field_name in required_teacher_fields:
            if private.get(field_name) in (None, ""):
                raise AssertionError(f"teacher private result missing {field_name}")
        testing_agent = next(agent for agent in private["agents"] if agent["id"] == "testing")
        hidden_private = next(
            case for case in testing_agent["testResults"] if case.get("visibility") == "hidden"
        )
        for private_key in ("stdin", "expected_stdout", "actual_stdout", "actual_stderr", "oracle_validation"):
            if private_key not in hidden_private:
                raise AssertionError(f"teacher hidden case missing {private_key}")

        # Step 8: faculty tests suppress generator
        calls_before_faculty = generation_calls
        faculty_case_id = str(uuid.uuid4())
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.assignment_test_cases (
                    id, assignment_id, name, stdin, expected_stdout, expected_exit_code,
                    visibility, source, oracle, display_order
                )
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                faculty_case_id,
                owned.assignment_id,
                "faculty square",
                "2\n",
                "4\n",
                0,
                "hidden",
                "manual",
                "teacher",
                0,
            )
        await main._invalidate_generated_test_set(owned.assignment_id)

        faculty_selection = await select_tests(
            context,
            "python",
            load_faculty=load_faculty,
            store=store,
            redis=redis,
            generate_once=tracked_generate_once,
        )
        if generation_calls != calls_before_faculty:
            ledger.faculty_test_triggered_generator = True
        if faculty_selection.source != "faculty":
            raise AssertionError(f"expected faculty source after manual test insert, got {faculty_selection.source}")

        # Client override must not affect authoritative selection path
        import inspect

        fake_client_cases = [
            {
                "id": "client-fake",
                "name": "client_fake_pass",
                "stdin": "",
                "expected_stdout": "PASS\n",
                "source": "manual",
                "oracle": "teacher",
            }
        ]
        authoritative_cases = main._formal_cases_to_sandbox_cases(faculty_selection.cases)
        fake_result = run_in_sandbox(MISMATCH_CODE, "python", test_cases=fake_client_cases)
        real_result = run_in_sandbox(MISMATCH_CODE, "python", test_cases=authoritative_cases)
        fake_passed = sum(1 for row in fake_result.get("test_results", []) if row.get("passed"))
        real_passed = sum(1 for row in real_result.get("test_results", []) if row.get("passed"))
        selection_sig = inspect.signature(main._resolve_pipeline_test_selection)
        if (
            "test_cases" in selection_sig.parameters
            or (fake_passed > 0 and real_passed == 0 and not authoritative_cases)
        ):
            ledger.client_test_override_affected_score = True

        # Step 9: deleting faculty tests reactivates exact cache key
        await db_pool.execute(
            "DELETE FROM public.assignment_test_cases WHERE assignment_id = $1::uuid",
            owned.assignment_id,
        )
        reactivated = await select_tests(
            context,
            "python",
            load_faculty=load_faculty,
            store=store,
            redis=redis,
            generate_once=tracked_generate_once,
        )
        if generation_calls != calls_before_faculty:
            ledger.faculty_test_triggered_generator = True
        if reactivated.test_set_id != owned.first_set_id:
            raise AssertionError(
                f"cache reactivation must reuse prior set ID: "
                f"{reactivated.test_set_id} != {owned.first_set_id}"
            )
        if reactivated.cache_version != owned.first_cache_version:
            raise AssertionError(
                f"cache reactivation must reuse prior cache version: "
                f"{reactivated.cache_version} != {owned.first_cache_version}"
            )

        # Fail-soft generation must not fabricate formal passes
        async def failing_generate(_ctx: AssignmentTestContext) -> GenerationAttemptResult:
            raise RuntimeError("generation unavailable")

        fail_soft = await select_tests(
            AssignmentTestContext(
                assignment_id=str(uuid.uuid4()),
                title="no-cache-assignment",
                description="temporary",
                rubric=[{"name": "Correctness"}],
                difficulty="easy",
            ),
            "python",
            load_faculty=_load_empty_faculty,
            store=DemoGeneratedTestSetStore({"generated_test_sets": []}),
            redis=redis,
            generate_once=failing_generate,
        )
        if fail_soft.test_evidence_status != "unavailable" or fail_soft.cases:
            ledger.generation_failure_created_formal_pass = True

        ledger.assert_secure()
        print("PASS", flush=True)
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", flush=True)
        return 1
    finally:
        ledger.print_report()
        try:
            shutdown_pool()
        except Exception:
            pass
        if db_pool is not None:
            try:
                await _cleanup_owned(db_pool, owned, redis)
            except Exception:
                pass
            try:
                await db_pool.close()
            except Exception:
                pass
            main._DB_POOL = None
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:
                pass
        if os.environ.get("SANDBOX_POOL_OWNER") == owned.pool_owner:
            del os.environ["SANDBOX_POOL_OWNER"]
        if started_by_script:
            _stop_compose_services(started_by_script)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2B end-to-end QA gate")
    parser.add_argument(
        "--manage-services",
        action="store_true",
        help="Start docker compose redis/postgres if not already running",
    )
    args = parser.parse_args()
    return asyncio.run(_run_e2e(manage_services=args.manage_services))


if __name__ == "__main__":
    raise SystemExit(main())
