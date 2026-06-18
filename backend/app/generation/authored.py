"""Mode A — human-authored case specs + deterministic-first Pest rendering.

A human authors a test case from scratch (no AI plan). This module is the
generation half of Mode A:

- ``AuthoredCaseSpec`` is the authoring input contract — the standard case fields
  a human fills in (endpoint, payload, expected status + structural shape,
  oracle). ``CaseAuthoringService`` turns it into a versioned ``TestCase``.
- **Deterministic-first scripting.** A structurally simple case (single endpoint,
  concrete method/URI/payload/expected-status + a structural shape, no DB setup)
  renders to Pest from a pure template — *no AI call*. Only cases that genuinely
  need app-specific knowledge (DB rows to set up, path params, unusual methods)
  fall back to the existing T1.4 AI render. This is deterministic-first: AI only
  where it is actually needed (Architecture §5/§6, TRD §5).

Nothing here writes to the database; persistence is the service's job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.ai.types import AIProvider
from app.ingestion.models import EndpointSpec
from app.models.enums import OracleSource, TestLayer, TestType

from .case_key import compute_case_key
from .plan import DbDependency, ExpectedOutcome, PlannedCase
from .render import render_script

# HTTP method → Laravel test JSON helper. For these (except GET) the second
# argument is the request body; GET's second argument is headers, so a GET with
# a body is not template-renderable (see is_template_renderable).
_JSON_HELPERS: dict[str, str] = {
    "GET": "getJson",
    "POST": "postJson",
    "PUT": "putJson",
    "PATCH": "patchJson",
    "DELETE": "deleteJson",
}


@dataclass(frozen=True)
class AuthoredEndpoint:
    """The endpoint a human-authored case targets."""

    method: str
    uri: str
    route_name: str | None = None


@dataclass(frozen=True)
class DbSetup:
    """A DB precondition the case needs (a row that must exist / not exist).

    Its presence makes a case app-specific — the deterministic template cannot
    synthesize the rows/relations, so such a case falls back to the AI render.
    """

    kind: str  # "row_present" | "row_absent"
    table: str
    column: str | None = None
    value: Any = None


@dataclass(frozen=True)
class AuthoredCaseSpec:
    """A human's from-scratch test case (Mode A). Carries the standard fields.

    The human sets the oracle (``oracle_source``) directly; the "human-vouched"
    oracle tier is a later refinement and is intentionally not modeled here.
    """

    name: str
    type: TestType
    endpoint: AuthoredEndpoint
    expected_status: int
    oracle_source: OracleSource
    layer: TestLayer = TestLayer.API
    auth_required: bool = False
    authenticated: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    path_values: dict[str, Any] = field(default_factory=dict)
    # Structural only (which keys to assert / which fields error) — never values.
    expected_shape: dict[str, Any] = field(default_factory=dict)
    requirement_link: str | None = None
    rule: str = "authored"
    # Compute a case_key (so re-generation recognizes this logical case) when the
    # case targets a known endpoint+type; set False for a free-form case (null key).
    keyed: bool = True
    db_setup: list[DbSetup] = field(default_factory=list)


def is_template_renderable(spec: AuthoredCaseSpec) -> bool:
    """True when the case is simple enough for the deterministic Pest template.

    Simple ⇒ no DB setup, a known HTTP method, a URI with every path placeholder
    resolved, and no GET body. Anything else needs app-specific knowledge and is
    routed to the AI render instead.
    """
    method = spec.endpoint.method.upper()
    if spec.db_setup:
        return False
    if method not in _JSON_HELPERS:
        return False
    if _resolve_uri(spec) is None:
        return False
    if method == "GET" and spec.payload:
        return False
    return True


def render_authored_script(
    provider: AIProvider, spec: AuthoredCaseSpec, budget_tokens: int
) -> tuple[str, bool]:
    """Render the Pest script for an authored case.

    Returns ``(code, deterministic)``: a template render (``True``, no AI call)
    for a simple case, otherwise the T1.4 AI render (``False``). The AI provider
    is touched *only* on the fallback path.
    """
    if is_template_renderable(spec):
        return render_pest_template(spec), True
    endpoint, planned = _to_endpoint_and_plan(spec)
    return render_script(provider, endpoint, planned, budget_tokens), False


def compute_authored_case_key(spec: AuthoredCaseSpec) -> str | None:
    """The deterministic case_key for a keyed authored case, else None.

    Uses the SAME key function as generation (``compute_case_key``), so an
    authored case targeting a known endpoint+type shares the key a re-generation
    would compute — and is therefore matched (and protected) by the merge engine.
    A free-form case (``keyed=False``) gets a null key.
    """
    if not spec.keyed:
        return None
    endpoint, planned = _to_endpoint_and_plan(spec)
    return compute_case_key(endpoint, planned)


# --- deterministic Pest template ---------------------------------------------


def render_pest_template(spec: AuthoredCaseSpec) -> str:
    """Assemble a Pest feature test purely from the spec — no AI.

    Precondition: ``is_template_renderable(spec)`` (the caller guarantees it).
    """
    method = spec.endpoint.method.upper()
    helper = _JSON_HELPERS[method]
    uri = _resolve_uri(spec)
    assert uri is not None  # guaranteed by is_template_renderable
    php_uri = uri if uri.startswith("/") else f"/{uri}"

    lines = [
        "<?php",
        "",
        f"// Authored test case: {spec.name}",
        f"// oracle_source: {spec.oracle_source.value}",
        "",
        f"test('{_escape_single(spec.name)}', function () {{",
    ]
    if spec.authenticated:
        lines.append(
            "    $this->actingAs(\\App\\Models\\User::query()->firstOrFail());"
        )
    if method != "GET" and spec.payload:
        body = _php_payload(spec.payload)
        lines.append(f"    $response = $this->{helper}('{php_uri}', {body});")
    else:
        lines.append(f"    $response = $this->{helper}('{php_uri}');")
    lines.append(f"    $response->assertStatus({spec.expected_status});")
    lines.extend(_shape_asserts(spec.expected_shape))
    lines.append("});")
    return "\n".join(lines) + "\n"


def _shape_asserts(shape: dict[str, Any]) -> list[str]:
    """Deterministic structural assertions (never asserts specific values)."""
    errors = shape.get("validation_errors")
    structure = shape.get("json_structure")
    if errors:
        return [f"    $response->assertJsonValidationErrors({_php_list(errors)});"]
    if structure:
        return [f"    $response->assertJsonStructure({_php_list(structure)});"]
    return ["    expect($response->json())->toBeArray();"]


def _resolve_uri(spec: AuthoredCaseSpec) -> str | None:
    """Substitute ``path_values`` into the URI; None if any placeholder remains."""
    uri = spec.endpoint.uri
    for key, value in spec.path_values.items():
        uri = uri.replace("{" + key + "}", str(value))
    if "{" in uri or "}" in uri:
        return None
    return uri


def _php_payload(payload: dict[str, Any]) -> str:
    """A multi-line PHP associative array, keys sorted for determinism."""
    if not payload:
        return "[]"
    lines = ["["]
    for key in sorted(payload):
        lines.append(f"        {_php_value(key)} => {_php_value(payload[key])},")
    lines.append("    ]")
    return "\n".join(lines)


def _php_list(values: list[Any]) -> str:
    return "[" + ", ".join(_php_value(v) for v in values) + "]"


def _php_value(value: Any) -> str:
    """Render a Python value as a deterministic PHP literal."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # before int — bool is a subclass of int
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return f"'{_escape_single(value)}'"
    if isinstance(value, dict):
        inner = ", ".join(
            f"{_php_value(k)} => {_php_value(v)}" for k, v in sorted(value.items())
        )
        return f"[{inner}]"
    if isinstance(value, list):
        return _php_list(value)
    # Anything exotic: encode as a JSON string literal (deterministic, safe).
    return _php_value(json.dumps(value, sort_keys=True))


def _escape_single(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _to_endpoint_and_plan(
    spec: AuthoredCaseSpec,
) -> tuple[EndpointSpec, PlannedCase]:
    """Adapt an authoring spec to the T1.4 (EndpointSpec, PlannedCase) shape.

    Lets the authored case reuse the existing key function and AI render path
    without a parallel code path.
    """
    endpoint = EndpointSpec(
        method=spec.endpoint.method,
        uri=spec.endpoint.uri,
        route_name=spec.endpoint.route_name,
        auth_required=spec.auth_required,
        path_params=list(spec.path_values),
        query_params=[],
        validation_fields=[],
    )
    planned = PlannedCase(
        name=spec.name,
        description=f"authored: {spec.name}",
        case_type=spec.type,
        rule=spec.rule,
        target_field=None,
        payload=spec.payload,
        path_values=spec.path_values,
        authenticated=spec.authenticated,
        expected=ExpectedOutcome(
            status=spec.expected_status, shape=spec.expected_shape
        ),
        oracle_source=spec.oracle_source,
        dependencies=[
            DbDependency(kind=d.kind, table=d.table, column=d.column, value=d.value)
            for d in spec.db_setup
        ],
    )
    return endpoint, planned
