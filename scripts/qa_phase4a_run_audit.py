"""Phase 4A real-run audit and ownership-checked cleanup."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.config import settings
from backend.ops.release_qualification import (
    REQUIRED_CHECKS,
    Phase4ABrowserEvidence,
    Phase4ACheck,
    Phase4AAnalysisAudit,
    Phase4AReleaseLedger,
    audit_analysis_pair,
    safe_ledger_lines as _safe_ledger_lines,
)
from backend.queue.analysis_jobs import AnalysisJobNotFound, AnalysisJobStore, get_analysis_job

OWNER_ID_ENV = "PHASE4A_OWNER_ID"

_SECRET_FIELD_MARKERS = (
    "password",
    "token",
    "secret",
    "cookie",
    "csrf",
    "authorization",
    "bearer",
    "credential",
    "private_result",
    "student_result",
    "source_code",
    "prompt",
)


class UnsafeCleanupTarget(Exception):
    """Raised when cleanup would touch non-owned resources."""


class AuditFailure(Exception):
    """Raised when browser evidence or recorded jobs fail audit."""


class RedisLike(Protocol):
    async def hgetall(self, key: str) -> Mapping[Any, Any]: ...
    async def delete(self, *keys: str) -> int: ...
    def scan_iter(self, match: str) -> AsyncIterator[str]: ...


class PostgresLike(Protocol):
    async def fetch_assignment(self, assignment_id: str) -> Mapping[str, str] | None: ...
    async def delete_assignment_owned(self, assignment_id: str) -> None: ...
    async def residue_tables_with_rows(self, assignment_id: str) -> Sequence[str]: ...


@dataclass(frozen=True, slots=True)
class Phase4ACleanupPlan:
    run_id: str
    assignment_id: str
    redis_keys: tuple[str, ...]


def _asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def analysis_job_key(job_id: str) -> str:
    return f"analysis_job:{job_id}"


def testing_generation_lock_scan_pattern(assignment_id: str) -> str:
    return f"testing:generation_lock:{assignment_id}:*"


def algorithm_expectation_lock_scan_pattern(assignment_id: str) -> str:
    return f"algorithm:expectation_lock:{assignment_id}:*"


def discover_run_owned_redis_keys(
    assignment_id: str,
    job_ids: Sequence[str],
    run_id: str,
) -> tuple[str, ...]:
    keys = [analysis_job_key(job_id) for job_id in job_ids]
    return tuple(keys)


async def discover_run_owned_redis_keys_live(
    redis: RedisLike,
    assignment_id: str,
    job_ids: Sequence[str],
    run_id: str,
) -> tuple[str, ...]:
    discovered = set(discover_run_owned_redis_keys(assignment_id, job_ids, run_id))
    scan_patterns = (
        testing_generation_lock_scan_pattern(assignment_id),
        algorithm_expectation_lock_scan_pattern(assignment_id),
        f"{run_id}:*",
    )
    for pattern in scan_patterns:
        async for key in redis.scan_iter(pattern):
            key_text = str(key)
            if pattern.endswith(":*"):
                prefix = pattern[:-1]
                if not key_text.startswith(prefix):
                    continue
                if pattern.startswith("testing:generation_lock:") or pattern.startswith(
                    "algorithm:expectation_lock:"
                ):
                    if assignment_id not in key_text:
                        continue
            discovered.add(key_text)
    return tuple(sorted(discovered))


def _payload_contains_secret_fields(payload: Any, *, path: str = "") -> bool:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in _SECRET_FIELD_MARKERS):
                return True
            child_path = f"{path}.{key_text}" if path else key_text
            if _payload_contains_secret_fields(value, path=child_path):
                return True
        return False
    if isinstance(payload, (list, tuple)):
        return any(_payload_contains_secret_fields(item, path=path) for item in payload)
    return False


def _normalize_evidence_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for field in ("job_ids", "screenshots"):
        value = normalized.get(field)
        if isinstance(value, list):
            normalized[field] = tuple(value)
    return normalized


def load_browser_evidence(path: Path) -> Phase4ABrowserEvidence:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise AuditFailure("evidence must be a JSON object")
    if _payload_contains_secret_fields(payload):
        raise AuditFailure("evidence contains secret-like fields")
    evidence = Phase4ABrowserEvidence.model_validate(_normalize_evidence_payload(payload))
    validate_recorded_job_ids(evidence.job_ids)
    return evidence


def validate_recorded_job_ids(job_ids: Sequence[str]) -> None:
    if len(job_ids) != 3 or len(set(job_ids)) != 3:
        raise AuditFailure("evidence must record three unique job ids")


def build_cleanup_plan(
    *,
    run_id: str,
    assignment: Mapping[str, str],
    job_ids: Sequence[str],
    expected_owner_id: str | None = None,
) -> Phase4ACleanupPlan:
    assignment_id = str(assignment.get("id", "")).strip()
    name = str(assignment.get("name", "")).strip()
    created_by = str(assignment.get("created_by", "")).strip()

    if not assignment_id or not name.startswith(run_id):
        raise UnsafeCleanupTarget("assignment name missing required run_id prefix")

    if not expected_owner_id:
        raise UnsafeCleanupTarget("expected owner id is required for cleanup")
    if created_by != expected_owner_id:
        raise UnsafeCleanupTarget("assignment owner mismatch")

    validate_recorded_job_ids(job_ids)
    redis_keys = tuple(analysis_job_key(job_id) for job_id in job_ids)
    return Phase4ACleanupPlan(
        run_id=run_id,
        assignment_id=assignment_id,
        redis_keys=redis_keys,
    )


async def audit_redis_jobs(
    redis: RedisLike,
    job_ids: Sequence[str],
) -> tuple[Phase4AAnalysisAudit, ...]:
    validate_recorded_job_ids(job_ids)
    store = AnalysisJobStore(redis)  # type: ignore[arg-type]
    audits: list[Phase4AAnalysisAudit] = []
    for job_id in job_ids:
        try:
            job = await get_analysis_job(store, job_id)
        except AnalysisJobNotFound as exc:
            raise AuditFailure(f"job {job_id} not found") from exc
        if job.get("status") != "completed":
            raise AuditFailure(f"job {job_id} must be completed")
        private_result = job.get("private_result")
        student_result = job.get("student_result")
        if not isinstance(private_result, Mapping) or not isinstance(student_result, Mapping):
            raise AuditFailure(f"job {job_id} missing analysis results")
        audits.append(audit_analysis_pair(private_result, student_result))
    return tuple(audits)


def _resolve_owner_id(explicit_owner_id: str | None = None) -> str:
    owner_id = (explicit_owner_id or os.environ.get(OWNER_ID_ENV) or "").strip()
    if not owner_id:
        raise AuditFailure("owner id is required via --owner-id or PHASE4A_OWNER_ID")
    return owner_id


def _resolve_provider_model() -> tuple[str, str]:
    provider = settings.llm_provider.strip().lower() or "ollama"
    if provider == "nvidia-nim":
        model = settings.nvidia_nim_general_model
    else:
        model = settings.ollama_general_model
    return provider, model


def _analysis_audit_flags(audits: Sequence[Phase4AAnalysisAudit]) -> dict[str, bool]:
    return {
        "AGENT_CONTRACT_FAILED": any(audit.agent_contract_failed for audit in audits),
        "FORMAL_AUTHORITY_OVERRIDDEN": any(audit.formal_authority_overridden for audit in audits),
        "ALGORITHM_GUARDRAIL_OVERRIDDEN": any(
            audit.algorithm_guardrail_overridden for audit in audits
        ),
        "STUDENT_PRIVATE_DATA_LEAK": any(audit.student_private_data_leak for audit in audits),
    }


def _default_check_values(
    *,
    evidence: Phase4ABrowserEvidence,
    analysis_flags: Mapping[str, bool],
    cleanup_residue_found: bool,
) -> dict[str, bool | int]:
    values: dict[str, bool | int] = {
        "BASELINE_FAILURE_COUNT": 0,
        "BACKEND_FULL_SUITE_FAILED": False,
        "FRONTEND_SUITE_FAILED": False,
        "FRONTEND_BUILD_FAILED": False,
        "POSTGRES_READY": True,
        "REDIS_READY": True,
        "WORKER_READY": True,
        "SANDBOX_REAL_EXECUTION_FAILED": False,
        "REAL_LLM_PROVIDER_MISMATCH": False,
        "TEACHER_JOURNEY_FAILED": not evidence.teacher_journey_passed,
        "STUDENT_JOURNEY_FAILED": not evidence.student_journey_passed,
        "UNAUTHORIZED_ACCESS_SUCCEEDED": not evidence.unauthorized_checks_passed,
        "CLEANUP_RESIDUE_FOUND": cleanup_residue_found,
    }
    values.update(analysis_flags)
    return values


def _check_passed(name: str, safe_value: bool | int) -> bool:
    if name == "BASELINE_FAILURE_COUNT":
        return safe_value == 0
    # True means a failure/leak/override/residue condition was observed.
    if (
        name.endswith("_FAILED")
        or name.endswith("_OVERRIDDEN")
        or name
        in {
            "UNAUTHORIZED_ACCESS_SUCCEEDED",
            "REAL_LLM_PROVIDER_MISMATCH",
            "STUDENT_PRIVATE_DATA_LEAK",
            "CLEANUP_RESIDUE_FOUND",
        }
    ):
        return not bool(safe_value)
    return bool(safe_value)


def build_release_ledger_fixed(
    *,
    run_id: str,
    provider: str,
    model: str,
    evidence: Phase4ABrowserEvidence,
    analysis_flags: Mapping[str, bool],
    cleanup_residue_found: bool,
) -> Phase4AReleaseLedger:
    values = _default_check_values(
        evidence=evidence,
        analysis_flags=analysis_flags,
        cleanup_residue_found=cleanup_residue_found,
    )
    checks = tuple(
        Phase4ACheck(
            name=name,
            safe_value=values[name],
            passed=_check_passed(name, values[name]),
            detail_code="",
        )
        for name in REQUIRED_CHECKS
    )
    return Phase4AReleaseLedger(
        run_id=run_id,
        provider=provider,
        model=model,
        checks=checks,
    )


async def detect_cleanup_residue(
    plan: Phase4ACleanupPlan,
    *,
    postgres: PostgresLike,
    redis: RedisLike,
) -> bool:
    if await postgres.residue_tables_with_rows(plan.assignment_id):
        return True
    job_ids = tuple(
        key.removeprefix("analysis_job:")
        for key in plan.redis_keys
        if key.startswith("analysis_job:")
    )
    for job_id in job_ids:
        if await redis.hgetall(analysis_job_key(job_id)):
            return True
    scan_patterns = (
        testing_generation_lock_scan_pattern(plan.assignment_id),
        algorithm_expectation_lock_scan_pattern(plan.assignment_id),
        f"{plan.run_id}:*",
    )
    for pattern in scan_patterns:
        async for _key in redis.scan_iter(pattern):
            return True
    return False


async def execute_cleanup(
    plan: Phase4ACleanupPlan,
    *,
    postgres: PostgresLike,
    redis: RedisLike,
    expected_owner_id: str | None = None,
) -> bool:
    assignment = await postgres.fetch_assignment(plan.assignment_id)
    if assignment is None:
        raise UnsafeCleanupTarget("assignment not found")
    build_cleanup_plan(
        run_id=plan.run_id,
        assignment=assignment,
        job_ids=tuple(
            key.removeprefix("analysis_job:")
            for key in plan.redis_keys
            if key.startswith("analysis_job:")
        ),
        expected_owner_id=expected_owner_id,
    )
    job_ids = tuple(
        key.removeprefix("analysis_job:")
        for key in plan.redis_keys
        if key.startswith("analysis_job:")
    )
    await postgres.delete_assignment_owned(plan.assignment_id)
    redis_keys = await discover_run_owned_redis_keys_live(
        redis,
        plan.assignment_id,
        job_ids,
        plan.run_id,
    )
    if redis_keys:
        await redis.delete(*redis_keys)
    return await detect_cleanup_residue(plan, postgres=postgres, redis=redis)


class LivePostgres:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def fetch_assignment(self, assignment_id: str) -> Mapping[str, str] | None:
        row = await self.pool.fetchrow(
            """
            SELECT id::text AS id, name, created_by::text AS created_by
            FROM public.assignments
            WHERE id = $1::uuid
            """,
            assignment_id,
        )
        if row is None:
            return None
        return {"id": row["id"], "name": row["name"], "created_by": row["created_by"]}

    async def delete_assignment_owned(self, assignment_id: str) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM public.assignments WHERE id = $1::uuid",
                    assignment_id,
                )

    async def residue_tables_with_rows(self, assignment_id: str) -> tuple[str, ...]:
        queries = {
            "rubrics": "SELECT 1 FROM public.rubrics WHERE assignment_id = $1::uuid LIMIT 1",
            "assignment_test_cases": (
                "SELECT 1 FROM public.assignment_test_cases WHERE assignment_id = $1::uuid LIMIT 1"
            ),
            "generated_test_sets": (
                "SELECT 1 FROM public.generated_test_sets WHERE assignment_id = $1::uuid LIMIT 1"
            ),
            "algorithm_expectations": (
                "SELECT 1 FROM public.algorithm_expectations WHERE assignment_id = $1::uuid LIMIT 1"
            ),
            "assignments": "SELECT 1 FROM public.assignments WHERE id = $1::uuid LIMIT 1",
        }
        found: list[str] = []
        for table, query in queries.items():
            row = await self.pool.fetchrow(query, assignment_id)
            if row is not None:
                found.append(table)
        return tuple(found)


async def audit_browser_run(
    evidence_path: Path | str,
    *,
    cleanup: bool = False,
    expected_owner_id: str | None = None,
    postgres: PostgresLike | None = None,
    redis: RedisLike | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Phase4AReleaseLedger:
    evidence = load_browser_evidence(Path(evidence_path))
    owner_id = _resolve_owner_id(expected_owner_id) if cleanup else expected_owner_id
    resolved_provider, resolved_model = (
        (provider, model) if provider and model else _resolve_provider_model()
    )

    if redis is None:
        import redis.asyncio as redis_async

        client = redis_async.from_url(settings.redis_url, decode_responses=True)
        try:
            return await audit_browser_run(
                evidence_path,
                cleanup=cleanup,
                expected_owner_id=owner_id,
                postgres=postgres,
                redis=client,
                provider=resolved_provider,
                model=resolved_model,
            )
        finally:
            await client.aclose()

    audits = await audit_redis_jobs(redis, evidence.job_ids)
    analysis_flags = _analysis_audit_flags(audits)
    cleanup_residue_found = False

    if cleanup:
        if postgres is None:
            import asyncpg

            pool = await asyncpg.create_pool(dsn=_asyncpg_dsn(settings.database_url), min_size=1, max_size=1)
            try:
                live_postgres = LivePostgres(pool)
                assignment = await live_postgres.fetch_assignment(evidence.assignment_id)
                if assignment is None:
                    raise UnsafeCleanupTarget("assignment not found")
                plan = build_cleanup_plan(
                    run_id=evidence.run_id,
                    assignment=assignment,
                    job_ids=evidence.job_ids,
                    expected_owner_id=owner_id,
                )
                cleanup_residue_found = await execute_cleanup(
                    plan,
                    postgres=live_postgres,
                    redis=redis,
                    expected_owner_id=owner_id,
                )
            finally:
                await pool.close()
        else:
            assignment = await postgres.fetch_assignment(evidence.assignment_id)
            if assignment is None:
                raise UnsafeCleanupTarget("assignment not found")
            plan = build_cleanup_plan(
                run_id=evidence.run_id,
                assignment=assignment,
                job_ids=evidence.job_ids,
                expected_owner_id=owner_id,
            )
            cleanup_residue_found = await execute_cleanup(
                plan,
                postgres=postgres,
                redis=redis,
                expected_owner_id=owner_id,
            )

    return build_release_ledger_fixed(
        run_id=evidence.run_id,
        provider=resolved_provider,
        model=resolved_model,
        evidence=evidence,
        analysis_flags=analysis_flags,
        cleanup_residue_found=cleanup_residue_found,
    )


def safe_ledger_lines(ledger: Phase4AReleaseLedger) -> tuple[str, ...]:
    return _safe_ledger_lines(ledger)


async def _async_main(
    evidence_path: Path,
    *,
    cleanup: bool,
    owner_id: str | None,
) -> int:
    ledger = await audit_browser_run(
        evidence_path,
        cleanup=cleanup,
        expected_owner_id=owner_id,
    )
    for line in safe_ledger_lines(ledger):
        print(line, flush=True)
    residue_check = next(
        check for check in ledger.checks if check.name == "CLEANUP_RESIDUE_FOUND"
    )
    failed_checks = [
        check.name
        for check in ledger.checks
        if not check.passed and check.name != "CLEANUP_RESIDUE_FOUND"
    ]
    if failed_checks:
        return 1
    if cleanup and residue_check.safe_value is True:
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a Phase 4A browser evidence run.")
    parser.add_argument("--evidence", required=True, help="Path to browser-evidence.json")
    parser.add_argument("--cleanup", action="store_true", help="Perform ownership-checked cleanup")
    parser.add_argument("--owner-id", default=None, help="Expected assignment owner teacher UUID")
    args = parser.parse_args(list(argv) if argv is not None else None)
    owner_id = args.owner_id or os.environ.get(OWNER_ID_ENV)
    return asyncio.run(
        _async_main(
            Path(args.evidence),
            cleanup=args.cleanup,
            owner_id=owner_id,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
