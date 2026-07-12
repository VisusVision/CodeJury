"""Pure unit tests for Phase 4A real-run audit and ownership-checked cleanup."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.ops.release_qualification import (
    REQUIRED_CHECKS,
    Phase4ABrowserEvidence,
    Phase4ACheck,
    Phase4AReleaseLedger,
)
from backend.reporting.student_projection import project_student_result

ROOT = Path(__file__).resolve().parents[2]

RUN_ID = "phase4a-11111111-1111-4111-8111-111111111111"
ASSIGNMENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
JOB_IDS = ("job-1", "job-2", "job-3")


def _load_audit_module():
    path = ROOT / "scripts" / "qa_phase4a_run_audit.py"
    spec = importlib.util.spec_from_file_location("qa_phase4a_run_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load audit script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["qa_phase4a_run_audit"] = module
    spec.loader.exec_module(module)
    return module


def _owned_assignment(*, name: str | None = None, created_by: str = OWNER_ID) -> dict[str, str]:
    return {
        "id": ASSIGNMENT_ID,
        "name": name or f"{RUN_ID} Algorithm QA",
        "created_by": created_by,
    }


def _valid_evidence_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "run_id": RUN_ID,
        "assignment_id": ASSIGNMENT_ID,
        "job_ids": list(JOB_IDS),
        "teacher_journey_passed": True,
        "student_journey_passed": True,
        "unauthorized_checks_passed": True,
        "screenshots": [],
    }
    payload.update(overrides)
    return payload


def _minimal_private_result() -> dict[str, object]:
    from backend.ops.release_qualification import (
        REQUIRED_AGENT_IDS,
        REQUIRED_PRESENTATION_AGENT_IDS,
    )

    def presentation(agent_id: str) -> dict[str, object]:
        agent: dict[str, object] = {
            "id": agent_id,
            "name": agent_id,
            "summary": "ready",
            "score": 80,
            "maxScore": 100,
            "findings": [],
        }
        if agent_id == "algorithm":
            agent["algorithmResult"] = {
                "timeComplexity": "O(n)",
                "expectedComplexity": "O(n)",
                "complexityGap": "matches_expected",
                "gapSteps": 0,
                "gapExplanation": "ok",
                "programmatic_base_score": 90,
                "evidence": [],
            }
        if agent_id == "testing":
            agent["testResults"] = [
                {
                    "name": "public",
                    "input": "1",
                    "expected": "1",
                    "actual": "1",
                    "passed": True,
                    "visibility": "public",
                },
                {"name": "hidden", "visibility": "hidden", "status": "failed", "passed": False},
            ]
        return agent

    def diagnostic(agent_id: str) -> dict[str, object]:
        return {
            "id": agent_id,
            "score": 80,
            "llm_status": "ok",
            "confidence": 0.9,
            "guardrail_flags": [],
        }

    return {
        "reportStatus": "ready",
        "formalPassed": 1,
        "formalTotal": 2,
        "agents": [presentation(agent_id) for agent_id in sorted(REQUIRED_PRESENTATION_AGENT_IDS)],
        "agentDiagnostics": {
            "agents": [diagnostic(agent_id) for agent_id in sorted(REQUIRED_AGENT_IDS)],
        },
    }


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.keys: set[str] = set()
        self.deleted: list[str] = []

    def seed_job(
        self,
        job_id: str,
        *,
        status: str = "completed",
        private_result: dict[str, object] | None = None,
        student_result: dict[str, object] | None = None,
    ) -> None:
        key = f"analysis_job:{job_id}"
        private = private_result or _minimal_private_result()
        student = student_result or project_student_result(private)
        self.hashes[key] = {
            "job_id": job_id,
            "status": status,
            "private_result": json.dumps(private, ensure_ascii=False, separators=(",", ":")),
            "student_result": json.dumps(student, ensure_ascii=False, separators=(",", ":")),
        }
        self.keys.add(key)

    def seed_key(self, key: str) -> None:
        self.keys.add(key)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def delete(self, *keys: str) -> int:
        for key in keys:
            self.deleted.append(key)
            self.hashes.pop(key, None)
            self.keys.discard(key)
        return len(keys)

    async def scan_iter(self, match: str) -> AsyncIterator[str]:
        prefix = match[:-1] if match.endswith("*") else match
        for key in sorted(self.keys):
            if key.startswith(prefix):
                yield key


class FakePostgres:
    RESIDUE_TABLES = (
        "rubrics",
        "assignment_test_cases",
        "generated_test_sets",
        "algorithm_expectations",
        "assignments",
    )

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, str]]] = {
            table: [] for table in self.RESIDUE_TABLES
        }
        self.fail_on_delete = False
        self.delete_attempted = False

    def seed_assignment(self, assignment: dict[str, str]) -> None:
        self.tables["assignments"].append(
            {"id": assignment["id"], "name": assignment["name"], "created_by": assignment["created_by"]}
        )

    def seed_related_rows(self, assignment_id: str) -> None:
        self.tables["rubrics"].append({"assignment_id": assignment_id})
        self.tables["assignment_test_cases"].append({"assignment_id": assignment_id})
        self.tables["generated_test_sets"].append({"assignment_id": assignment_id})
        self.tables["algorithm_expectations"].append({"assignment_id": assignment_id})

    async def fetch_assignment(self, assignment_id: str) -> dict[str, str] | None:
        for row in self.tables["assignments"]:
            if row["id"] == assignment_id:
                return dict(row)
        return None

    async def delete_assignment_owned(self, assignment_id: str) -> None:
        self.delete_attempted = True
        if self.fail_on_delete:
            raise RuntimeError("simulated transaction failure")
        for table in self.RESIDUE_TABLES:
            self.tables[table] = [
                row
                for row in self.tables[table]
                if row.get("assignment_id") != assignment_id and row.get("id") != assignment_id
            ]

    async def residue_tables_with_rows(self, assignment_id: str) -> tuple[str, ...]:
        found: list[str] = []
        for table in self.RESIDUE_TABLES:
            if any(
                row.get("assignment_id") == assignment_id or row.get("id") == assignment_id
                for row in self.tables[table]
            ):
                found.append(table)
        return tuple(found)

    async def residue_redis_keys(
        self,
        *,
        assignment_id: str,
        job_ids: tuple[str, ...],
        run_id: str,
        redis: FakeRedis,
    ) -> tuple[str, ...]:
        audit = _load_audit_module()
        expected = set(audit.discover_run_owned_redis_keys(assignment_id, job_ids, run_id))
        for key in sorted(redis.keys):
            if key in expected:
                continue
            if key.startswith("analysis_job:"):
                continue
            if (
                key.startswith(f"testing:generation_lock:{assignment_id}:")
                or key.startswith(f"algorithm:expectation_lock:{assignment_id}:")
                or key.startswith(f"{run_id}:")
            ):
                continue
            continue
        remaining = [key for key in sorted(redis.keys) if key in expected]
        return tuple(remaining)


@pytest.fixture
def audit_module():
    return _load_audit_module()


def test_cleanup_refuses_assignment_without_exact_run_prefix(audit_module) -> None:
    with pytest.raises(audit_module.UnsafeCleanupTarget):
        audit_module.build_cleanup_plan(
            run_id=RUN_ID,
            assignment={"id": ASSIGNMENT_ID, "name": "Existing Assignment", "created_by": OWNER_ID},
            job_ids=JOB_IDS,
            expected_owner_id=OWNER_ID,
        )


def test_cleanup_refuses_wrong_owner(audit_module) -> None:
    with pytest.raises(audit_module.UnsafeCleanupTarget):
        audit_module.build_cleanup_plan(
            run_id=RUN_ID,
            assignment=_owned_assignment(created_by="cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            job_ids=JOB_IDS,
            expected_owner_id=OWNER_ID,
        )


def test_cleanup_plan_contains_only_recorded_jobs(audit_module) -> None:
    plan = audit_module.build_cleanup_plan(
        run_id=RUN_ID,
        assignment=_owned_assignment(),
        job_ids=JOB_IDS,
        expected_owner_id=OWNER_ID,
    )
    assert plan.redis_keys == (
        "analysis_job:job-1",
        "analysis_job:job-2",
        "analysis_job:job-3",
    )


@pytest.mark.asyncio
async def test_cleanup_does_not_delete_unrelated_redis_key(audit_module) -> None:
    redis = FakeRedis()
    postgres = FakePostgres()
    postgres.seed_assignment(_owned_assignment())
    postgres.seed_related_rows(ASSIGNMENT_ID)
    for job_id in JOB_IDS:
        redis.seed_job(job_id)
    unrelated = "analysis_job:someone-else"
    redis.seed_key(unrelated)
    owned_lock = f"testing:generation_lock:{ASSIGNMENT_ID}:cache-a"
    redis.seed_key(owned_lock)
    unrelated_lock = f"testing:generation_lock:other-assignment:cache-b"
    redis.seed_key(unrelated_lock)

    plan = audit_module.build_cleanup_plan(
        run_id=RUN_ID,
        assignment=_owned_assignment(),
        job_ids=JOB_IDS,
        expected_owner_id=OWNER_ID,
    )
    residue = await audit_module.execute_cleanup(
        plan,
        postgres=postgres,
        redis=redis,
        expected_owner_id=OWNER_ID,
    )

    assert unrelated in redis.keys
    assert unrelated_lock in redis.keys
    assert owned_lock not in redis.keys
    assert residue is False
    assert unrelated not in redis.deleted
    assert unrelated_lock not in redis.deleted


def test_duplicate_job_ids_fail_closed(audit_module) -> None:
    with pytest.raises(audit_module.AuditFailure, match="unique"):
        audit_module.validate_recorded_job_ids(("job-1", "job-1", "job-2"))


@pytest.mark.asyncio
async def test_missing_completed_job_fails_audit(audit_module) -> None:
    redis = FakeRedis()
    redis.seed_job("job-1")
    redis.seed_job("job-2")
    redis.seed_job("job-3", status="running")

    with pytest.raises(audit_module.AuditFailure, match="completed"):
        await audit_module.audit_redis_jobs(redis, JOB_IDS)


def test_malformed_evidence_rejected(audit_module, tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps({"run_id": RUN_ID}), encoding="utf-8")
    with pytest.raises(ValidationError):
        audit_module.load_browser_evidence(evidence_path)


def test_secret_like_evidence_fields_rejected(audit_module, tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    payload = _valid_evidence_payload(password="secret-value")
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(audit_module.AuditFailure, match="secret"):
        audit_module.load_browser_evidence(evidence_path)


@pytest.mark.asyncio
async def test_transaction_failure_rolls_back_without_redis_delete(audit_module) -> None:
    redis = FakeRedis()
    postgres = FakePostgres()
    postgres.fail_on_delete = True
    postgres.seed_assignment(_owned_assignment())
    for job_id in JOB_IDS:
        redis.seed_job(job_id)

    plan = audit_module.build_cleanup_plan(
        run_id=RUN_ID,
        assignment=_owned_assignment(),
        job_ids=JOB_IDS,
        expected_owner_id=OWNER_ID,
    )

    with pytest.raises(RuntimeError, match="simulated transaction failure"):
        await audit_module.execute_cleanup(
            plan,
            postgres=postgres,
            redis=redis,
            expected_owner_id=OWNER_ID,
        )

    assert redis.deleted == []
    assert postgres.delete_attempted is True


@pytest.mark.asyncio
async def test_residue_detection_reports_cleanup_failure(audit_module) -> None:
    redis = FakeRedis()
    postgres = FakePostgres()
    postgres.seed_assignment(_owned_assignment())
    postgres.seed_related_rows(ASSIGNMENT_ID)
    for job_id in JOB_IDS:
        redis.seed_job(job_id)
    leftover = f"testing:generation_lock:{ASSIGNMENT_ID}:leftover"
    redis.seed_key(leftover)

    plan = audit_module.build_cleanup_plan(
        run_id=RUN_ID,
        assignment=_owned_assignment(),
        job_ids=JOB_IDS,
        expected_owner_id=OWNER_ID,
    )

    async def flaky_cleanup(plan, *, postgres, redis, expected_owner_id):
        await postgres.delete_assignment_owned(plan.assignment_id)
        for key in plan.redis_keys:
            await redis.delete(key)
        return True

    audit_module.execute_cleanup = flaky_cleanup  # type: ignore[method-assign]
    residue = await audit_module.detect_cleanup_residue(
        plan,
        postgres=postgres,
        redis=redis,
    )
    assert residue is True


@pytest.mark.asyncio
async def test_exact_cleanup_success_clears_owned_state(audit_module) -> None:
    redis = FakeRedis()
    postgres = FakePostgres()
    postgres.seed_assignment(_owned_assignment())
    postgres.seed_related_rows(ASSIGNMENT_ID)
    for job_id in JOB_IDS:
        redis.seed_job(job_id)
    owned_lock = f"algorithm:expectation_lock:{ASSIGNMENT_ID}:cache-1"
    redis.seed_key(owned_lock)

    plan = audit_module.build_cleanup_plan(
        run_id=RUN_ID,
        assignment=_owned_assignment(),
        job_ids=JOB_IDS,
        expected_owner_id=OWNER_ID,
    )
    residue = await audit_module.execute_cleanup(
        plan,
        postgres=postgres,
        redis=redis,
        expected_owner_id=OWNER_ID,
    )
    leftover = await audit_module.detect_cleanup_residue(plan, postgres=postgres, redis=redis)

    assert residue is False
    assert leftover is False
    assert postgres.tables["assignments"] == []
    assert owned_lock not in redis.keys
    assert all(f"analysis_job:{job_id}" not in redis.keys for job_id in JOB_IDS)


@pytest.mark.asyncio
async def test_audit_browser_run_builds_complete_ledger(audit_module, tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_valid_evidence_payload()), encoding="utf-8")
    redis = FakeRedis()
    postgres = FakePostgres()
    postgres.seed_assignment(_owned_assignment())
    for job_id in JOB_IDS:
        redis.seed_job(job_id)

    ledger = await audit_module.audit_browser_run(
        evidence_path,
        cleanup=False,
        expected_owner_id=OWNER_ID,
        postgres=postgres,
        redis=redis,
        provider="ollama",
        model="qwen2.5:7b",
    )

    assert isinstance(ledger, Phase4AReleaseLedger)
    assert {check.name for check in ledger.checks} == set(REQUIRED_CHECKS)
    agent_check = next(check for check in ledger.checks if check.name == "AGENT_CONTRACT_FAILED")
    assert agent_check.safe_value is False
    assert agent_check.passed is True


def test_safe_ledger_lines_never_emit_job_payload(audit_module) -> None:
    ledger = Phase4AReleaseLedger(
        run_id=RUN_ID,
        provider="ollama",
        model="qwen2.5:7b",
        checks=tuple(
            Phase4ACheck(
                name=name,
                safe_value=False if name.endswith("FAILED") else True,
                passed=True,
            )
            for name in REQUIRED_CHECKS
        ),
    )
    text = "\n".join(audit_module.safe_ledger_lines(ledger))
    assert "private_result" not in text
    assert "student_result" not in text
