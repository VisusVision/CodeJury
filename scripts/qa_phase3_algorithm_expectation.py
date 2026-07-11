"""Phase 3 algorithm expectation QA: Redis/PostgreSQL cache, concurrency, privacy."""

from __future__ import annotations

import argparse
import asyncio
import json
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
STUDENT_CODE_SENTINEL_PREFIX = "STUDENT_CODE_SENTINEL_PHASE3"

PHASE3_PROVENANCE_SENTINELS = (
    "SENTINEL_EXPECTATION_ID_PHASE3",
    "SENTINEL_CACHE_KEY_PHASE3_UNIQUE",
    "SENTINEL_EXTRACTOR_PROVIDER_PHASE3",
    "SENTINEL_VERIFIER_REASON_PHASE3",
)


@dataclass
class AdversarialLedger:
    second_expectation_generator_ran: bool = False
    student_code_appeared_in_expectation_prompt: bool = False
    different_students_received_different_expectation: bool = False
    unknown_complexity_received_gap_penalty: bool = False
    llm_overruled_ast_lower_bound: bool = False
    llm_overruled_score_cap: bool = False
    student_expectation_provenance_leak: bool = False
    algorithm_score_changed_master_rubric: bool = False
    teacher_expectation_mutation_route_exists: bool = False

    def print_report(self) -> None:
        print("Adversarial ledger:", flush=True)
        for key, value in (
            ("SECOND_EXPECTATION_GENERATOR_RAN", self.second_expectation_generator_ran),
            ("STUDENT_CODE_APPEARED_IN_EXPECTATION_PROMPT", self.student_code_appeared_in_expectation_prompt),
            ("DIFFERENT_STUDENTS_RECEIVED_DIFFERENT_EXPECTATION", self.different_students_received_different_expectation),
            ("UNKNOWN_COMPLEXITY_RECEIVED_GAP_PENALTY", self.unknown_complexity_received_gap_penalty),
            ("LLM_OVERRULED_AST_LOWER_BOUND", self.llm_overruled_ast_lower_bound),
            ("LLM_OVERRULED_SCORE_CAP", self.llm_overruled_score_cap),
            ("STUDENT_EXPECTATION_PROVENANCE_LEAK", self.student_expectation_provenance_leak),
            ("ALGORITHM_SCORE_CHANGED_MASTER_RUBRIC", self.algorithm_score_changed_master_rubric),
            ("TEACHER_EXPECTATION_MUTATION_ROUTE_EXISTS", self.teacher_expectation_mutation_route_exists),
        ):
            print(f"  {key}={value}", flush=True)

    def assert_secure(self) -> None:
        violations = [
            name
            for name, value in (
                ("SECOND_EXPECTATION_GENERATOR_RAN", self.second_expectation_generator_ran),
                ("STUDENT_CODE_APPEARED_IN_EXPECTATION_PROMPT", self.student_code_appeared_in_expectation_prompt),
                ("DIFFERENT_STUDENTS_RECEIVED_DIFFERENT_EXPECTATION", self.different_students_received_different_expectation),
                ("UNKNOWN_COMPLEXITY_RECEIVED_GAP_PENALTY", self.unknown_complexity_received_gap_penalty),
                ("LLM_OVERRULED_AST_LOWER_BOUND", self.llm_overruled_ast_lower_bound),
                ("LLM_OVERRULED_SCORE_CAP", self.llm_overruled_score_cap),
                ("STUDENT_EXPECTATION_PROVENANCE_LEAK", self.student_expectation_provenance_leak),
                ("ALGORITHM_SCORE_CHANGED_MASTER_RUBRIC", self.algorithm_score_changed_master_rubric),
                ("TEACHER_EXPECTATION_MUTATION_ROUTE_EXISTS", self.teacher_expectation_mutation_route_exists),
            )
            if value
        ]
        if violations:
            raise AssertionError(f"adversarial ledger violations: {', '.join(violations)}")


