from __future__ import annotations

import json
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, Protocol

import asyncpg

from backend.testing.contracts import (
    FormalTestCase,
    GeneratedTestSet,
    OracleValidation,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _stringify_timestamp(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_cases(cases: tuple[FormalTestCase, ...]) -> list[dict[str, Any]]:
    return [case.model_dump() for case in cases]


def _serialize_oracle_validation(
    oracle_validation: tuple[OracleValidation, ...],
) -> list[dict[str, Any]]:
    return [item.model_dump() for item in oracle_validation]


def _row_to_generated_test_set(row: dict[str, Any]) -> GeneratedTestSet:
    raw_cases = row["cases"]
    if isinstance(raw_cases, str):
        raw_cases = json.loads(raw_cases) if raw_cases else []
    raw_cases = raw_cases or []
    cases = tuple(
        FormalTestCase.model_validate(c) if isinstance(c, dict) else c
        for c in raw_cases
    )

    raw_oracle_validation = row.get("oracle_validation") or []
    if isinstance(raw_oracle_validation, str):
        raw_oracle_validation = (
            json.loads(raw_oracle_validation) if raw_oracle_validation else []
        )
    oracle_validation = tuple(
        OracleValidation.model_validate(item) if isinstance(item, dict) else item
        for item in raw_oracle_validation
    )

    return GeneratedTestSet(
        id=str(row["id"]),
        assignment_id=str(row["assignment_id"]),
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
        oracle_validation=oracle_validation,
        active=row.get("active", True),
        created_at=_stringify_timestamp(row.get("created_at", "")),
        deactivated_at=_stringify_timestamp(row.get("deactivated_at")),
    )


def _test_set_to_row(test_set: GeneratedTestSet, *, version: int, active: bool) -> dict[str, Any]:
    return {
        "id": test_set.id,
        "assignment_id": test_set.assignment_id,
        "cache_key": test_set.cache_key,
        "version": version,
        "difficulty": test_set.difficulty,
        "cases": _serialize_cases(test_set.cases),
        "provider": test_set.provider,
        "model": test_set.model,
        "schema_version": test_set.schema_version,
        "prompt_version": test_set.prompt_version,
        "assignment_hash": test_set.assignment_hash,
        "rubric_hash": test_set.rubric_hash,
        "oracle_validation": _serialize_oracle_validation(test_set.oracle_validation),
        "active": active,
        "created_at": test_set.created_at,
        "deactivated_at": None,
    }


class GeneratedTestSetStore(Protocol):
    async def find_by_cache_key(
        self, assignment_id: str, cache_key: str
    ) -> GeneratedTestSet | None: ...

    async def insert_verified_set(
        self,
        test_set: GeneratedTestSet,
        *,
        lease_check: Callable[[], None] | None = None,
    ) -> GeneratedTestSet: ...

    async def deactivate_assignment(self, assignment_id: str, *, reason: str) -> int: ...

    async def reactivate_exact(
        self, assignment_id: str, cache_key: str
    ) -> GeneratedTestSet | None: ...

    async def get_active(self, assignment_id: str) -> GeneratedTestSet | None: ...

    async def get_by_id(self, test_set_id: str) -> GeneratedTestSet | None: ...


class DemoGeneratedTestSetStore:
    def __init__(self, container: dict[str, list[dict[str, Any]]]) -> None:
        self._container = container

    async def find_by_cache_key(
        self, assignment_id: str, cache_key: str
    ) -> GeneratedTestSet | None:
        for row in self._container["generated_test_sets"]:
            if row["assignment_id"] == assignment_id and row["cache_key"] == cache_key:
                return _row_to_generated_test_set(row)
        return None

    async def insert_verified_set(
        self,
        test_set: GeneratedTestSet,
        *,
        lease_check: Callable[[], None] | None = None,
    ) -> GeneratedTestSet:
        existing = await self.find_by_cache_key(test_set.assignment_id, test_set.cache_key)
        if existing is not None:
            return existing

        if lease_check is not None:
            lease_check()

        version = (
            max(
                (
                    row["version"]
                    for row in self._container["generated_test_sets"]
                    if row["assignment_id"] == test_set.assignment_id
                ),
                default=0,
            )
            + 1
        )

        now = _utc_now_iso()
        for row in self._container["generated_test_sets"]:
            if row["assignment_id"] == test_set.assignment_id and row.get("active"):
                row["active"] = False
                row["deactivated_at"] = now

        new_row = _test_set_to_row(test_set, version=version, active=True)
        self._container["generated_test_sets"].append(new_row)
        return _row_to_generated_test_set(new_row)

    async def deactivate_assignment(self, assignment_id: str, *, reason: str) -> int:
        now = _utc_now_iso()
        count = 0
        for row in self._container["generated_test_sets"]:
            if row["assignment_id"] == assignment_id and row.get("active"):
                row["active"] = False
                row["deactivated_at"] = now
                count += 1
        return count

    async def reactivate_exact(
        self, assignment_id: str, cache_key: str
    ) -> GeneratedTestSet | None:
        target: dict[str, Any] | None = None
        for row in self._container["generated_test_sets"]:
            if row["assignment_id"] == assignment_id and row["cache_key"] == cache_key:
                target = row
                break
        if target is None:
            return None

        for row in self._container["generated_test_sets"]:
            if (
                row["assignment_id"] == assignment_id
                and row is not target
                and row.get("active")
            ):
                row["active"] = False
                row["deactivated_at"] = _utc_now_iso()

        target["active"] = True
        target["deactivated_at"] = None
        return _row_to_generated_test_set(target)

    async def get_active(self, assignment_id: str) -> GeneratedTestSet | None:
        for row in self._container["generated_test_sets"]:
            if row["assignment_id"] == assignment_id and row.get("active"):
                return _row_to_generated_test_set(row)
        return None

    async def get_by_id(self, test_set_id: str) -> GeneratedTestSet | None:
        for row in self._container["generated_test_sets"]:
            if row["id"] == test_set_id:
                return _row_to_generated_test_set(row)
        return None


class PostgresGeneratedTestSetStore:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def find_by_cache_key(
        self, assignment_id: str, cache_key: str
    ) -> GeneratedTestSet | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, assignment_id, cache_key, version, difficulty, cases,
                       provider, model, schema_version, prompt_version,
                       assignment_hash, rubric_hash, oracle_validation,
                       active, created_at, deactivated_at
                FROM generated_test_sets
                WHERE assignment_id = $1 AND cache_key = $2
                """,
                assignment_id,
                cache_key,
            )
        if row is None:
            return None
        return _row_to_generated_test_set(dict(row))

    async def insert_verified_set(
        self,
        test_set: GeneratedTestSet,
        *,
        lease_check: Callable[[], None] | None = None,
    ) -> GeneratedTestSet:
        version: int | None = None
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtext($1))",
                        test_set.assignment_id,
                    )

                    version_row = await conn.fetchrow(
                        """
                        SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                        FROM generated_test_sets
                        WHERE assignment_id = $1
                        """,
                        test_set.assignment_id,
                    )
                    version = int(version_row["next_version"])

                    now = _utc_now_dt()
                    await conn.execute(
                        """
                        UPDATE generated_test_sets SET active = false, deactivated_at = $1
                        WHERE assignment_id = $2 AND active = true
                        """,
                        now,
                        test_set.assignment_id,
                    )

                    if test_set.created_at:
                        try:
                            created_at = datetime.fromisoformat(test_set.created_at)
                        except (ValueError, TypeError):
                            created_at = now
                    else:
                        created_at = now

                    if lease_check is not None:
                        lease_check()

                    await conn.execute(
                        """
                        INSERT INTO generated_test_sets (
                            id, assignment_id, cache_key, version, difficulty, cases,
                            provider, model, schema_version, prompt_version,
                            assignment_hash, rubric_hash, oracle_validation, active, created_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $12, $13::jsonb, true, $14
                        )
                        """,
                        test_set.id,
                        test_set.assignment_id,
                        test_set.cache_key,
                        version,
                        test_set.difficulty,
                        json.dumps(_serialize_cases(test_set.cases)),
                        test_set.provider,
                        test_set.model,
                        test_set.schema_version,
                        test_set.prompt_version,
                        test_set.assignment_hash,
                        test_set.rubric_hash,
                        json.dumps(_serialize_oracle_validation(test_set.oracle_validation)),
                        created_at,
                    )
        except asyncpg.UniqueViolationError:
            winner = await self.find_by_cache_key(
                test_set.assignment_id, test_set.cache_key
            )
            if winner is None:
                raise
            return winner

        inserted = await self.find_by_cache_key(test_set.assignment_id, test_set.cache_key)
        if inserted is None:
            raise RuntimeError("inserted generated test set could not be re-read")
        return inserted.model_copy(update={"version": version})

    async def deactivate_assignment(self, assignment_id: str, *, reason: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE generated_test_sets SET active = false, deactivated_at = $1
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
    ) -> GeneratedTestSet | None:
        existing = await self.find_by_cache_key(assignment_id, cache_key)
        if existing is None:
            return None

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generated_test_sets SET active = false, deactivated_at = $1
                WHERE assignment_id = $2 AND active = true
                """,
                _utc_now_dt(),
                assignment_id,
            )
            await conn.execute(
                """
                UPDATE generated_test_sets SET active = true, deactivated_at = NULL
                WHERE assignment_id = $1 AND cache_key = $2
                """,
                assignment_id,
                cache_key,
            )

        reactivated = await self.find_by_cache_key(assignment_id, cache_key)
        if reactivated is None:
            return None
        return reactivated.model_copy(update={"active": True, "deactivated_at": None})

    async def get_active(self, assignment_id: str) -> GeneratedTestSet | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM generated_test_sets
                WHERE assignment_id = $1 AND active = true
                """,
                assignment_id,
            )
        if row is None:
            return None
        return _row_to_generated_test_set(dict(row))

    async def get_by_id(self, test_set_id: str) -> GeneratedTestSet | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM generated_test_sets
                WHERE id = $1
                """,
                test_set_id,
            )
        if row is None:
            return None
        return _row_to_generated_test_set(dict(row))
