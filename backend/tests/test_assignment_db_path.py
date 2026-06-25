import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from frontend.backend import main


_COURSE_ID = "44444444-4444-4444-8444-444444444444"
_ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"


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


if __name__ == "__main__":
    unittest.main()