@dataclass
class OwnedResources:
    run_tag: str
    teacher_id: str
    course_id: str
    assignment_id: str
    student_a_id: str
    student_b_id: str
    redis_lock_prefix: str = field(default="")
    generation_calls: int = 0
    first_expectation_id: str | None = None
    first_expectation_version: int | None = None
    first_cache_key: str | None = None


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
            "Phase3",
            f"{owned.run_tag}@agentgrade.local",
            "qa-phase3-hash",
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
            "Implement binary search on a sorted array. Required complexity O(log n).",
            owned.teacher_id,
            "medium",
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
        for student_id, suffix in ((owned.student_a_id, "a"), (owned.student_b_id, "b")):
            await conn.execute(
                """
                INSERT INTO public.students (id, student_no, tc_no, first_name, last_name, password_hash)
                VALUES ($1::uuid, $2, $3, $4, $5, $6)
                """,
                student_id,
                f"{owned.run_tag}-{suffix}",
                f"{owned.run_tag}-tc-{suffix}",
                "QA",
                f"Student{suffix.upper()}",
                "qa-student-hash",
            )
            await conn.execute(
                """
                INSERT INTO public.student_courses (student_id, course_id)
                VALUES ($1::uuid, $2::uuid)
                """,
                student_id,
                owned.course_id,
            )


