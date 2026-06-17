"""End-to-end LaravelExtractor against the fixture, with injected runners so no
real artisan/php is ever invoked (asserted, like the no-real-CLI guard in T1.2).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.ingestion.commands import CommandResult
from app.ingestion.errors import ActionResolutionError
from app.ingestion.laravel.extractor import LaravelExtractor
from app.ingestion.laravel.route_list import RouteTarget

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
    ]
)

# Canned outputs of the PHP AST helper for the fixture's two actions.
VALIDATION_BY_ACTION = {
    "store": json.dumps(
        {
            "source": "form_request",
            "class": "App\\Http\\Requests\\StoreUserRequest",
            "rules": {
                "name": "required|string|max:255",
                "email": "required|email|unique:users,email",
                "age": "required|integer|min:18|max:120",
                "country_id": "required|exists:countries,id",
                "newsletter": "boolean",
            },
        }
    ),
    "update": json.dumps(
        {
            "source": "inline_validate",
            "rules": {
                "name": "sometimes|string|max:255",
                "age": "nullable|integer|min:18|max:120",
                "email": "sometimes|email|unique:users,email",
            },
        }
    ),
}


@pytest.fixture(autouse=True)
def _forbid_real_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("real artisan/php subprocess invoked in tests")

    monkeypatch.setattr("app.ingestion.commands.subprocess.run", _boom)


def _runner(argv: Sequence[str], cwd: str | None, timeout: float) -> CommandResult:
    args = list(argv)
    if "artisan" in args:
        return CommandResult(0, ROUTE_LIST_JSON, "")
    if len(args) >= 5 and args[1].endswith("extract_validation.php"):
        return CommandResult(0, VALIDATION_BY_ACTION[args[4]], "")
    raise AssertionError(f"unexpected argv: {args}")


def test_extract_store_endpoint_via_form_request() -> None:
    spec = LaravelExtractor(runner=_runner).extract_endpoint(
        "/repo", RouteTarget(name="users.store")
    )
    assert spec.method == "POST"
    assert spec.uri == "api/users"
    assert spec.route_name == "users.store"
    assert spec.auth_required is True
    assert spec.path_params == []

    assert [f.name for f in spec.validation_fields] == [
        "name",
        "email",
        "age",
        "country_id",
        "newsletter",
    ]
    by_name = {f.name: f for f in spec.validation_fields}
    assert by_name["email"].type == "email"
    assert by_name["email"].relational is not None
    assert by_name["email"].relational.kind == "unique"
    assert by_name["age"].type == "integer"
    assert by_name["age"].constraints.min == 18.0
    assert by_name["age"].constraints.max == 120.0
    assert by_name["country_id"].relational is not None
    assert by_name["country_id"].relational.kind == "exists"
    assert by_name["country_id"].relational.table == "countries"


def test_extract_update_endpoint_via_inline_validate() -> None:
    spec = LaravelExtractor(runner=_runner).extract_endpoint(
        "/repo", RouteTarget(method="PUT", uri="api/users/{user}")
    )
    assert spec.method == "PUT"
    assert spec.route_name == "users.update"
    assert spec.auth_required is True
    assert spec.path_params == ["user"]
    assert [f.name for f in spec.validation_fields] == ["name", "age", "email"]
    by_name = {f.name: f for f in spec.validation_fields}
    assert by_name["age"].required is False
    assert by_name["age"].type == "integer"
    assert by_name["email"].type == "email"


def test_closure_action_raises_typed_error() -> None:
    def runner(
        argv: Sequence[str], cwd: str | None, timeout: float
    ) -> CommandResult:
        return CommandResult(
            0,
            json.dumps(
                [
                    {
                        "method": "GET",
                        "uri": "ping",
                        "name": "ping",
                        "action": "Closure",
                        "middleware": [],
                    }
                ]
            ),
            "",
        )

    with pytest.raises(ActionResolutionError):
        LaravelExtractor(runner=runner).extract_endpoint(
            "/repo", RouteTarget(name="ping")
        )
