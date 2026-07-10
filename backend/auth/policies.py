from __future__ import annotations

from fastapi import HTTPException

from backend.auth.models import AuthPrincipal


def enforce_teacher_owner(principal: AuthPrincipal, owner_id: object, *, mutation: bool) -> None:
    if principal.role != "teacher":
        raise HTTPException(status_code=403, detail="Öğretmen yetkisi gerekli")
    normalized = str(owner_id or "").strip()
    if not normalized:
        if mutation:
            raise HTTPException(status_code=403, detail="Bu eski kayıt salt okunurdur")
        return
    if normalized != principal.user_id:
        raise HTTPException(status_code=404, detail="Kaynak bulunamadı")


def enforce_student_self(principal: AuthPrincipal, student_id: object) -> None:
    if principal.role != "student":
        raise HTTPException(status_code=403, detail="Öğrenci yetkisi gerekli")
    if str(student_id or "").strip() != principal.user_id:
        raise HTTPException(status_code=404, detail="Kaynak bulunamadı")
