from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, Response

from backend.auth.models import AuthPrincipal, IssuedSession
from backend.auth.sessions import SessionStore, hash_token
from backend.core.config import settings
from backend.queue.analysis_jobs import create_redis_client

SESSION_COOKIE = "agentgrade_session"
CSRF_COOKIE = "agentgrade_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_SESSION_MAX_AGE = 28800


async def get_auth_session_store(request: Request) -> SessionStore:
    store = getattr(request.app.state, "auth_session_store", None)
    if store is None:
        redis = create_redis_client(settings.redis_url)
        store = SessionStore(redis, ttl_seconds=settings.auth_session_ttl_seconds)
        request.app.state.auth_session_store = store
    return store


async def require_authenticated(
    request: Request,
    store: SessionStore = Depends(get_auth_session_store),
) -> AuthPrincipal:
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw:
        raise HTTPException(status_code=401, detail="Oturum gerekli")

    try:
        principal = await store.read_session(raw)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Oturum servisine ulaşılamıyor") from exc

    if principal is None:
        raise HTTPException(status_code=401, detail="Oturum geçersiz veya süresi dolmuş")

    if request.method.upper() not in SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not hmac.compare_digest(hash_token(supplied), principal.csrf_hash):
            raise HTTPException(status_code=403, detail="CSRF doğrulaması başarısız")

    return principal


async def require_student(
    principal: AuthPrincipal = Depends(require_authenticated),
) -> AuthPrincipal:
    if principal.role != "student":
        raise HTTPException(status_code=403, detail="Öğrenci yetkisi gerekli")
    return principal


async def require_teacher(
    principal: AuthPrincipal = Depends(require_authenticated),
) -> AuthPrincipal:
    if principal.role != "teacher":
        raise HTTPException(status_code=403, detail="Öğretmen yetkisi gerekli")
    return principal


def set_auth_cookies(response: Response, issued: IssuedSession, *, secure: bool) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=issued.session_token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=issued.csrf_token,
        max_age=_SESSION_MAX_AGE,
        httponly=False,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
