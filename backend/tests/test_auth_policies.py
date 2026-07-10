import unittest
import uuid

from fastapi import HTTPException

from backend.auth.models import AuthPrincipal
from backend.auth.policies import enforce_student_self, enforce_teacher_owner

_TEACHER_ID = "11111111-1111-4111-8111-111111111111"
_OTHER_TEACHER_ID = "22222222-2222-4222-8222-222222222222"
_STUDENT_ID = "33333333-3333-4333-8333-333333333333"
_OTHER_STUDENT_ID = "44444444-4444-4444-8444-444444444444"


def _teacher(user_id: str = _TEACHER_ID) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        role="teacher",
        session_hash="sess",
        csrf_hash="csrf",
    )


def _student(user_id: str = _STUDENT_ID) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        role="student",
        session_hash="sess",
        csrf_hash="csrf",
    )


class EnforceTeacherOwnerTests(unittest.TestCase):
    def test_allows_teacher_on_own_resource_read(self):
        enforce_teacher_owner(_teacher(), _TEACHER_ID, mutation=False)

    def test_allows_teacher_on_own_resource_mutation(self):
        enforce_teacher_owner(_teacher(), _TEACHER_ID, mutation=True)

    def test_raises_404_for_different_teacher_owner_read(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_teacher_owner(_teacher(), _OTHER_TEACHER_ID, mutation=False)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_raises_404_for_different_teacher_owner_mutation(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_teacher_owner(_teacher(), _OTHER_TEACHER_ID, mutation=True)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_legacy_null_owner_read_allowed(self):
        enforce_teacher_owner(_teacher(), None, mutation=False)

    def test_legacy_null_owner_mutation_forbidden(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_teacher_owner(_teacher(), None, mutation=True)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Bu eski kayıt salt okunurdur")

    def test_student_principal_raises_403(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_teacher_owner(_student(), _TEACHER_ID, mutation=False)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Öğretmen yetkisi gerekli")

    def test_normalizes_non_string_owner_id(self):
        owner_uuid = uuid.UUID(_TEACHER_ID)
        enforce_teacher_owner(_teacher(), owner_uuid, mutation=False)
        enforce_teacher_owner(_teacher(), owner_uuid, mutation=True)


class EnforceStudentSelfTests(unittest.TestCase):
    def test_allows_student_on_own_id(self):
        enforce_student_self(_student(), _STUDENT_ID)

    def test_raises_404_for_different_student_id(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_student_self(_student(), _OTHER_STUDENT_ID)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_teacher_principal_raises_403(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_student_self(_teacher(), _STUDENT_ID)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Öğrenci yetkisi gerekli")

    def test_normalizes_non_string_student_id(self):
        student_uuid = uuid.UUID(_STUDENT_ID)
        enforce_student_self(_student(), student_uuid)


if __name__ == "__main__":
    unittest.main()