async def _cleanup_owned(pool: Any, owned: OwnedResources, redis: Any) -> None:
    if pool is not None:
        await pool.execute(
            "DELETE FROM public.algorithm_expectations WHERE assignment_id = $1::uuid",
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
        for student_id in (owned.student_a_id, owned.student_b_id):
            await pool.execute(
                "DELETE FROM public.student_courses WHERE student_id = $1::uuid",
                student_id,
            )
            await pool.execute(
                "DELETE FROM public.students WHERE id = $1::uuid",
                student_id,
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


def _expectation_context(owned: OwnedResources) -> Any:
    from backend.algorithm_expectations.cache import AlgorithmExpectationContext

    return AlgorithmExpectationContext(
        assignment_id=owned.assignment_id,
        title=f"{owned.run_tag}-assignment",
        description="Implement binary search on a sorted array. Required complexity O(log n).",
        rubric=({"name": "Correctness", "max_score": 100},),
        difficulty="medium",
    )


def _successful_attempt() -> Any:
    from backend.algorithm_analysis.contracts import ComplexityEstimate
    from backend.algorithm_expectations.generator import (
        AlgorithmExpectationCandidate,
        ExpectationAttempt,
    )

    return ExpectationAttempt(
        candidate=AlgorithmExpectationCandidate(
            expected_complexity=ComplexityEstimate(
                expression="O(log n)",
                family="single_variable",
                rank=1,
                confidence=0.9,
                source="llm",
            ),
            expected_approach="binary search",
            algorithm_families=("binary_search",),
            confidence=0.9,
        ),
        rejection_reason="",
        provider="qa",
        model="qa-model",
        success=True,
    )


def _unit_unknown_gap_no_penalty(ledger: AdversarialLedger) -> None:
    from backend.algorithm_analysis.contracts import GapResult
    from backend.algorithm_analysis.scoring import apply_algorithm_score_guardrail

    gap = GapResult(
        status="unknown",
        steps=None,
        approach_mismatch=False,
        explanation="unknown gap",
    )
    decision = apply_algorithm_score_guardrail(85, 100, gap, ())
    if "algorithm_gap_penalty" in decision.guardrail_flags or decision.cap < 100:
        ledger.unknown_complexity_received_gap_penalty = True


def _unit_merge_guardrails(ledger: AdversarialLedger) -> None:
    from backend.agents.algorithm_evidence import build_evidence_algorithm_result, merge_algorithm_results
    from backend.algorithm_analysis.scoring import apply_algorithm_score_guardrail
    from backend.algorithm_analysis.contracts import AlgorithmEvidence, GapResult

    nested_code = """
def two_sum(values, target):
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] + values[j] == target:
                return i, j
    return None
"""
    evidence = build_evidence_algorithm_result(
        nested_code,
        "python",
        algorithm_expectation={
            "expected_complexity": {
                "expression": "O(n)",
                "family": "single_variable",
                "rank": 2,
                "confidence": 1.0,
                "source": "verified_expectation",
            },
            "algorithm_families": ["hash_lookup"],
        },
    )
    programmatic = {
        "score": 90,
        "programmatic_base_score": evidence.programmatic_base_score,
        "time_complexity": "O(n^2)",
        "expected_complexity": "O(n)",
        "issues": [],
        "detected_algorithms": list(evidence.detected_algorithms),
        "data_structures": list(evidence.data_structures),
    }
    merged = merge_algorithm_results(
        programmatic,
        {"score": 100, "algorithm_analysis": "LLM claims optimal", "issues": []},
        source=nested_code,
        evidence=evidence,
    )
    if merged["score"] > 65:
        ledger.llm_overruled_score_cap = True

    gap = GapResult(
        status="worse_than_expected",
        steps=1,
        approach_mismatch=False,
        explanation="one step worse",
    )
    nested_evidence = (
        AlgorithmEvidence(kind="nested_loop", line=3, detail="depth 2", confidence=0.95),
    )
    ast_decision = apply_algorithm_score_guardrail(90, 100, gap, nested_evidence)
    if ast_decision.score > 80:
        ledger.llm_overruled_ast_lower_bound = True


def _unit_student_projection(ledger: AdversarialLedger) -> None:
    from backend.reporting.student_projection import project_student_result

    private = {
        "totalScore": 88,
        "maxScore": 100,
        "rubric": {},
        "agents": [
            {
                "id": "algorithm",
                "name": "Algoritma",
                "summary": "ok",
                "score": 88,
                "maxScore": 100,
                "findings": [],
                "algorithmResult": {
                    "detectedAlgorithms": ["binary_search"],
                    "dataStructures": [],
                    "timeComplexity": "O(log n)",
                    "spaceComplexity": "O(1)",
                    "actualFamily": "single_variable",
                    "actualConfidence": 0.9,
                    "expectedComplexity": "O(log n)",
                    "expectedApproach": "binary search",
                    "complexityGap": "matches_expected",
                    "gapSteps": 0,
                    "gapExplanation": "ok",
                    "recommendedApproach": "binary search",
                    "expectationId": PHASE3_PROVENANCE_SENTINELS[0],
                    "cacheKey": PHASE3_PROVENANCE_SENTINELS[1],
                    "extractorProvider": PHASE3_PROVENANCE_SENTINELS[2],
                    "verificationReason": PHASE3_PROVENANCE_SENTINELS[3],
                    "evidence": [{"line": 2, "kind": "binary_search", "detail": "loop", "confidence": 0.9}],
                },
            }
        ],
        "fileName": "solution.py",
        "executionTimeMs": 100,
        "memoryUsageMb": 1.0,
        "peakMemoryMb": 1.0,
        "analysisEngine": "agentgrade-v1",
        "summary": "ok",
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "taskAlignment": {},
        "reportStatus": "ready",
    }
    projected = project_student_result(private)
    serialized = json.dumps(projected, ensure_ascii=False)
    if any(sentinel in serialized for sentinel in PHASE3_PROVENANCE_SENTINELS):
        ledger.student_expectation_provenance_leak = True


def _unit_master_wiring(ledger: AdversarialLedger) -> None:
    from backend.agents.master_evaluator import MasterEvaluatorAgent

    agent = MasterEvaluatorAgent()

    def _input(algorithm_score: int) -> dict[str, Any]:
        return {
            "source_code": "def solve(xs):\n    lo, hi = 0, len(xs) - 1\n    return lo\n",
            "language": "python",
            "assignment_description": "Implement binary search. Required complexity O(log n).",
            "rubric": {"functionality": 35, "algorithmic_efficiency": 25, "code_standards": 25, "security": 15},
            "sandbox_result": {"compilation_success": True, "exit_code": 0},
            "task_alignment": {"factor": 0.95, "reasons": []},
            "evidence": {"validated_claims": [], "total_claims_received": 0, "total_claims_validated": 0},
            "code_quality": {"score": 80},
            "test_agent": {"score": 82, "runs_successfully": True},
            "seniority": {"score": 75},
            "guideline": {"score": 70},
            "security": {"score": 95, "risk_level": "safe", "critical_count": 0, "high_count": 0},
            "algorithm": {"score": algorithm_score, "time_complexity": "O(log n)", "complexity_gap": "matches_expected"},
        }

    low = agent._programmatic_analysis(_input(5))
    high = agent._programmatic_analysis(_input(100))
    if low["final_score"] != high["final_score"] or low["rubric_breakdown"] != high["rubric_breakdown"]:
        ledger.algorithm_score_changed_master_rubric = True


def _unit_mutation_routes(ledger: AdversarialLedger) -> None:
    from frontend.backend import main

    mutation_methods = {"POST", "PUT", "PATCH", "DELETE"}
    for route in main.app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "") or ""
        if "algorithm-expectation" not in path.lower():
            continue
        if methods & mutation_methods:
            ledger.teacher_expectation_mutation_route_exists = True


async def _unit_lease_loss_aborts() -> None:
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from backend.algorithm_expectations import service as service_module
    from backend.algorithm_expectations.cache import AlgorithmExpectationLeaseLost
    from backend.algorithm_expectations.store import DemoAlgorithmExpectationStore

    context = _expectation_context(
        OwnedResources(
            run_tag="lease-unit",
            teacher_id=str(uuid.uuid4()),
            course_id=str(uuid.uuid4()),
            assignment_id=str(uuid.uuid4()),
            student_a_id=str(uuid.uuid4()),
            student_b_id=str(uuid.uuid4()),
        )
    )

    @asynccontextmanager
    async def _lease_that_loses(redis_client, assignment_id, cache_key, **kwargs):
        del redis_client, assignment_id, cache_key, kwargs
        handle = MagicMock()
        handle.check.side_effect = AlgorithmExpectationLeaseLost("lease lost")
        yield handle

    original = service_module.expectation_generation_lock
    service_module.expectation_generation_lock = _lease_that_loses
    try:
        resolution = await service_module.resolve_expectation(
            context,
            store=DemoAlgorithmExpectationStore({"algorithm_expectations": []}),
            redis=MagicMock(),
            generate_once=AsyncMock(return_value=_successful_attempt()),
        )
    finally:
        service_module.expectation_generation_lock = original

    if resolution.status != "unknown" or resolution.expectation is not None:
        raise AssertionError("lease-loss must abort fail-closed with unknown status")


async def _run_qa(*, manage_services: bool) -> int:
    from backend.algorithm_expectations.cache import compute_expectation_identity
    from backend.algorithm_expectations.generator import build_extractor_prompt, build_verifier_prompt, ExtractorResponse
    from backend.algorithm_expectations.service import resolve_expectation
    from backend.algorithm_expectations.store import PostgresAlgorithmExpectationStore
    from backend.core.config import settings
    from frontend.backend import main

    ledger = AdversarialLedger()
    run_tag = f"qa-phase3-{uuid.uuid4()}"
    owned = OwnedResources(
        run_tag=run_tag,
        teacher_id=str(uuid.uuid4()),
        course_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        student_a_id=str(uuid.uuid4()),
        student_b_id=str(uuid.uuid4()),
    )
    owned.redis_lock_prefix = f"algorithm:expectation_lock:{owned.assignment_id}:*"

    started_by_script: list[str] = []
    pool = None
    redis = None

    if manage_services:
        already_running = _running_compose_services()
        to_start = [svc for svc in TARGET_SERVICES if svc not in already_running]
        if to_start:
            _start_compose_services(to_start)
            started_by_script = to_start
            await asyncio.sleep(2.0)

    try:
        _unit_unknown_gap_no_penalty(ledger)
        _unit_merge_guardrails(ledger)
        _unit_student_projection(ledger)
        _unit_master_wiring(ledger)
        _unit_mutation_routes(ledger)
        await _unit_lease_loss_aborts()

        await _wait_redis(settings.redis_url)
        await _wait_postgres(settings.database_url)

        import asyncpg
        import redis.asyncio as redis_async

        dsn = _asyncpg_dsn(settings.database_url)
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
        main._DB_POOL = pool
        await main._ensure_db_schema(pool)
        redis = redis_async.from_url(settings.redis_url, decode_responses=True)
        await redis.ping()

        await _seed_assignment(pool, owned)
        context = _expectation_context(owned)
        store = PostgresAlgorithmExpectationStore(pool)

        student_code_sentinel = f"{STUDENT_CODE_SENTINEL_PREFIX}_{run_tag}"
        _student_submission = f"print('{student_code_sentinel}')\n"  # noqa: F841

        extractor_prompt = build_extractor_prompt(context)
        verifier_prompt = build_verifier_prompt(
            context,
            ExtractorResponse(
                expected_complexity="O(log n)",
                expected_approach="binary search",
                algorithm_families=["binary_search"],
                confidence=0.9,
            ),
            "0",
        )
        if student_code_sentinel in extractor_prompt or student_code_sentinel in verifier_prompt:
            ledger.student_code_appeared_in_expectation_prompt = True

        release = asyncio.Event()
        generation_calls = 0
        captured_prompts: list[str] = []

        async def tracked_generate_once(ctx: Any) -> Any:
            nonlocal generation_calls
            generation_calls += 1
            captured_prompts.append(build_extractor_prompt(ctx))
            await release.wait()
            return _successful_attempt()

        task_a = asyncio.create_task(
            resolve_expectation(context, store=store, redis=redis, generate_once=tracked_generate_once)
        )
        task_b = asyncio.create_task(
            resolve_expectation(context, store=store, redis=redis, generate_once=tracked_generate_once)
        )
        await asyncio.sleep(0.05)
        release.set()
        resolution_a, resolution_b = await asyncio.gather(task_a, task_b)

        if generation_calls != 1:
            ledger.second_expectation_generator_ran = True
        if (
            resolution_a.expectation is None
            or resolution_b.expectation is None
            or resolution_a.expectation.id != resolution_b.expectation.id
            or resolution_a.expectation.version != resolution_b.expectation.version
        ):
            raise AssertionError(
                "concurrent resolutions must share expectation ID/version: "
                f"{getattr(resolution_a.expectation, 'id', None)}/{getattr(resolution_a.expectation, 'version', None)} "
                f"vs {getattr(resolution_b.expectation, 'id', None)}/{getattr(resolution_b.expectation, 'version', None)}"
            )
        owned.generation_calls = generation_calls
        owned.first_expectation_id = resolution_a.expectation.id
        owned.first_expectation_version = resolution_a.expectation.version
        owned.first_cache_key = resolution_a.expectation.cache_key

        if any(student_code_sentinel in prompt for prompt in captured_prompts):
            ledger.student_code_appeared_in_expectation_prompt = True

        async def _must_not_regenerate(_ctx: Any) -> Any:
            raise AssertionError("must not regenerate")

        student_a = await resolve_expectation(
            context,
            store=store,
            redis=redis,
            generate_once=_must_not_regenerate,
        )
        student_b = await resolve_expectation(
            context,
            store=store,
            redis=redis,
            generate_once=_must_not_regenerate,
        )
        if (
            student_a.expectation is None
            or student_b.expectation is None
            or student_a.expectation.id != student_b.expectation.id
        ):
            ledger.different_students_received_different_expectation = True

        deactivated = await store.deactivate_assignment(owned.assignment_id, reason="qa-reactivation")
        if deactivated < 1:
            raise AssertionError("expected at least one active expectation to deactivate")
        reactivated = await resolve_expectation(
            context,
            store=store,
            redis=redis,
            generate_once=_must_not_regenerate,
        )
        if reactivated.expectation is None:
            raise AssertionError("exact-key reactivation must return an expectation")
        if reactivated.expectation.id != owned.first_expectation_id:
            raise AssertionError(
                f"reactivation must reuse prior ID: {reactivated.expectation.id} != {owned.first_expectation_id}"
            )
        if reactivated.expectation.cache_key != owned.first_cache_key:
            raise AssertionError("reactivation must reuse exact cache key")

        provider = (settings.llm_provider or "ollama").strip().lower()
        model = (
            settings.nvidia_nim_general_model
            if provider in {"nvidia_nim", "nim", "nvidia"}
            else settings.ollama_general_model
        )
        cache_key = compute_expectation_identity(context, provider, model).cache_key
        lock_key = f"algorithm:expectation_lock:{owned.assignment_id}:{cache_key}"
        if await redis.get(lock_key) is not None:
            raise AssertionError("generation lock must be released after resolution")

        ledger.assert_secure()
        print("PASS", flush=True)
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", flush=True)
        return 1
    finally:
        ledger.print_report()
        if pool is not None:
            try:
                await _cleanup_owned(pool, owned, redis)
            except Exception:
                pass
            try:
                await pool.close()
            except Exception:
                pass
            main._DB_POOL = None
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:
                pass
        if started_by_script:
            _stop_compose_services(started_by_script)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3 algorithm expectation QA gate")
    parser.add_argument(
        "--manage-services",
        action="store_true",
        help="Start docker compose redis/postgres if not already running",
    )
    args = parser.parse_args()
    return asyncio.run(_run_qa(manage_services=args.manage_services))


if __name__ == "__main__":
    raise SystemExit(main())
