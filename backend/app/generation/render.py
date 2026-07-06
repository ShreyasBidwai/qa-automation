"""PHASE 2 — AI renders the PHPUnit test code AROUND the deterministic plan.

The AIProvider assembles auth setup, the HTTP call, and assertions, but the
payload and expected status are FIXED by PHASE 1 and passed in the
budget-capped Subgraph context — the model never invents them. A characterization
header is prepended deterministically so the oracle stance is always explicit,
independent of model output.

The output is a PHPUnit-style Laravel feature test CLASS (``class …Test extends
TestCase``) — a single dialect BOTH PHPUnit and Pest run natively (Pest executes
PHPUnit test classes), so the test runs whatever binary the target ships. The class
name is rewritten to a deterministic, globally-unique value so multiple generated
files never collide in one runner invocation.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from app.ai.types import AIProvider, Subgraph, SubgraphNode
from app.ingestion.models import EndpointSpec
from app.models.enums import OracleSource

from .extract import (
    extract_code,
    rewrite_class_name,
    skip_if_uses_factory,
    unique_class_name,
    with_php_header,
)
from .plan import PlannedCase

_INSTRUCTION = (
    "You are rendering ONE Laravel/PHPUnit feature test CLASS for a route. "
    "Emit a PHP class in `namespace Tests\\Feature;` that extends `Tests\\TestCase`, "
    "uses `Illuminate\\Foundation\\Testing\\RefreshDatabase`, and has a SINGLE public "
    "method `test_<case>(): void`. Do NOT use Pest's it()/test()/uses()/expect(). Use "
    "EXACTLY the HTTP request (method, URI, path values, payload) given in the "
    "context; do NOT invent or change any payload value.\n\n"
    # The request helper depends on the route CLASS: api routes speak JSON, web routes
    # speak sessions/redirects. Using the JSON helper on a web route (and asserting a
    # JSON body) is the single biggest source of false failures — ADR-0063.
    "CHOOSE THE REQUEST HELPER by `endpoint.is_api`: if is_api is true, drive it with "
    "the JSON helpers ($this->getJson/postJson/putJson/patchJson/deleteJson) so "
    "Laravel sets the JSON Accept header; if is_api is FALSE (a web route), use the "
    "plain helpers ($this->get/post/put/patch/delete) and do NOT assert a JSON body — "
    "a web route returns HTML or a redirect, not JSON.\n\n"
    # Self-analysis in the SAME call: reason about the contract, record the intent as
    # a PHP comment (valid code, so output stays code-only), then assert THAT behaviour.
    "FIRST, analyse the contract from the context — the HTTP method's semantics, the "
    "route class (is_api), the endpoint's validation rules, this case's intent/target "
    "field, and `expected` — and open the test method body with a concise `// Intent:` "
    "comment (1-2 lines) stating WHAT behaviour this verifies and WHY. THEN assert "
    "exactly that, grounded ONLY in the context: never assert a body field VALUE you "
    "cannot derive from the context — an ungrounded value is a false failure.\n\n"
    # The assertion is driven by expected.assert — NEVER a hardcoded status. Guessing an
    # exact 200 for every happy case is precisely the bug this replaces (ADR-0063).
    "ASSERT ACCORDING TO `expected.assert`:\n"
    "- 'success_json' (happy, api): assert a success response with "
    "$response->assertSuccessful() (any 2xx — NEVER hardcode assertStatus(200)); if "
    "expected.shape lists keys, assert that structure via assertJsonStructure([...]), "
    "else assert the body is JSON ($this->assertIsArray($response->json())). If "
    "expected.shape has an `echo` object, ALSO assert the response echoes those exact "
    "field:value pairs via assertJsonFragment([...]) (you SENT them; matches inside a "
    "`data` wrapper too). Never assert a value NOT in `echo`.\n"
    "- 'reachable' (happy, web route or un-seedable path params): assert only that the "
    "app handled it without a server error, WITH the status in the message so it stays "
    "debuggable and triage-able (never a bare assertTrue) — "
    "`$status = $response->getStatusCode(); "
    '$this->assertLessThan(500, $status, "expected no server error, got HTTP '
    '{$status}");`. A 401/403/404 or a redirect (auth/config/missing-record '
    "precondition) is expected here and must NOT fail the test; only a 5xx does.\n"
    "- 'status' (rule-derived negative/auth): assert the EXACT expected.status via "
    "$response->assertStatus(expected.status). For a 422, ALSO assert the validation "
    "envelope reports the targeted field(s) via assertJsonValidationErrors([...]) from "
    "expected.shape.errors_for; for a 401, assert it is unauthorized.\n"
    "- 'redirect' (auth on a web route): assert $response->assertRedirect() — an "
    "unauthenticated web request is redirected to login, it is NOT a 401.\n"
    "- 'redirect_with_errors' (validation on a web route): assert "
    "$response->assertSessionHasErrors([...]) for expected.shape.errors_for — a web "
    "validation failure redirects back with session errors, it is NOT a 422 JSON body."
)
# Defense in depth: demand code-only output so there's nothing to strip. The
# extractor (extract.py) is the belt; this is the suspenders.
_CODE_ONLY = (
    " Output ONLY the PHP test file content, beginning with `<?php`. Do NOT wrap "
    "it in markdown fences and do NOT add any prose, explanation, or summary tables."
)
# When the target defines no model factories (ADR-0037), steer the model off them.
_NO_FACTORIES = (
    " The target application defines NO model factories: do NOT call `::factory()`. "
    "Create any required rows with explicit inserts, or rely on already-seeded data."
)
# When the target DOES define factories, steer the model to USE them for setup rows
# (the authenticated user, related records) rather than hand-writing column lists —
# guessing a column the table lacks (e.g. a `password` on a non-standard users table)
# fails the setup before the endpoint is even hit. Agnostic: factories encode each
# target's real schema, so this works for ANY project that ships them.
_USE_FACTORIES = (
    " The target application DEFINES model factories: create the authenticated user "
    "and any required related rows via their model factories "
    "(`User::factory()->create()`, `RelatedModel::factory()->create([...])`) — do NOT "
    "hand-write column lists for setup inserts."
)
# When a case carries DB dependencies (a payload foreign key that must reference an
# existing row), creation ORDER matters: a model factory often auto-creates its own
# related rows, which can grab the same primary-key id the dependency hardcodes. So:
# satisfy the dependencies FIRST, then create the authenticated user — its factory's
# auto-created relations then get fresh ids and never collide. Agnostic: applies to
# any project whose endpoints have foreign-key validation (`exists:...`).
_DEPENDENCY_ORDER = (
    " IMPORTANT setup order: create the listed DB-dependency rows FIRST (before the "
    "authenticated user), so the user factory's own auto-created related rows take "
    "fresh ids and do not collide with a dependency row's hardcoded id."
)
_FACTORY_SKIP_REASON = (
    "precondition seeding (model factories) unavailable on the target — deferred "
    "to B10"
)


def build_context(spec: EndpointSpec, case: PlannedCase) -> Subgraph:
    """Budget-capped grounding for the model — the plan + the real contract, serialized.

    Beyond the fixed request/expected pair, this hands the model the endpoint's actual
    validation rules and the case's intent/target field, so its self-analysis (and the
    assertions it derives) are grounded in the contract — never guessed. Structural
    only: rules and shape, never invented body values (ADR-0025 honesty stance).
    """
    snippet = json.dumps(
        {
            "endpoint": {
                "method": spec.method,
                "uri": spec.uri,
                "route_name": spec.route_name,
                "auth_required": spec.auth_required,
                # api (JSON) vs web (session/redirect) route — dictates the request
                # helper and the whole assertion style (ADR-0063).
                "is_api": spec.is_api,
                "path_params": spec.path_params,
                "query_params": spec.query_params,
                # The REAL validation contract — so a negative asserts the RIGHT field
                # against the RIGHT rule, and a happy case knows what a valid request
                # must satisfy. The model grounds assertions in these; it never invents.
                "validation": [
                    {
                        "field": vf.name,
                        "required": vf.required,
                        "type": vf.type,
                        "rules": vf.raw_rules,
                    }
                    for vf in spec.validation_fields
                ],
            },
            "case": {
                "name": case.name,
                "description": case.description,
                "type": case.case_type.value,
                "rule": case.rule,
                "target_field": case.target_field,
                "oracle_source": case.oracle_source.value,
            },
            "request": {
                "method": spec.method,
                "uri": spec.uri,
                "path_values": case.path_values,
                "authenticated": case.authenticated,
                "payload": case.payload,
            },
            "expected": {
                "status": case.expected.status,
                "shape": case.expected.shape,
                # HOW to assert (ADR-0063) — the renderer instruction maps each value
                # to the exact PHPUnit call. The status above is a representative hint
                # for the bands (success_json / reachable), and the exact code for the
                # status / redirect kinds.
                "assert": case.expected.expectation.value,
            },
            "dependencies": [asdict(dep) for dep in case.dependencies],
        },
        indent=2,
        sort_keys=True,
    )
    node = SubgraphNode(
        id=spec.route_name or spec.uri,
        kind="endpoint",
        name=f"{spec.method} {spec.uri}",
    )
    return Subgraph(nodes=[node], snippets=[snippet])


def _header(case: PlannedCase) -> str:
    lines = [
        f"// Generated test case: {case.name}",
        f"// oracle_source: {case.oracle_source.value}",
    ]
    if case.oracle_source is OracleSource.CHARACTERIZATION:
        lines.append(
            "// CHARACTERIZATION: pins the honest floor for the route's class "
            "(api CRUD 2xx+JSON / else handled without a 5xx), never a guessed status."
        )
        lines.append(
            "// It asserts NO specific body values — upgrade to spec-grounded "
            "once a requirement is ingested."
        )
    return "\n".join(lines)


def render_script(
    provider: AIProvider,
    spec: EndpointSpec,
    case: PlannedCase,
    budget_tokens: int,
    *,
    factories_available: bool = True,
) -> str:
    """Render a DIRECTLY-RUNNABLE PHPUnit test class from the model.

    Extracts the executable code from however the model wraps it (markdown prose
    snuck through before — B5 smoke), forces a deterministic globally-unique class
    name (so files don't collide in one runner invocation), assembles a valid PHP
    file, and — when the target has no factories — honestly skips a factory-dependent
    case rather than emitting one that hard-fails (ADR-0037).
    """
    instruction = _INSTRUCTION + _CODE_ONLY
    if factories_available:
        instruction += _USE_FACTORIES
        if case.dependencies:
            instruction += _DEPENDENCY_ORDER
    else:
        instruction += _NO_FACTORIES
    raw = provider.generate(instruction, build_context(spec, case), budget_tokens)
    code = extract_code(raw)
    if not factories_available:
        code = skip_if_uses_factory(code, _FACTORY_SKIP_REASON)
    seed = f"{spec.method} {spec.uri} {case.name}"
    code = rewrite_class_name(code, unique_class_name(case.name, seed))
    return with_php_header(code, _header(case))
