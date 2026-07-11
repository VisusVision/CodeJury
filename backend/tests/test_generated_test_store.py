"""RED-phase tests for generated-test set persistence (demo and PostgreSQL adapters)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import pytest

from backend.testing.contracts import FormalTestCase, GeneratedTestSet
from backend.testing.store import DemoGeneratedTestSetStore, PostgresGeneratedTestSetStore


def _minimal_case(case_id: str = "case-1") -> FormalTestCase:
    return FormalTestCase(
        id=case_id,
        name="basic",
        source="auto_generated",
        oracle="llm_verified",
    )


def _test_set(
    *,
    set_id: str = "set-1",
    assignment_id: str = "assignment-1",
    cache_key: str = "a" * 64,
    version: int = 1,
    active: bool = True,
    difficulty: str = "medium",
) -> GeneratedTestSet:
    return GeneratedTestSet(
        id=set_id,
        assignment_id=assignment_id,
        cache_key=cache_key,
        version=version,
        difficulty=difficulty,  # type: ignore[arg-type]
        cases=(_minimal_case(),),
        provider="ollama",
        model="qwen2.5:7b",
        schema_version="test-set-v1",
        prompt_version="test-generator-v1",
        active=active,
    )


def _make_demo_store() -> DemoGeneratedTestSetStore:
    """Hermetic demo store backed by a fresh in-memory container."""
    return DemoGeneratedTestSetStore({"generated_test_sets": []})


# --- DemoGeneratedTestSetStore tests ---


@pytest.mark.asyncio
async def test_demo_store_insert_then_find_by_cache_key() -> None:
    store = _make_demo_store()
    test_set = _test_set(cache_key="b" * 64)

    inserted = await store.insert_verified_set(test_set)
    assert inserted == test_set

    found = await store.find_by_cache_key(test_set.assignment_id, test_set.cache_key)
    assert found == test_set
    assert await store.find_by_cache_key(test_set.assignment_id, "c" * 64) is None


@pytest.mark.asyncio
async def test_demo_store_insert_assigns_monotonic_version() -> None:
    store = _make_demo_store()
    assignment_id = "assignment-versioned"

    first = await store.insert_verified_set(
        _test_set(set_id="set-v1", assignment_id=assignment_id, cache_key="d" * 64, version=1)
    )
    second = await store.insert_verified_set(
        _test_set(set_id="set-v2", assignment_id=assignment_id, cache_key="e" * 64, version=1)
    )

    assert first.version == 1
    assert second.version == first.version + 1


@pytest.mark.asyncio
async def test_demo_store_insert_duplicate_cache_key_returns_existing_immutable_winner() -> None:
    store = _make_demo_store()
    assignment_id = "assignment-race"
    cache_key = "f" * 64

    first = await store.insert_verified_set(
        _test_set(set_id="set-winner", assignment_id=assignment_id, cache_key=cache_key)
    )
    duplicate_attempt = _test_set(
        set_id="set-loser",
        assignment_id=assignment_id,
        cache_key=cache_key,
        version=99,
    )
    second = await store.insert_verified_set(duplicate_attempt)

    assert second == first
    assert second.id == first.id
    assert second.version == first.version

    all_for_key = [
        row
        for row in store._container["generated_test_sets"]  # type: ignore[attr-defined]
        if row["assignment_id"] == assignment_id and row["cache_key"] == cache_key
    ]
    assert len(all_for_key) == 1


@pytest.mark.asyncio
async def test_demo_store_deactivate_marks_active_false() -> None:
    store = _make_demo_store()
    test_set = await store.insert_verified_set(_test_set())

    deactivated_count = await store.deactivate_assignment(test_set.assignment_id, reason="test")
    assert deactivated_count == 1
    assert await store.get_active(test_set.assignment_id) is None

    by_id = await store.get_by_id(test_set.id)
    assert by_id is not None
    assert by_id.active is False

    by_cache_key = await store.find_by_cache_key(test_set.assignment_id, test_set.cache_key)
    assert by_cache_key is not None
    assert by_cache_key.active is False


@pytest.mark.asyncio
async def test_demo_store_reactivate_exact_only_when_no_faculty_and_no_active() -> None:
    store = _make_demo_store()
    assignment_id = "assignment-reactivate"
    cache_key = "0" * 64
    stale_cache_key = "1" * 64

    inserted = await store.insert_verified_set(
        _test_set(set_id="set-reactivate", assignment_id=assignment_id, cache_key=cache_key)
    )
    await store.deactivate_assignment(assignment_id, reason="rubric changed")
    assert await store.get_active(assignment_id) is None

    reactivated = await store.reactivate_exact(assignment_id, cache_key)
    assert reactivated is not None
    assert reactivated.id == inserted.id
    assert reactivated.active is True
    assert await store.get_active(assignment_id) == reactivated

    missing = await store.reactivate_exact(assignment_id, stale_cache_key)
    assert missing is None
    assert await store.get_active(assignment_id) == reactivated


@pytest.mark.asyncio
async def test_demo_store_get_by_id_returns_none_for_unknown_id() -> None:
    store = _make_demo_store()
    assert await store.get_by_id("missing-set-id") is None


# --- PostgresGeneratedTestSetStore tests (fake asyncpg) ---


@dataclass
class _PostgresLedger:
  rows: list[dict[str, Any]] = field(default_factory=list)
  next_version_by_assignment: dict[str, int] = field(default_factory=dict)
  insert_attempts: int = 0
  fail_next_insert_with_unique_violation: bool = False


class FakePostgresConnection:
    def __init__(self, ledger: _PostgresLedger) -> None:
        self.ledger = ledger
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self._in_transaction = False

    @asynccontextmanager
    async def transaction(self):
        self._in_transaction = True
        try:
            yield self
        finally:
            self._in_transaction = False

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args or None))
        normalized = " ".join(query.lower().split())

        if "pg_advisory_xact_lock" in normalized:
            return "SELECT 1"

        if normalized.startswith("update generated_test_sets set active = false"):
            assignment_id = args[1] if len(args) > 1 else args[0]
            count = 0
            for row in self.ledger.rows:
                if row["assignment_id"] == assignment_id and row.get("active"):
                    row["active"] = False
                    row["deactivated_at"] = "2026-07-11T12:00:00Z"
                    count += 1
            return f"UPDATE {count}"

        if normalized.startswith("insert into generated_test_sets"):
            self.ledger.insert_attempts += 1
            if self.ledger.fail_next_insert_with_unique_violation:
                self.ledger.fail_next_insert_with_unique_violation = False
                raise asyncpg.UniqueViolationError("duplicate key value violates unique constraint")

            assignment_id = str(args[1])
            cache_key = str(args[2])
            for existing in self.ledger.rows:
                if existing["assignment_id"] == assignment_id and existing["cache_key"] == cache_key:
                    raise asyncpg.UniqueViolationError("duplicate key value violates unique constraint")

            current_max = max(
                (row["version"] for row in self.ledger.rows if row["assignment_id"] == assignment_id),
                default=0,
            )
            version = current_max + 1
            row = {
                "id": str(args[0]),
                "assignment_id": assignment_id,
                "cache_key": cache_key,
                "version": version,
                "difficulty": args[4],
                "cases": args[5],
                "provider": args[6],
                "model": args[7],
                "schema_version": args[8],
                "prompt_version": args[9],
                "assignment_hash": args[10] if len(args) > 10 else "",
                "rubric_hash": args[11] if len(args) > 11 else "",
                "oracle_validation": args[12] if len(args) > 12 else [],
                "active": True,
                "created_at": "2026-07-11T12:00:00Z",
                "deactivated_at": None,
            }
            for prior in self.ledger.rows:
                if prior["assignment_id"] == assignment_id and prior.get("active"):
                    prior["active"] = False
                    prior["deactivated_at"] = "2026-07-11T12:00:00Z"
            self.ledger.rows.append(row)
            self.ledger.next_version_by_assignment[assignment_id] = version
            return "INSERT 1"

        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.executed.append((query, args or None))
        normalized = " ".join(query.lower().split())

        if "from generated_test_sets" in normalized and "cache_key" in normalized:
            assignment_id = str(args[0])
            cache_key = str(args[1])
            for row in self.ledger.rows:
                if row["assignment_id"] == assignment_id and row["cache_key"] == cache_key:
                    return dict(row)
            return None

        if "from generated_test_sets" in normalized and "active = true" in normalized:
            assignment_id = str(args[0])
            for row in self.ledger.rows:
                if row["assignment_id"] == assignment_id and row.get("active"):
                    return dict(row)
            return None

        if "from generated_test_sets" in normalized and "where id" in normalized:
            set_id = str(args[0])
            for row in self.ledger.rows:
                if row["id"] == set_id:
                    return dict(row)
            return None

        if "coalesce(max(version)" in normalized:
            assignment_id = str(args[0])
            current_max = max(
                (row["version"] for row in self.ledger.rows if row["assignment_id"] == assignment_id),
                default=0,
            )
            return {"next_version": current_max + 1}

        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        row = await self.fetchrow(query, *args)
        if row is None:
            return None
        if len(row) == 1:
            return next(iter(row.values()))
        return row.get("next_version")


class FakePostgresPool:
    def __init__(self, ledger: _PostgresLedger) -> None:
        self.ledger = ledger
        self.connection = FakePostgresConnection(ledger)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def _row_to_generated_test_set(row: dict[str, Any]) -> GeneratedTestSet:
    cases = row["cases"]
    if cases and isinstance(cases[0], dict):
        cases = tuple(FormalTestCase.model_validate(case) for case in cases)
    return GeneratedTestSet(
        id=row["id"],
        assignment_id=row["assignment_id"],
        cache_key=row["cache_key"],
        version=row["version"],
        difficulty=row["difficulty"],
        cases=cases,
        provider=row["provider"],
        model=row["model"],
        schema_version=row["schema_version"],
        prompt_version=row["prompt_version"],
        assignment_hash=row.get("assignment_hash", ""),
        rubric_hash=row.get("rubric_hash", ""),
        oracle_validation=tuple(row.get("oracle_validation") or ()),
        active=row.get("active", True),
        created_at=row.get("created_at", ""),
        deactivated_at=row.get("deactivated_at"),
    )


@pytest.mark.asyncio
async def test_postgres_store_insert_verified_set_uses_advisory_lock_and_monotonic_version() -> None:
    ledger = _PostgresLedger()
    pool = FakePostgresPool(ledger)
    store = PostgresGeneratedTestSetStore(pool)

    first = await store.insert_verified_set(
        _test_set(set_id="pg-set-1", assignment_id="assignment-pg", cache_key="2" * 64)
    )
    second = await store.insert_verified_set(
        _test_set(set_id="pg-set-2", assignment_id="assignment-pg", cache_key="3" * 64)
    )

    executed_sql = "\n".join(query for query, _ in pool.connection.executed)
    assert "pg_advisory_xact_lock" in executed_sql.lower()
    assert first.version == 1
    assert second.version == 2
    assert ledger.next_version_by_assignment["assignment-pg"] == 2


@pytest.mark.asyncio
async def test_postgres_store_insert_handles_unique_violation_by_rereading_winner() -> None:
    ledger = _PostgresLedger()
    pool = FakePostgresPool(ledger)
    store = PostgresGeneratedTestSetStore(pool)
    assignment_id = "assignment-race-pg"
    cache_key = "4" * 64

    winner = _test_set(set_id="pg-winner", assignment_id=assignment_id, cache_key=cache_key)
    committed = await store.insert_verified_set(winner)

    ledger.fail_next_insert_with_unique_violation = True
    loser = _test_set(set_id="pg-loser", assignment_id=assignment_id, cache_key=cache_key, version=99)
    recovered = await store.insert_verified_set(loser)

    assert recovered.id == committed.id
    assert recovered.version == committed.version
    assert recovered.cache_key == cache_key
    assert ledger.insert_attempts == 2
    assert len([row for row in ledger.rows if row["cache_key"] == cache_key]) == 1


@pytest.mark.asyncio
async def test_postgres_store_deactivate_and_get_active_none() -> None:
    ledger = _PostgresLedger()
    pool = FakePostgresPool(ledger)
    store = PostgresGeneratedTestSetStore(pool)

    inserted = await store.insert_verified_set(_test_set(set_id="pg-deact", cache_key="5" * 64))
    assert await store.get_active(inserted.assignment_id) is not None

    count = await store.deactivate_assignment(inserted.assignment_id, reason="test")
    assert count == 1
    assert await store.get_active(inserted.assignment_id) is None


@pytest.mark.asyncio
async def test_postgres_store_reactivate_exact_returns_none_for_missing_key() -> None:
    ledger = _PostgresLedger()
    pool = FakePostgresPool(ledger)
    store = PostgresGeneratedTestSetStore(pool)

    assert await store.reactivate_exact("assignment-missing", "6" * 64) is None
