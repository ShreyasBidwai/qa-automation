"""PHASE 2 — AI renders a Playwright ``.spec.ts`` AROUND the deterministic plan.

Mirrors render.py: the AIProvider assembles the executable spec, but the steps
and the assertions (and their ``oracle_source`` provenance) are FIXED by phase 1
and passed in the budget-capped context — the model never invents an assertion or
changes its meaning. An oracle-provenance header is prepended deterministically
so the oracle stance is explicit in the spec regardless of model output. Output
is executable by the T4.1 Playwright runner.
"""

from __future__ import annotations

import json

from app.ai.types import AIProvider, Subgraph, SubgraphNode

from .e2e_plan import PlannedE2ECase
from .extract import extract_code, with_comment_header

_INSTRUCTION = (
    "You are rendering ONE Playwright '.spec.ts' E2E test (TypeScript, importing "
    "from '@playwright/test'). Use EXACTLY the ordered steps and the assertions "
    "in the context below — navigate, fill each field, submit, then assert. Do "
    "NOT invent, add, weaken, or remove any assertion, and do NOT change what an "
    "assertion checks. A 'validation_error' assertion must check that the named "
    "field is reported invalid; a 'recorded_state' assertion must check the "
    "recorded post-submit/rendered state described. Emit only the spec — TypeScript "
    "only, no markdown fences and no prose."
)


def build_context(case: PlannedE2ECase) -> Subgraph:
    """Budget-capped grounding for the model — the plan, serialized."""
    snippet = json.dumps(
        {
            "name": case.name,
            "type": case.case_type.value,
            "page_path": case.page_path,
            "oracle_source": case.oracle_source.value,
            "steps": [step.to_dict() for step in case.steps],
            "assertions": [a.to_dict() for a in case.assertions],
        },
        indent=2,
        sort_keys=True,
    )
    node = SubgraphNode(id=case.page_path, kind="page", name=case.name)
    return Subgraph(nodes=[node], snippets=[snippet])


def _header(case: PlannedE2ECase) -> str:
    lines = [
        f"// Generated E2E case: {case.name}",
        f"// page: {case.page_path}",
        f"// oracle_source: {case.oracle_source.value}",
        "// assertion provenance (set deterministically, not by the model):",
    ]
    for assertion in case.assertions:
        lines.append(
            f"//   - {assertion.kind} [{assertion.target}]: "
            f"{assertion.oracle_source.value}"
        )
    return "\n".join(lines)


def render_e2e_spec(
    provider: AIProvider, case: PlannedE2ECase, budget_tokens: int
) -> str:
    """Render a directly-runnable Playwright spec (markdown/prose extracted out)."""
    raw = provider.generate(_INSTRUCTION, build_context(case), budget_tokens)
    return with_comment_header(extract_code(raw), _header(case))
