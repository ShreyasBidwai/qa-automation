"""PHASE 2 — AI renders the Pest code AROUND the deterministic plan.

The AIProvider assembles auth setup, the HTTP call, and assertions, but the
payload and expected status are FIXED by PHASE 1 and passed in the
budget-capped Subgraph context — the model never invents them. A characterization
header is prepended deterministically so the oracle stance is always explicit,
independent of model output.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from app.ai.types import AIProvider, Subgraph, SubgraphNode
from app.ingestion.models import EndpointSpec
from app.models.enums import OracleSource

from .plan import PlannedCase

_INSTRUCTION = (
    "You are rendering ONE Laravel/Pest feature test for an API endpoint. "
    "Use EXACTLY the HTTP request (method, URI, path values, payload) and the "
    "expected status given in the context below. Do NOT invent or change any "
    "payload value or the expected status — only assemble the auth setup, the "
    "HTTP call, and the assertions around them. For a 'characterization' case, "
    "assert ONLY the success status and that the response body is a JSON object "
    "— never assert specific body field values. For a 'rule-derived' case, "
    "assert the exact expected status and, for 422s, that the validation error "
    "envelope reports the targeted field(s)."
)


def build_context(spec: EndpointSpec, case: PlannedCase) -> Subgraph:
    """Budget-capped grounding for the model — the plan, serialized."""
    snippet = json.dumps(
        {
            "endpoint": {
                "method": spec.method,
                "uri": spec.uri,
                "route_name": spec.route_name,
                "auth_required": spec.auth_required,
            },
            "case": {
                "name": case.name,
                "type": case.case_type.value,
                "rule": case.rule,
                "oracle_source": case.oracle_source.value,
            },
            "request": {
                "method": spec.method,
                "uri": spec.uri,
                "path_values": case.path_values,
                "authenticated": case.authenticated,
                "payload": case.payload,
            },
            "expected": {"status": case.expected.status, "shape": case.expected.shape},
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
            "// CHARACTERIZATION: asserts only the success status + structural "
            "shape (body is JSON)."
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
) -> str:
    body = provider.generate(_INSTRUCTION, build_context(spec, case), budget_tokens)
    return f"{_header(case)}\n\n{body}"
