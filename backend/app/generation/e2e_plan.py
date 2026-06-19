"""PHASE 1 — deterministic E2E plan from a cross-layer journey (no AI).

Mirrors the backend planner (plan.py): pure Python derives the ordered steps and
the oracle-tagged assertions; the AIProvider later only *renders* them (phase 2).
From ``CrossLayerResolver.journey(page)`` we read the page node's captured form
metadata and build, per form: a happy case (fill valid values, submit, assert the
recorded post-submit state) plus one negative per required field (leave it empty,
submit, assert the validation error). A page with no form gets a single happy
"navigate + assert it rendered" case.

Oracle honesty (the differentiator, extended to the UI — see ADR-0017):
- a required-field validation error is grounded in something the app DECLARES
  (the ``required`` attribute) → ``rule-derived``;
- recorded post-submit / rendered state is ``characterization`` (weak) until a
  spec is ingested. Every assertion carries its ``oracle_source``; the AI never
  sets or changes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.enums import NodeKind, OracleSource, TestType
from app.models.model_node import ModelNode

from .errors import E2EPlanError

# Assertion kinds. ``validation_error`` checks a declared rule; ``recorded_state``
# checks observed post-submit/rendered state.
ASSERT_VALIDATION_ERROR = "validation_error"
ASSERT_RECORDED_STATE = "recorded_state"

# Deterministic valid values per input type — concrete, never AI-invented.
_VALID_VALUES: dict[str, str] = {
    "email": "user@example.com",
    "number": "1",
    "tel": "15555550123",
    "url": "https://example.com",
    "password": "Passw0rd1!",
    "date": "2026-01-01",
}


def _valid_value(field_type: str) -> str:
    return _VALID_VALUES.get(field_type.lower(), "sample text")


def _fill_step(field: dict[str, Any]) -> E2EStep:
    field_type = str(field.get("type", "text"))
    return E2EStep("fill", str(field["name"]), _valid_value(field_type))


@dataclass(frozen=True)
class E2EStep:
    action: str  # navigate | fill | submit
    target: str  # path | field name | form action/selector
    value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "target": self.target, "value": self.value}


@dataclass(frozen=True)
class E2EAssertion:
    kind: str
    target: str
    oracle_source: OracleSource

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "oracle_source": self.oracle_source.value,
        }


@dataclass(frozen=True)
class PlannedE2ECase:
    name: str
    case_type: TestType
    page_path: str
    steps: tuple[E2EStep, ...]
    assertions: tuple[E2EAssertion, ...]
    oracle_source: OracleSource  # the case's dominant oracle tier


def e2e_case_key(page_path: str, name: str) -> str:
    """Deterministic logical-case identity for an E2E case (mirrors compute_case_key).

    Stable across runs so re-generation matches the same logical case instead of
    duplicating it (the never-clobber basis, TRD §3 / T3.2).
    """
    return f"PAGE /{page_path.lstrip('/')}::e2e::{name}"


def _fields(form: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in form.get("fields", []) if isinstance(f, dict) and f.get("name")]


def _recorded_state_assertion(page: ModelNode, page_path: str) -> E2EAssertion:
    # A specific recorded indicator (the page's title, else its path) — a real
    # check, never the tautological "page loaded".
    target = str(page.attributes.get("title") or page_path)
    return E2EAssertion(ASSERT_RECORDED_STATE, target, OracleSource.CHARACTERIZATION)


def _happy_case(
    page: ModelNode, page_path: str, form: dict[str, Any] | None
) -> PlannedE2ECase:
    steps: list[E2EStep] = [E2EStep("navigate", page_path)]
    if form is not None:
        for field in _fields(form):
            steps.append(_fill_step(field))
        steps.append(E2EStep("submit", str(form.get("action") or "form")))
    return PlannedE2ECase(
        name="happy",
        case_type=TestType.E2E,
        page_path=page_path,
        steps=tuple(steps),
        assertions=(_recorded_state_assertion(page, page_path),),
        oracle_source=OracleSource.CHARACTERIZATION,
    )


def _required_negative_case(
    page_path: str, form: dict[str, Any], required: dict[str, Any]
) -> PlannedE2ECase:
    name = str(required["name"])
    steps: list[E2EStep] = [E2EStep("navigate", page_path)]
    for field in _fields(form):
        if field["name"] == name:
            continue  # leave the required field empty — that is the negative
        steps.append(_fill_step(field))
    steps.append(E2EStep("submit", str(form.get("action") or "form")))
    return PlannedE2ECase(
        name=f"{name}_required_missing",
        case_type=TestType.E2E,
        page_path=page_path,
        steps=tuple(steps),
        # Grounded in the declared ``required`` attribute → rule-derived.
        assertions=(
            E2EAssertion(ASSERT_VALIDATION_ERROR, name, OracleSource.RULE_DERIVED),
        ),
        oracle_source=OracleSource.RULE_DERIVED,
    )


def build_e2e_plan(journey: Any) -> list[PlannedE2ECase]:
    """Build the deterministic E2E plan from a journey subgraph (root = a page).

    ``journey`` is a ``CrossLayerResolver`` ``Subgraph``; typed as ``Any`` to
    avoid a hard import cycle (brain depends on nothing here). Raises
    ``E2EPlanError`` if the root is not a page node.
    """
    page: ModelNode = journey.root
    if page.kind is not NodeKind.PAGE:
        raise E2EPlanError(
            f"E2E plan needs a page node as the journey root, got {page.kind.value}"
        )
    page_path = str(page.attributes.get("path") or page.name)
    forms = [f for f in page.attributes.get("forms", []) if isinstance(f, dict)]

    cases: list[PlannedE2ECase] = []
    if not forms:
        cases.append(_happy_case(page, page_path, None))
        return cases
    for form in forms:
        cases.append(_happy_case(page, page_path, form))
        for field in _fields(form):
            if field.get("required"):
                cases.append(_required_negative_case(page_path, form, field))
    return cases
