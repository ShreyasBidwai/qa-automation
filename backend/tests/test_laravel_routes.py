"""Route-fact parsing/matching from canned `route:list --json` (offline)."""

from __future__ import annotations

import json

import pytest

from app.ingestion.errors import RouteNotFound
from app.ingestion.laravel.route_list import (
    RouteTarget,
    build_route_facts,
    derive_auth_required,
    find_route,
    parse_route_list,
    path_params_from_uri,
    route_facts_from_output,
)

ROUTE_LIST_JSON = json.dumps(
    [
        {
            "method": "POST",
            "uri": "api/users",
            "name": "users.store",
            "action": "App\\Http\\Controllers\\UserController@store",
            "middleware": ["api", "auth:sanctum"],
        },
        {
            "method": "PUT",
            "uri": "api/users/{user}",
            "name": "users.update",
            "action": "App\\Http\\Controllers\\UserController@update",
            "middleware": ["api", "auth:sanctum"],
        },
        {
            "method": "GET|HEAD",
            "uri": "api/health",
            "name": "health",
            "action": "App\\Http\\Controllers\\UserController@health",
            "middleware": ["api"],
        },
    ]
)


def test_match_by_route_name() -> None:
    facts = route_facts_from_output(ROUTE_LIST_JSON, RouteTarget(name="users.store"))
    assert facts.method == "POST"
    assert facts.uri == "api/users"
    assert facts.name == "users.store"
    assert facts.action == "App\\Http\\Controllers\\UserController@store"
    assert facts.auth_required is True
    assert "auth:sanctum" in facts.middleware


def test_match_by_method_and_uri() -> None:
    facts = route_facts_from_output(
        ROUTE_LIST_JSON, RouteTarget(method="put", uri="/api/users/{user}")
    )
    assert facts.name == "users.update"
    assert facts.method == "PUT"
    assert facts.auth_required is True


def test_public_route_is_not_auth_required_and_picks_primary_method() -> None:
    facts = route_facts_from_output(ROUTE_LIST_JSON, RouteTarget(name="health"))
    assert facts.method == "GET"  # HEAD is dropped as the primary verb
    assert facts.auth_required is False


def test_unmatched_or_underspecified_target_raises() -> None:
    with pytest.raises(RouteNotFound):
        route_facts_from_output(ROUTE_LIST_JSON, RouteTarget(name="does.not.exist"))
    with pytest.raises(RouteNotFound):
        route_facts_from_output(ROUTE_LIST_JSON, RouteTarget())  # no identifier


def test_derive_auth_required_variants() -> None:
    assert derive_auth_required(["web", "auth"]) is True
    assert derive_auth_required(["auth:sanctum"]) is True
    assert derive_auth_required(["api", "auth:api"]) is True
    assert derive_auth_required(["sanctum"]) is True
    assert derive_auth_required(["web", "throttle:60,1"]) is False
    assert derive_auth_required([]) is False


def test_path_params_extraction() -> None:
    assert path_params_from_uri("api/users/{user}") == ["user"]
    assert path_params_from_uri("api/users/{user}/posts/{post?}") == ["user", "post"]
    assert path_params_from_uri("api/health") == []


def test_middleware_string_form_is_supported() -> None:
    routes = parse_route_list(
        json.dumps(
            [
                {
                    "method": "GET",
                    "uri": "x",
                    "name": "x",
                    "action": "A@b",
                    "middleware": "web\nauth",
                }
            ]
        )
    )
    facts = build_route_facts(find_route(routes, RouteTarget(name="x")), RouteTarget(name="x"))
    assert facts.middleware == ["web", "auth"]
    assert facts.auth_required is True
