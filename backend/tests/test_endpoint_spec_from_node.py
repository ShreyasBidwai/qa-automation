"""Regression: ``endpoint_spec_from_node`` must accept the STATIC whole-repo
ingester's validation shape — ``validation.fields`` as bare names (``list[str]``) —
not only the per-endpoint extractor's rich dicts. A statically-ingested Brain (the
default ``INGESTOR_MODE=laravel`` path) has to drive generation without crashing.

Before the fix this raised ``AttributeError: 'str' object has no attribute 'get'``
in ``_validation_field`` and killed every real mode_b run during generation.
"""

from __future__ import annotations

import uuid

from app.generation.endpoint_from_node import (
    _validation_field,
    endpoint_spec_from_node,
)
from app.models.enums import NodeKind
from app.models.model_node import ModelNode


def _endpoint_node(validation: dict[str, object]) -> ModelNode:
    return ModelNode(
        project_id=uuid.uuid4(),
        kind=NodeKind.ENDPOINT,
        name="POST /users",
        attributes={"method": "POST", "uri": "/users", "validation": validation},
    )


def test_validation_field_accepts_a_bare_string_name() -> None:
    # The static ingester records a field as just its NAME.
    field = _validation_field("email")
    assert field.name == "email"
    assert field.required is False
    assert field.type == "unknown"
    assert field.constraints.max is None


def test_endpoint_spec_prefers_typed_rules_over_bare_names() -> None:
    # When the Brain carries the rule SPECS, fields are TYPED (so the plan can emit
    # type-correct payloads) — not the type='unknown' bare-name fallback.
    node = _endpoint_node(
        {
            "source": "form_request",
            "fields": ["age", "email"],
            "rules": {
                "age": "required|integer|min:18|max:120",
                "email": "required|email",
            },
        }
    )
    spec = endpoint_spec_from_node(node)
    by_name = {f.name: f for f in spec.validation_fields}
    assert by_name["age"].type == "integer"
    assert by_name["age"].required is True
    assert by_name["age"].constraints.min == 18
    assert by_name["age"].constraints.max == 120
    assert by_name["email"].type == "email"


def test_endpoint_spec_from_static_ingest_string_fields_does_not_raise() -> None:
    node = _endpoint_node(
        {"source": "form_request", "fields": ["name", "email", "age"]}
    )
    spec = endpoint_spec_from_node(node)  # must not raise
    assert spec.method == "POST"
    assert spec.uri == "/users"
    assert [f.name for f in spec.validation_fields] == ["name", "email", "age"]


def _route_node(uri: str, middleware: object) -> ModelNode:
    attrs: dict[str, object] = {"method": "GET", "uri": uri, "validation": {}}
    if middleware is not None:
        attrs["middleware"] = middleware
    return ModelNode(
        project_id=uuid.uuid4(),
        kind=NodeKind.ENDPOINT,
        name=f"GET {uri}",
        attributes=attrs,
    )


def test_is_api_derived_from_the_api_middleware_group() -> None:
    # The `api` middleware group is the reliable signal — a JSON api route (ADR-0063).
    spec = endpoint_spec_from_node(_route_node("api/users", ["api", "throttle:60,1"]))
    assert spec.is_api is True


def test_is_api_false_for_a_web_route() -> None:
    # A `web` route (session/redirect) — the login-module case that must NOT be treated
    # as a JSON API, or every generated test false-fails.
    spec = endpoint_spec_from_node(_route_node("login/apple", ["web", "guest"]))
    assert spec.is_api is False


def test_is_api_falls_back_to_the_uri_prefix_when_middleware_missing() -> None:
    # Older Brains captured no middleware — fall back to the conventional `api/` prefix.
    assert endpoint_spec_from_node(_route_node("api/orders", None)).is_api is True
    assert endpoint_spec_from_node(_route_node("dashboard", None)).is_api is False


def test_endpoint_spec_from_extractor_dict_fields_still_works() -> None:
    # The richer per-endpoint extractor shape (dicts) must keep working unchanged.
    node = _endpoint_node(
        {
            "fields": [
                {
                    "name": "email",
                    "type": "string",
                    "required": True,
                    "constraints": {"max": 255},
                }
            ]
        }
    )
    spec = endpoint_spec_from_node(node)
    assert len(spec.validation_fields) == 1
    field = spec.validation_fields[0]
    assert field.name == "email"
    assert field.required is True
    assert field.type == "string"
    assert field.constraints.max == 255
