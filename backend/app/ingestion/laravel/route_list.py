"""Parse and match `php artisan route:list --json` output (deterministic)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.ingestion.errors import RouteNotFound, ValidationExtractionError

# Middleware whose presence implies the endpoint requires authentication.
_AUTH_MIDDLEWARE_HEADS = {"auth", "auth.basic", "auth.session"}

# Middleware heads that name a role (e.g. `role:admin`, `role_or_permission:admin`).
_ROLE_MIDDLEWARE_HEADS = {"role", "roles", "role_or_permission"}

_PATH_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\??\}")


@dataclass(frozen=True)
class RouteTarget:
    """Identifies one route: by name, or by HTTP method + URI."""

    name: str | None = None
    method: str | None = None
    uri: str | None = None


@dataclass(frozen=True)
class RouteFacts:
    method: str  # primary HTTP method (e.g. POST)
    methods: list[str]  # all methods (e.g. [GET, HEAD])
    uri: str
    name: str | None
    action: str  # Controller@method | Closure | ...
    middleware: list[str] = field(default_factory=list)
    auth_required: bool = False


def _normalize_uri(uri: str) -> str:
    return uri.strip().strip("/")


def _as_middleware_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        # Older Laravel joins middleware with newlines/commas in one string.
        return [part.strip() for part in re.split(r"[\n,]", raw) if part.strip()]
    return []


def _methods_of(route: dict[str, Any]) -> list[str]:
    raw = route.get("method", "")
    return [m.strip().upper() for m in str(raw).split("|") if m.strip()]


def derive_auth_required(middleware: list[str]) -> bool:
    for entry in middleware:
        head = entry.split(":", 1)[0].strip()
        if head in _AUTH_MIDDLEWARE_HEADS or "sanctum" in entry:
            return True
    return False


def roles_from_middleware(middleware: list[str]) -> list[str]:
    """Role names named by middleware (`role:admin`, `role:admin,editor`, …).

    Only reliably role-naming middleware is read; everything else is left out
    (honest extraction — no guessing).
    """
    roles: list[str] = []
    for entry in middleware:
        head, _, args = entry.partition(":")
        if head.strip() in _ROLE_MIDDLEWARE_HEADS and args:
            roles.extend(part.strip() for part in args.split(",") if part.strip())
    # De-dupe, preserve order.
    return list(dict.fromkeys(roles))


def path_params_from_uri(uri: str) -> list[str]:
    return _PATH_PARAM.findall(uri)


def parse_route_list(stdout: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValidationExtractionError(
            "artisan route:list did not return valid JSON"
        ) from exc
    if not isinstance(data, list):
        raise ValidationExtractionError("route:list JSON is not an array")
    return [item for item in data if isinstance(item, dict)]


def _matches(route: dict[str, Any], target: RouteTarget) -> bool:
    if target.name is not None:
        return route.get("name") == target.name
    if target.method is not None and target.uri is not None:
        return target.method.strip().upper() in _methods_of(route) and _normalize_uri(
            str(route.get("uri", ""))
        ) == _normalize_uri(target.uri)
    return False


def find_route(routes: list[dict[str, Any]], target: RouteTarget) -> dict[str, Any]:
    if target.name is None and not (target.method and target.uri):
        raise RouteNotFound("route target requires a name, or both a method and a URI")
    matches = [route for route in routes if _matches(route, target)]
    if not matches:
        raise RouteNotFound(f"no route matched target {target}")
    return matches[0]


def build_route_facts(route: dict[str, Any], target: RouteTarget) -> RouteFacts:
    methods = _methods_of(route)
    # Prefer the requested method; else the first non-HEAD/OPTIONS verb.
    primary = (target.method or "").strip().upper()
    if primary not in methods:
        primary = next(
            (m for m in methods if m not in {"HEAD", "OPTIONS"}),
            methods[0] if methods else "",
        )
    middleware = _as_middleware_list(route.get("middleware"))
    name = route.get("name")
    return RouteFacts(
        method=primary,
        methods=methods,
        uri=_normalize_uri(str(route.get("uri", ""))),
        name=str(name) if name else None,
        action=str(route.get("action", "")),
        middleware=middleware,
        auth_required=derive_auth_required(middleware),
    )


def route_facts_from_output(stdout: str, target: RouteTarget) -> RouteFacts:
    routes = parse_route_list(stdout)
    return build_route_facts(find_route(routes, target), target)


def all_route_facts(stdout: str) -> list[RouteFacts]:
    """Facts for EVERY route in `route:list --json` output (whole-repo ingest)."""
    return [
        build_route_facts(route, RouteTarget()) for route in parse_route_list(stdout)
    ]
