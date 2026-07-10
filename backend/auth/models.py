from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AuthRole = Literal["student", "teacher"]


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    user_id: str
    role: AuthRole
    session_hash: str
    csrf_hash: str


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session_token: str
    csrf_token: str
    principal: AuthPrincipal


@dataclass
class SessionRecord:
    user_id: str
    role: AuthRole
    csrf_hash: str
    created_at: str
