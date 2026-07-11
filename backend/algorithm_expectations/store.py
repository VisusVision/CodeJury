from __future__ import annotations

import json
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, Protocol

import asyncpg

from backend.algorithm_analysis.contracts import ComplexityEstimate
from backend.algorithm_expectations.contracts import AlgorithmExpectation


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _stringify_timestamp(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_complexity(complexity: ComplexityEstimate | None) -> dict[str, Any] | None:
    if complexity is None:
        return None
    return complexity.model_dump()


def _serialize_algorithm_families(families: tuple[str, ...]) -> list[str]:
    return list(families)


def _parse_complexity(raw: Any) -> ComplexityEstimate | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = json.loads(raw) if raw else None
    if not raw:
        return None
    if isinstance(raw, ComplexityEstimate):
        return raw
    return ComplexityEstimate.model_validate(raw)


def _parse_algorithm_families(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = json.loads(raw) if raw else []
    raw = raw or []
    return tuple(str(item) for item in raw)


def _row_to_algorithm_expectation(row: dict[str, Any]) -> AlgorithmExpectation:
    return AlgorithmExpectation(
        id=str(row["id"]),
        assignment_id=str(row["assignment_id"]),
        cache_key=row["cache_key"],
        version=row["version"],
        expected_complexity=_parse_complexity(row.get("complexity")),
        expected_approach=row.get("expected_approach", ""),
        algorithm_families=_parse_algorithm_families(row.get("algorithm_families")),
        confidence=row.get("confidence", 0.0),
        extractor_provider=row["extractor_provider"],
        extractor_model=row["extractor_model"],
        verifier_provider=row["verifier_provider"],
        verifier_model=row["verifier_model"],
        schema_version=row["schema_version"],
        extractor_prompt_version=row["extractor_prompt_version"],
        verifier_prompt_version=row["verifier_prompt_version"],
        assignment_hash=row.get("assignment_hash", ""),
        rubric_hash=row.get("rubric_hash", ""),
        verification_status=row["verification_status"],
        verification_reason=row.get("verification_reason", ""),
        active=row.get("active", True),
        created_at=_stringify_timestamp(row.get("created_at", "")),
        deactivated_at=_stringify_timestamp(row.get("deactivated_at")),
    )


def _expectation_to_row(
    expectation: AlgorithmExpectation, *, version: int, active: bool
) -> dict[str, Any]:
    return {
        "id": expectation.id,
        "assignment_id": expectation.assignment_id,
        "cache_key": expectation.cache_key,
        "version": version,
        "complexity": _serialize_complexity(expectation.expected_complexity),
        "expected_approach": expectation.expected_approach,
        "algorithm_families": _serialize_algorithm_families(expectation.algorithm_families),
        "confidence": expectation.confidence,
        "extractor_provider": expectation.extractor_provider,
        "extractor_model": expectation.extractor_model,
        "verifier_provider": expectation.verifier_provider,
        "verifier_model": expectation.verifier_model,
        "schema_version": expectation.schema_version,
        "extractor_prompt_version": expectation.extractor_prompt_version,
        "verifier_prompt_version": expectation.verifier_prompt_version,
        "assignment_hash": expectation.assignment_hash,
        "rubric_hash": expectation.rubric_hash,
        "verification_status": expectation.verification_status,
        "verification_reason": expectation.verification_reason,
        "active": active,
        "created_at": expectation.created_at,
        "deactivated_at": None,
    }


class AlgorithmExpectationStore(Protocol):
    async def find_by_cache_key(
        self, assignment_id: str, cache_key: str
    ) -> AlgorithmExpectation | None: ...

    async def insert_verified(
        self,
        expectation: AlgorithmExpectation,
        *,
        lease_check: Callable[[], None] | None = None,
    ) -> AlgorithmExpectation: ...

    async def deactivate_assignment(self, assignment_id: str, *, reason: str) -> int: ...

    async def reactivate_exact(
        self, assignment_id: str, cache_key: str
    ) -> AlgorithmExpectation | None: ...

    async def get_active(self, assignment_id: str) -> AlgorithmExpectation | None: ...

    async def get_by_id(self, expectation_id: str) -> AlgorithmExpectation | None: ...


class DemoAlgorithmExpectationStore:
    def __init__(self, container: dict[str, list[dict[str, Any]]]) -> None:
        self._container = container

    async def find_by_cache_key(
        self, assignment_id: str, cache_key: str
    ) -> AlgorithmExpectation | None:
        for row in self._container["algorithm_expectations"]:
            if row["assignment_id"] == assignment_id and row["cache_key"] == cache_key:
                return _row_to_algorithm_expectation(row)
        return None

    async def insert_verified(
        self,
        expectation: AlgorithmExpectation,
        *,
        lease_check: Callable[[], None] | None = None,
    ) -> AlgorithmExpectation:
        existing = await self.find_by_cache_key(
            expectation.assignment_id, expectation.cache_key
        )
        if existing is not None:
            return existing

        version = (
            max(
                (
                    row["version"]
                    for row in self._container["algorithm_expectations"]
                    if row["assignment_id"] == expectation.assignment_id
                ),
                default=0,
            )
            + 1
        )

        now = _utc_now_iso()
        deactivated: list[dict[str, Any]] = []
        for row in self._container["algorithm_expectations"]:
            if row["assignment_id"] == expectation.assignment_id and row.get("active"):
                deactivated.append(row)
                row["active"] = False
                row["deactivated_at"] = now

        try:
            if lease_check is not None:
                lease_check()
        except Exception:
            for row in deactivated:
                row["active"] = True
                row["deactivated_at"] = None
            raise

        new_row = _expectation_to_row(expectation, version=version, active=True)
        self._container["algorithm_expectations"].append(new_row)
        return _row_to_algorithm_expectation(new_row)

    async def deactivate_assignment(self, assignment_id: str, *, reason: str) -> int:
        now = _utc_now_iso()
        count = 0
        for row in self._container["algorithm_expectations"]:
            if row["assignment_id"] == assignment_id and row.get("active"):
                row["active"] = False
                row["deactivated_at"] = now
                count += 1
        return count

    async def reactivate_exact(
        self, assignment_id: str, cache_key: str
    ) -> AlgorithmExpectation | None:
        target: dict[str, Any] | None = None
        for row in self._container["algorithm_expectations"]:
            if row["assignment_id"] == assignment_id and row["cache_key"] == cache_key:
                target = row
                break
        if target is None:
            return None

        for row in self._container["algorithm_expectations"]:
            if (
                row["assignment_id"] == assignment_id
                and row is not target
                and row.get("active")
            ):
                row["active"] = False
                row["deactivated_at"] = _utc_now_iso()

        target["active"] = True
        target["deactivated_at"] = None
        return _row_to_algorithm_expectation(target)

    async def get_active(self, assignment_id: str) -> AlgorithmExpectation | None:
        for row in self._container["algorithm_expectations"]:
            if row["assignment_id"] == assignment_id and row.get("active"):
                return _row_to_algorithm_expectation(row)
        return None

    async def get_by_id(self, expectation_id: str) -> AlgorithmExpectation | None:
        for row in self._container["algorithm_expectations"]:
            if row["id"] == expectation_id:
                return _row_to_algorithm_expectation(row)
        return None


class PostgresAlgorithmExpectationStore:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def find_by_cache_key(
        self, assignment_id: str, cache_key: str
    ) -> AlgorithmExpectation | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, assignment_id, cache_key, version, complexity,
                       expected_approach, algorithm_families, confidence,
                       extractor_provider, extractor_model, verifier_provider,
                       verifier_model, schema_version, extractor_prompt_version,
                       verifier_prompt_version, assignment_hash, rubric_hash,
                       verification_status, verification_reason,
                       active, created_at, deactivated_at
                FROM algorithm_expectations
                WHERE assignment_id = $1 AND cache_key = $2
                """,
                assignment_id,
                cache_key,
            )
        if row is None:
            return None
        return _row_to_algorithm_expectation(dict(row))

    async def insert_verified(
        self,
        expectation: AlgorithmExpectation,
        *,
        lease_check: Callable[[], None] | None = None,
    ) -> AlgorithmExpectation:
        version: int | None = None
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtext($1))",
                        expectation.assignment_id,
                    )

                    version_row = await conn.fetchrow(
                        """
                        SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                        FROM algorithm_expectations
                        WHERE assignment_id = $1
                        """,
                        expectation.assignment_id,
                    )
                    version = int(version_row["next_version"])

                    now = _utc_now_dt()
                    await conn.execute(
                        """
                        UPDATE algorithm_expectations SET active = false, deactivated_at = $1
                        WHERE assignment_id = $2 AND active = true
                        """,
                        now,
                        expectation.assignment_id,
                    )

                    if expectation.created_at:
                        try:
                            created_at = datetime.fromisoformat(expectation.created_at)
                        except (ValueError, TypeError):
                            created_at = now
                    else:
                        created_at = now

                    if lease_check is not None:
                        lease_check()

                    await conn.execute(
                        """
                        INSERT INTO algorithm_expectations (
                            id, assignment_id, cache_key, version, complexity,
                            expected_approach, algorithm_families, confidence,
                            extractor_provider, extractor_model, verifier_provider,
                            verifier_model, schema_version, extractor_prompt_version,
                            verifier_prompt_version, assignment_hash, rubric_hash,
                            verification_status, verification_reason, active, created_at
                        ) VALUES (
                            $1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8,
                            $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, true, $20
                        )
                        """,
                        expectation.id,
                        expectation.assignment_id,
                        expectation.cache_key,
                        version,
                        json.dumps(_serialize_complexity(expectation.expected_complexity)),
                        expectation.expected_approach,
                        json.dumps(
                            _serialize_algorithm_families(expectation.algorithm_families)
                        ),
                        expectation.confidence,
                        expectation.extractor_provider,
                        expectation.extractor_model,
                        expectation.verifier_provider,
                        expectation.verifier_model,
                        expectation.schema_version,
                        expectation.extractor_prompt_version,
                        expectation.verifier_prompt_version,
                        expectation.assignment_hash,
                        expectation.rubric_hash,
                        expectation.verification_status,
                        expectation.verification_reason,
                        created_at,
                    )
        except asyncpg.UniqueViolationError:
            winner = await self.find_by_cache_key(
                expectation.assignment_id, expectation.cache_key
            )
            if winner is None:
                raise
            return winner

        inserted = await self.find_by_cache_key(
            expectation.assignment_id, expectation.cache_key
        )
        if inserted is None:
            raise RuntimeError("inserted algorithm expectation could not be re-read")
        return inserted.model_copy(update={"version": version})

    async def deactivate_assignment(self, assignment_id: str, *, reason: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE algorithm_expectations SET active = false, deactivated_at = $1
                WHERE assignment_id = $2 AND active = true
                """,
                _utc_now_dt(),
                assignment_id,
            )
        if isinstance(result, str) and result.startswith("UPDATE "):
            try:
                return int(result.split()[1])
            except (IndexError, ValueError):
                pass
        return 0

    async def reactivate_exact(
        self, assignment_id: str, cache_key: str
    ) -> AlgorithmExpectation | None:
        existing = await self.find_by_cache_key(assignment_id, cache_key)
        if existing is None:
            return None

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE algorithm_expectations SET active = false, deactivated_at = $1
                WHERE assignment_id = $2 AND active = true
                """,
                _utc_now_dt(),
                assignment_id,
            )
            await conn.execute(
                """
                UPDATE algorithm_expectations SET active = true, deactivated_at = NULL
                WHERE assignment_id = $1 AND cache_key = $2
                """,
                assignment_id,
                cache_key,
            )

        reactivated = await self.find_by_cache_key(assignment_id, cache_key)
        if reactivated is None:
            return None
        return reactivated.model_copy(update={"active": True, "deactivated_at": None})

    async def get_active(self, assignment_id: str) -> AlgorithmExpectation | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM algorithm_expectations
                WHERE assignment_id = $1 AND active = true
                """,
                assignment_id,
            )
        if row is None:
            return None
        return _row_to_algorithm_expectation(dict(row))

    async def get_by_id(self, expectation_id: str) -> AlgorithmExpectation | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM algorithm_expectations
                WHERE id = $1
                """,
                expectation_id,
            )
        if row is None:
            return None
        return _row_to_algorithm_expectation(dict(row))
