"""
Exhaustive /api/* route protection inventory for Phase 2A auth.

Every non-public API route must include require_authenticated, require_student,
or require_teacher somewhere in its flattened FastAPI dependency graph.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable

from fastapi.routing import APIRoute

from backend.auth.dependencies import require_authenticated, require_student, require_teacher
from frontend.backend.main import app

PUBLIC_API_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/student/login"),
    ("POST", "/api/teacher/login"),
    ("POST", "/api/teacher/register"),
    # Idempotent cookie cleanup; inline session/CSRF handling, not require_authenticated.
    ("POST", "/api/auth/logout"),
}

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
AUTH_DEPENDENCIES = {require_authenticated, require_student, require_teacher}


def _flatten_dependency_calls(route: APIRoute) -> set[Callable]:
    seen: set[int] = set()
    calls: set[Callable] = set()

    def walk(dependant) -> None:
        dependant_id = id(dependant)
        if dependant_id in seen:
            return
        seen.add(dependant_id)

        call = dependant.call
        if call is not None:
            calls.add(call)

        for child in dependant.dependencies:
            walk(child)

    walk(route.dependant)
    return calls


def _iter_api_route_method_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api/"):
            continue
        methods = {method.upper() for method in route.methods} & HTTP_METHODS
        for method in sorted(methods):
            pairs.append((method, route.path))
    return pairs


def _api_routes_by_path() -> dict[str, APIRoute]:
    return {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
    }


class AuthRouteInventoryTests(unittest.TestCase):
    def test_every_non_public_api_route_has_auth_dependency(self) -> None:
        routes_by_path = _api_routes_by_path()
        checked = _iter_api_route_method_pairs()
        unprotected: list[tuple[str, str]] = []

        for method, path in checked:
            if (method, path) in PUBLIC_API_ROUTES:
                continue
            route = routes_by_path[path]
            if not (_flatten_dependency_calls(route) & AUTH_DEPENDENCIES):
                unprotected.append((method, path))

        if unprotected:
            self.fail(f"Unprotected routes found: {sorted(unprotected)}")

        self.assertGreater(len(checked), len(PUBLIC_API_ROUTES))

    def test_public_api_routes_have_no_auth_dependency(self) -> None:
        mismatched: list[tuple[str, str, list[str]]] = []

        routes_by_path = _api_routes_by_path()

        for method, path in sorted(PUBLIC_API_ROUTES):
            route = routes_by_path[path]
            auth_calls = sorted(
                fn.__name__
                for fn in (_flatten_dependency_calls(route) & AUTH_DEPENDENCIES)
            )
            if auth_calls:
                mismatched.append((method, path, auth_calls))

        if mismatched:
            details = ", ".join(
                f"{method} {path} -> {auth_calls}" for method, path, auth_calls in mismatched
            )
            self.fail(f"Public routes unexpectedly protected: {details}")


if __name__ == "__main__":
    unittest.main()
