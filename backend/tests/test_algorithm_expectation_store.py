"""RED-phase tests for algorithm expectation persistence (demo and PostgreSQL adapters)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import pytest

from backend.algorithm_analysis.contracts import ComplexityEstimate
from backend.algorithm_expectations.cache import AlgorithmExpectationLeaseLost
from backend.algorithm_expectations.contracts import AlgorithmExpectation
from backend.algorithm_expectations.store import (
    DemoAlgorithmExpectationStore,
    PostgresAlgorithmExpectationStore,
)


def _complexity() -> ComplexityEstimate:
    return ComplexityEstimate(
        expression="O(n log n)",
        family="single_variable",
        rank=3,
        confidence=0.85,
        source="llm",
        evidence_lines=(10, 20),
    )


def _expectation(
    *,
    expectation_id: str = "exp-1",
    assignment_id: str = "assignment-1",
    cache_key: str = "a" * 64,
    version: int = 1,
    active: bool = True,
) -> AlgorithmExpectation:
    return AlgorithmExpectation(
        id=expectation_id,
        assignment_id=assignment_id,
        cache_key=cache_key,
        version=version,
        expected_complexity=_complexity(),
        expected_approach="binary search",
        algorithm_families=("divide_and_conquer", "search"),
        confidence=0.9,
        extractor_provider="ollama",
        extractor_model="qwen2.5:7b",
        verifier_provider="ollama",
        verifier_model="qwen2.5:7b",
        schema_version="algorithm-expectation-v1",
        extractor_prompt_version="algorithm-extractor-v1",
        verifier_prompt_version="algorithm-verifier-v1",
        verification_status="verified",
        verification_reason="",
        active=active,
    )


def _make_demo_store() -> DemoAlgorithmExpectationStore:
    return DemoAlgorithmExpectationStore({"algorithm_expectations": []})


# --- DemoAlgorithmExpectationStore tests ---


@pytest.mark.asyncio
async def test_demo_store_insert_then_find_by_cache_key() -> None:
    store = _make_demo_store()
    expectation = _expectation(cache_key="b" * 64)

    inserted = await store.insert_verified(expectation)
    assert inserted == expectation

    found = await store.find_by_cache_key(expectation.assignment_id, expectation.cache_key)
    assert found == expectation
    assert await store.find_by_cache_key(expectation.assignment_id, "c" * 64) is None


@pytest.mark.asyncio
async def test_demo_store_insert_assigns_monotonic_version() -> None:
    store = _make_demo_store()
    assignment_id = "assignment-versioned"

    first = await store.insert_verified(
        _expectation(
            expectation_id="exp-v1",
            assignment_id=assignment_id,
            cache_key="d" * 64,
            version=1,
        )
    )
    second = await store.insert_verified(
        _expectation(
            expectation_id="exp-v2",
            assignment_id=assignment_id,
            cache_key="e" * 64,
            version=1,
        )
    )

    assert first.version == 1
    assert second.version == first.version + 1


@pytest.mark.asyncio
async def test_demo_store_insert_duplicate_cache_key_returns_existing_immutable_winner() -> None:
    store = _make_demo_store()
    assignment_id = "assignment-race"
    cache_key = "f" * 64

    first = await store.insert_verified(
        _expectation(expectation_id="exp-winner", assignment_id=assignment_id, cache_key=cache_key)
    )
    duplicate_attempt = _expectation(
        expectation_id="exp-loser",
        assignment_id=assignment_id,
        cache_key=cache_key,
        version=99,
    )
    second = await store.insert_verified(duplicate_attempt)

    assert second == first
    assert second.id == first.id
    assert second.version == first.version

    all_for_key = [
        row
        for row in store._container["algorithm_expectations"]  # type: ignore[attr-defined]
        if row["assignment_id"] == assignment_id and row["cache_key"] == cache_key
    ]
    assert len(all_for_key) == 1


@pytest.mark.asyncio
async def test_demo_store_one_active_row_per_assignment() -> None:
    store = _make_demo_store()
    assignment_id = "assignment-one-active"

    first = await store.insert_verified(
        _expectation(
            expectation_id="exp-active-1",
            assignment_id=assignment_id,
            cache_key="0" * 64,
        )
    )
    second = await store.insert_verified(
        _expectation(
            expectation_id="exp-active-2",
            assignment_id=assignment_id,
            cache_key="1" * 64,
        )
    )

    active = await store.get_active(assignment_id)
    assert active == second
    assert active is not None
    assert active.id == second.id

    first_by_id = await store.get_by_id(first.id)
    assert first_by_id is not None
    assert first_by_id.active is False


@pytest.mark.asyncio
async def test_demo_store_deactivate_marks_active_false() -> None:
    store = _make_demo_store()
    expectation = await store.insert_verified(_expectation())

    deactivated_count = await store.deactivate_assignment(
        expectation.assignment_id, reason="test"
    )
    assert deactivated_count == 1
    assert await store.get_active(expectation.assignment_id) is None

    by_id = await store.get_by_id(expectation.id)
    assert by_id is not None
    assert by_id.active is False


@pytest.mark.asyncio
async def test_demo_store_reactivate_exact() -> None:
    store = _make_demo_store()
    assignment_id = "assignment-reactivate"
    cache_key = "2" * 64
    stale_cache_key = "3" * 64

    inserted = await store.insert_verified(
        _expectation(
            expectation_id="exp-reactivate",
            assignment_id=assignment_id,
            cache_key=cache_key,
        )
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
async def test_demo_store_lease_loss_before_insert_does_not_persist() -> None:
    store = _make_demo_store()
    expectation = _expectation(cache_key="4" * 64)

    def _lose_lease() -> None:
        raise AlgorithmExpectationLeaseLost("lease lost")

    with pytest.raises(AlgorithmExpectationLeaseLost):
        await store.insert_verified(expectation, lease_check=_lose_lease)

    assert store._container["algorithm_expectations"] == []  # type: ignore[attr-defined]
    assert await store.find_by_cache_key(expectation.assignment_id, expectation.cache_key) is None


@pytest.mark.asyncio
async def test_demo_store_serializes_complexity_and_families() -> None:
    store = _make_demo_store()
    expectation = await store.insert_verified(_expectation(cache_key="5" * 64))

    row = store._container["algorithm_expectations"][0]  # type: ignore[attr-defined]
    assert isinstance(row["complexity"], dict)
    assert row["complexity"]["expression"] == "O(n log n)"
    assert row["algorithm_families"] == ["divide_and_conquer", "search"]

    round_trip = await store.get_by_id(expectation.id)
    assert round_trip is not None
    assert round_trip.expected_complexity == _complexity()
    assert round_trip.algorithm_families == ("divide_and_conquer", "search")


@pytest.mark.asyncio
async def test_demo_store_get_by_id_returns_none_for_unknown_id() -> None:
    store = _make_demo_store()
    assert await store.get_by_id("missing-exp-id") is None


# --- PostgresAlgorithmExpectationStore tests (fake asyncpg) ---


@dataclass
class _PostgresLedger:
    rows: list[dict[str, Any]] = field(default_factory=list)
    next_version_by_assignment: dict[str, int] = field(default_factory=dict)
    insert_attempts: int = 0
    fail_next_insert_with_unique_violation: bool = False
    lease_check_called_in_transaction: bool = False


class FakePostgresConnection:
    def __init__(self, ledger: _PostgresLedger) -> None:
        self.ledger = ledger
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self._in_transaction = False
        self._transaction_rolled_back = False

    @asynccontextmanager
    async def transaction(self):
        self._in_transaction = True
        self._transaction_rolled_back = False
        try:
            yield self
        except Exception:
            self._transaction_rolled_back = True
            raise
        finally:
            self._in_transaction = False

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args or None))
        normalized = " ".join(query.lower().split())

        if "pg_advisory_xact_lock" in normalized:
            return "SELECT 1"

        if normalized.startswith("update algorithm_expectations set active = false"):
            assignment_id = args[1] if len(args) > 1 else args[0]
            count = 0
            for row in self.ledger.rows:
                if row["assignment_id"] == assignment_id and row.get("active"):
                    row["active"] = False
                    row["deactivated_at"] = "2026-07-11T12:00:00Z"
                    count += 1
            return f"UPDATE {count}"

        if normalized.startswith("insert into algorithm_expectations"):
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
                "complexity": args[4],
                "expected_approach": args[5],
                "algorithm_families": args[6],
                "confidence": args[7],
                "extractor_provider": args[8],
                "extractor_model": args[9],
                "verifier_provider": args[10],
                "verifier_model": args[11],
                "schema_version": args[12],
                "extractor_prompt_version": args[13],
                "verifier_prompt_version": args[14],
                "assignment_hash": args[15] if len(args) > 15 else "",
                "rubric_hash": args[16] if len(args) > 16 else "",
                "verification_status": args[17] if len(args) > 17 else "verified",
                "verification_reason": args[18] if len(args) > 18 else "",
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

        if "from algorithm_expectations" in normalized and "cache_key" in normalized:
            assignment_id = str(args[0])
            cache_key = str(args[1])
            for row in self.ledger.rows:
                if row["assignment_id"] == assignment_id and row["cache_key"] == cache_key:
                    return dict(row)
            return None

        if "from algorithm_expectations" in normalized and "active = true" in normalized:
            assignment_id = str(args[0])
            for row in self.ledger.rows:
                if row["assignment_id"] == assignment_id and row.get("active"):
                    return dict(row)
            return None

        if "from algorithm_expectations" in normalized and "where id" in normalized:
            expectation_id = str(args[0])
            for row in self.ledger.rows:
                if row["id"] == expectation_id:
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


class FakePostgresPool:
    def __init__(self, ledger: _PostgresLedger) -> None:
        self.ledger = ledger
        self.connection = FakePostgresConnection(ledger)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.asyncio
async def test_postgres_store_insert_verified_uses_advisory_lock_and_monotonic_version() -> None:
    ledger = _PostgresLedger()
    pool = FakePostgresPool(ledger)
    store = PostgresAlgorithmExpectationStore(pool)

    first = await store.insert_verified(
        _expectation(
            expectation_id="pg-exp-1",
            assignment_id="assignment-pg",
            cache_key="6" * 64,
        )
    )
    second = await store.insert_verified(
        _expectation(
            expectation_id="pg-exp-2",
            assignment_id="assignment-pg",
            cache_key="7" * 64,
        )
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
    store = PostgresAlgorithmExpectationStore(pool)
    assignment_id = "assignment-race-pg"
    cache_key = "8" * 64

    winner = _expectation(
        expectation_id="pg-winner", assignment_id=assignment_id, cache_key=cache_key
    )
    committed = await store.insert_verified(winner)

    ledger.fail_next_insert_with_unique_violation = True
    loser = _expectation(
        expectation_id="pg-loser", assignment_id=assignment_id, cache_key=cache_key, version=99
    )
    recovered = await store.insert_verified(loser)

    assert recovered.id == committed.id
    assert recovered.version == committed.version
    assert recovered.cache_key == cache_key
    assert ledger.insert_attempts == 2
    assert len([row for row in ledger.rows if row["cache_key"] == cache_key]) == 1


@pytest.mark.asyncio
async def test_postgres_store_lease_loss_rolls_back_transaction() -> None:
    ledger = _PostgresLedger()
    pool = FakePostgresPool(ledger)
    store = PostgresAlgorithmExpectationStore(pool)
    expectation = _expectation(cache_key="9" * 64)

    def _lose_lease() -> None:
        ledger.lease_check_called_in_transaction = pool.connection._in_transaction
        raise AlgorithmExpectationLeaseLost("lease lost")

    with pytest.raises(AlgorithmExpectationLeaseLost):
        await store.insert_verified(expectation, lease_check=_lose_lease)

    assert ledger.lease_check_called_in_transaction is True
    assert ledger.rows == []
    assert await store.find_by_cache_key(expectation.assignment_id, expectation.cache_key) is None


@pytest.mark.asyncio
async def test_postgres_store_deactivate_and_get_active_none() -> None:
    ledger = _PostgresLedger()
    pool = FakePostgresPool(ledger)
    store = PostgresAlgorithmExpectationStore(pool)

    inserted = await store.insert_verified(
        _expectation(expectation_id="pg-deact", cache_key="a1" * 32)
    )
    assert await store.get_active(inserted.assignment_id) is not None

    count = await store.deactivate_assignment(inserted.assignment_id, reason="test")
    assert count == 1
    assert await store.get_active(inserted.assignment_id) is None


@pytest.mark.asyncio
async def test_postgres_store_reactivate_exact_returns_none_for_missing_key() -> None:
    ledger = _PostgresLedger()
    pool = FakePostgresPool(ledger)
    store = PostgresAlgorithmExpectationStore(pool)

    assert await store.reactivate_exact("assignment-missing", "b2" * 32) is None
