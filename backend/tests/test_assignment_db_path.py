import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from frontend.backend import main


_COURSE_ID = "44444444-4444-4444-8444-444444444444"
_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
_DEPARTMENT_ID = "33333333-3333-4333-8333-333333333333"


class AssignmentDbPathTests(unittest.TestCase):
    def test_create_assignment_db_insert_uses_four_values_for_four_placeholders(self):
        class FakePool:
            def __init__(self):
                self.calls = []

            async def fetchrow(self, query, *args):
                self.calls.append((query, args))
                if "FROM public.courses" in query:
                    return {
                        "id": _COURSE_ID,
                        "name": "Python Programlama",
                        "code": "PRO101",
                        "class_year": 3,
                    }
                return {
                    "id": _ASSIGNMENT_ID,
                    "course_id": _COURSE_ID,
                    "name": "Dosya Analizi",
                    "description": "Sayilari oku.",
                    "due_date": None,
                    "created_at": "2026-06-25T12:00:00Z",
                }

        pool = FakePool()

        async def run_case():
            with patch.object(main, "_DEMO_MODE", False):
                with patch.object(main, "_get_db_pool", new=AsyncMock(return_value=pool)):
                    with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
                        await main.create_assignment(
                            main.AssignmentCreateRequest(
                                course_id=_COURSE_ID,
                                name="Dosya Analizi",
                                description="Sayilari oku.",
                            )
                        )

        asyncio.run(run_case())

        insert_calls = [call for call in pool.calls if "INSERT INTO public.assignments" in call[0]]
        self.assertEqual(len(insert_calls), 1)
        self.assertEqual(len(insert_calls[0][1]), 4)

    def test_create_assignment_db_insert_returning_includes_created_by(self):
        class FakePool:
            def __init__(self):
                self.calls = []

            async def fetchrow(self, query, *args):
                self.calls.append((query, args))
                if "FROM public.courses" in query:
                    return {
                        "id": _COURSE_ID,
                        "name": "Python Programlama",
                        "code": "PRO101",
                        "class_year": 3,
                    }
                return {
                    "id": _ASSIGNMENT_ID,
                    "course_id": _COURSE_ID,
                    "name": "Dosya Analizi",
                    "description": "Sayilari oku.",
                    "due_date": None,
                    "created_at": "2026-06-25T12:00:00Z",
                }

        pool = FakePool()

        async def run_case():
            with patch.object(main, "_DEMO_MODE", False):
                with patch.object(main, "_get_db_pool", new=AsyncMock(return_value=pool)):
                    with patch.object(main, "_ensure_assignment_safety", new=AsyncMock(return_value=None)):
                        await main.create_assignment(
                            main.AssignmentCreateRequest(
                                course_id=_COURSE_ID,
                                name="Dosya Analizi",
                                description="Sayilari oku.",
                            )
                        )

        asyncio.run(run_case())

        insert_calls = [call for call in pool.calls if "INSERT INTO public.assignments" in call[0]]
        self.assertEqual(len(insert_calls), 1)
        self.assertIn("created_by", insert_calls[0][0])

    def test_create_course_db_insert_returning_includes_created_by(self):
        class FakePool:
            def __init__(self):
                self.calls = []

            async def fetchrow(self, query, *args):
                self.calls.append((query, args))
                if "INSERT INTO public.courses" in query:
                    return {
                        "id": _COURSE_ID,
                        "name": "Veri Yapilari",
                        "code": "BLM201",
                        "class_year": 2,
                        "department_id": _DEPARTMENT_ID,
                        "created_by": None,
                        "created_at": "2026-06-25T12:00:00Z",
                    }
                return None

            async def execute(self, query, *args):
                self.calls.append((query, args))
                return "INSERT 0 1"

        pool = FakePool()

        async def run_case():
            with patch.object(main, "_DEMO_MODE", False):
                with patch.object(main, "_get_db_pool", new=AsyncMock(return_value=pool)):
                    with patch.object(main, "_sync_course_to_all_students", new=AsyncMock(return_value=None)):
                        await main.create_course(
                            main.CourseCreateRequest(
                                name="Veri Yapilari",
                                code="BLM201",
                                class_year=2,
                                department_id=_DEPARTMENT_ID,
                            )
                        )

        asyncio.run(run_case())

        insert_calls = [call for call in pool.calls if "INSERT INTO public.courses" in call[0]]
        self.assertEqual(len(insert_calls), 1)
        self.assertEqual(len(insert_calls[0][1]), 4)
        self.assertIn("created_by", insert_calls[0][0])

    def test_ensure_db_schema_includes_created_by_columns_and_indexes(self):
        class FakePool:
            def __init__(self):
                self.sql = None

            async def execute(self, sql, *args):
                if self.sql is None:
                    self.sql = sql
                return "OK"

            async def fetch(self, query, *args):
                return []

        pool = FakePool()

        async def run_case():
            await main._ensure_db_schema(pool)

        asyncio.run(run_case())

        self.assertIsNotNone(pool.sql)
        self.assertIn("ALTER TABLE public.courses", pool.sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS created_by", pool.sql)
        self.assertIn("ALTER TABLE public.assignments", pool.sql)
        self.assertIn("idx_courses_created_by", pool.sql)
        self.assertIn("idx_assignments_created_by", pool.sql)


if __name__ == "__main__":
    unittest.main()
