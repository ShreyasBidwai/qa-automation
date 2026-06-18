"""Mode A — human authoring + deterministic-first scripting (T3 Mode A).

Exercises CaseAuthoringService: authoring creates a fresh authored lineage with
full provenance; authored cases edit and re-generate exactly like any other
versioned case (history preserved, never clobbered); and scripting is
deterministic-first — a simple case renders from the template with NO AI call,
while a complex one falls back to the T1.4 AI render. The AI provider is a
counting stub so "no AI call" is asserted directly. Project-scoped throughout.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stub import StubAIProvider
from app.ai.types import FailureEvidence, Subgraph, TriageLabel
from app.generation.authored import (
    AuthoredCaseSpec,
    AuthoredEndpoint,
    DbSetup,
    is_template_renderable,
    render_pest_template,
)
from app.generation.generator import TestGenerator
from app.models.enums import (
    AuthoredBy,
    CaseOrigin,
    OracleSource,
    ProposalStatus,
    TestType,
)
from app.models.test_case import TestCase
from app.repositories.test_case_repository import TestCaseRepository
from app.services.case_authoring_service import CaseAuthoringService
from app.services.errors import InvalidCaseSpecError
from app.services.test_case_service import TestCaseService
from tests.factories import make_project

_ALL_FIELDS = (
    "id",
    "project_id",
    "lineage_id",
    "parent_version_id",
    "version",
    "type",
    "layer",
    "target_node",
    "preconditions",
    "steps",
    "expected",
    "oracle_source",
    "authored_by",
    "edited_by_human",
    "requirement_link",
    "status",
    "origin",
    "edited_by",
    "case_key",
    "proposal_status",
    "resolved_by",
    "resolved_at",
    "is_current",
    "created_at",
    "updated_at",
)


class _CountingProvider:
    """An AIProvider that counts generate() calls (delegates to the stub)."""

    def __init__(self) -> None:
        self.calls = 0
        self._inner = StubAIProvider()

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str:
        self.calls += 1
        return self._inner.generate(prompt, context, budget_tokens)

    def triage(self, failure: FailureEvidence) -> TriageLabel:
        return self._inner.triage(failure)


def _snapshot(tc: TestCase) -> dict[str, Any]:
    return {f: copy.deepcopy(getattr(tc, f)) for f in _ALL_FIELDS}


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


def _simple_spec(**overrides: Any) -> AuthoredCaseSpec:
    """A structurally simple authored case (template-renderable, no DB setup)."""
    base: dict[str, Any] = dict(
        name="missing_name",
        type=TestType.NEGATIVE,
        endpoint=AuthoredEndpoint("POST", "api/users", "users.store"),
        expected_status=422,
        oracle_source=OracleSource.RULE_DERIVED,
        payload={"email": "a@b.com", "age": 30},
        expected_shape={"validation_errors": ["name"]},
    )
    base.update(overrides)
    return AuthoredCaseSpec(**base)


def _complex_spec(**overrides: Any) -> AuthoredCaseSpec:
    """A case needing app-specific DB setup → AI fallback."""
    base: dict[str, Any] = dict(
        name="happy",
        type=TestType.HAPPY,
        endpoint=AuthoredEndpoint("POST", "api/users", "users.store"),
        expected_status=201,
        oracle_source=OracleSource.CHARACTERIZATION,
        auth_required=True,
        authenticated=True,
        payload={"name": "Ada", "email": "ada@example.com", "age": 30},
        db_setup=[DbSetup(kind="row_present", table="countries", column="id", value=1)],
    )
    base.update(overrides)
    return AuthoredCaseSpec(**base)


def _authoring(
    session: AsyncSession, provider: Any | None = None
) -> CaseAuthoringService:
    return CaseAuthoringService(
        session, provider=provider or StubAIProvider(), budget_tokens=2048
    )


# --- authoring ---------------------------------------------------------------


async def test_create_case_starts_authored_v1_current_with_provenance(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    authored = await _authoring(db_session).create_case(
        project_id, _simple_spec(), authored_by="alice"
    )
    tc = authored.test_case

    # New lineage, version 1, current, origin=authored.
    assert tc.version == 1
    assert tc.parent_version_id is None
    assert tc.is_current is True
    assert tc.origin is CaseOrigin.AUTHORED
    assert tc.lineage_id is not None
    # Full human provenance.
    assert tc.edited_by_human is True
    assert tc.authored_by is AuthoredBy.HUMAN
    assert tc.edited_by == "alice"
    assert tc.created_at is not None
    # Standard case fields carried, human-set oracle.
    assert tc.expected == {"status": 422, "shape": {"validation_errors": ["name"]}}
    assert tc.oracle_source is OracleSource.RULE_DERIVED
    # case_key computed (targets a known endpoint+type) → re-gen can recognize it.
    assert tc.case_key == "POST /api/users::negative::missing_name"

    # Project-scoped: the case exists only in its project.
    repo = TestCaseRepository(db_session)
    assert await repo.count(project_id) == 1
    other = await _project(db_session)
    assert await repo.count(other) == 0
    assert await repo.get_current(other, tc.lineage_id) is None


async def test_free_form_authored_case_has_null_case_key(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    authored = await _authoring(db_session).create_case(
        project_id, _simple_spec(keyed=False), authored_by="alice"
    )
    assert authored.test_case.case_key is None


async def test_invalid_spec_raises_typed_error(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    svc = _authoring(db_session)
    bad_specs = [
        _simple_spec(name="  "),  # blank name
        _simple_spec(expected_status=99),  # status out of HTTP range
        _simple_spec(endpoint=AuthoredEndpoint("", "api/users")),  # no method
        _simple_spec(endpoint=AuthoredEndpoint("POST", "  ")),  # no URI
    ]
    for bad in bad_specs:
        with pytest.raises(InvalidCaseSpecError):
            await svc.create_case(project_id, bad, authored_by="alice")


async def test_authored_case_is_editable_history_retained(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    authored = await _authoring(db_session).create_case(
        project_id, _simple_spec(), authored_by="alice"
    )
    lineage_id = authored.test_case.lineage_id

    # Edit through the existing T3.1 service → a new edited version.
    v2 = await TestCaseService(db_session).edit(
        project_id,
        lineage_id,
        {"status": "active", "expected": {"status": 200, "shape": {}}},
        edited_by="bob",
    )
    assert v2.version == 2
    assert v2.origin is CaseOrigin.EDITED
    assert v2.is_current is True

    history = await TestCaseRepository(db_session).get_history(project_id, lineage_id)
    assert [h.version for h in history] == [1, 2]
    v1 = history[0]
    await db_session.refresh(v1)
    # The authored original is retained, demoted, content untouched.
    assert v1.origin is CaseOrigin.AUTHORED
    assert v1.is_current is False
    assert v1.expected == {"status": 422, "shape": {"validation_errors": ["name"]}}


# --- clobber-protection (re-gen against an authored case) --------------------


async def test_regen_against_authored_case_proposes_never_clobbers(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project_id = await _project(db_session)
    # Author the happy case so its key matches what generation will compute.
    authored = await _authoring(db_session).create_case(
        project_id,
        _complex_spec(name="happy"),  # keyed; happy → "POST /api/users::happy::happy"
        authored_by="alice",
    )
    lineage_id = authored.test_case.lineage_id
    assert authored.test_case.case_key == "POST /api/users::happy::happy"
    before = _snapshot(authored.test_case)

    # Re-generate the whole endpoint through the real generator + merge engine.
    gen = TestGenerator(
        provider=StubAIProvider(), budget_tokens=2048, generated_by="stub"
    )
    results = await gen.generate_and_persist(
        session=db_session, project_id=project_id, spec=endpoint_spec  # type: ignore[arg-type]
    )
    happy = next(r for r in results if r.plan.name == "happy")
    assert happy.action == "proposed"  # matched the authored case → proposed
    assert all(r.action == "created" for r in results if r.plan.name != "happy")

    # The authored case is still the sole current version, byte-for-byte unchanged.
    repo = TestCaseRepository(db_session)
    current = await repo.get_current(project_id, lineage_id)
    assert current is not None and current.id == authored.test_case.id
    await db_session.refresh(authored.test_case)
    assert _snapshot(authored.test_case) == before

    history = await repo.get_history(project_id, lineage_id)
    assert sum(h.is_current for h in history) == 1
    proposal = next(h for h in history if h.origin is CaseOrigin.PROPOSED)
    assert proposal.proposal_status is ProposalStatus.PENDING
    assert proposal.is_current is False


# --- deterministic-first scripting -------------------------------------------


async def test_simple_case_renders_via_template_without_calling_ai(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    provider = _CountingProvider()
    authored = await _authoring(db_session, provider).create_case(
        project_id, _simple_spec(), authored_by="alice"
    )
    script = authored.test_script

    assert script.deterministic is True
    assert script.generated_by == "template"
    assert provider.calls == 0  # THE assertion: deterministic path makes NO AI call

    code = script.code
    assert code.startswith("<?php")
    assert "test('missing_name'" in code
    assert "$this->postJson('/api/users', [" in code
    assert "'age' => 30," in code  # payload rendered deterministically (sorted)
    assert "$response->assertStatus(422);" in code
    assert "$response->assertJsonValidationErrors(['name']);" in code


async def test_complex_case_falls_back_to_ai(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    provider = _CountingProvider()
    authored = await _authoring(db_session, provider).create_case(
        project_id, _complex_spec(), authored_by="alice"
    )
    script = authored.test_script

    assert script.deterministic is False
    assert provider.calls == 1  # the AI provider rendered this one
    assert script.generated_by == "_CountingProvider"
    assert "stub-generated by StubAIProvider" in script.code  # via the AI path


# --- the simple/complex predicate + template rendering (pure, no DB) ---------


def test_is_template_renderable_discriminates_simple_from_complex() -> None:
    assert is_template_renderable(_simple_spec()) is True
    # DB setup → app-specific knowledge needed.
    assert is_template_renderable(_complex_spec()) is False
    # GET with a body (getJson's 2nd arg is headers, not a body).
    assert (
        is_template_renderable(
            _simple_spec(
                endpoint=AuthoredEndpoint("GET", "api/users"), payload={"q": 1}
            )
        )
        is False
    )
    # Unresolved path placeholder → needs substitution knowledge.
    assert (
        is_template_renderable(
            _simple_spec(endpoint=AuthoredEndpoint("GET", "api/users/{id}"), payload={})
        )
        is False
    )
    # Unknown HTTP method → no deterministic helper.
    assert (
        is_template_renderable(
            _simple_spec(endpoint=AuthoredEndpoint("TRACE", "api/users"), payload={})
        )
        is False
    )
    # A resolved path param is simple again.
    assert (
        is_template_renderable(
            _simple_spec(
                endpoint=AuthoredEndpoint("GET", "api/users/{id}"),
                payload={},
                path_values={"id": 7},
                expected_shape={"json_structure": ["id", "email"]},
            )
        )
        is True
    )


def test_template_renders_varied_payload_types_deterministically() -> None:
    spec = _simple_spec(
        name="create_thing",
        type=TestType.HAPPY,
        endpoint=AuthoredEndpoint("POST", "api/things"),
        expected_status=201,
        oracle_source=OracleSource.CHARACTERIZATION,
        payload={
            "active": True,
            "deleted": False,
            "note": None,
            "qty": 3,
            "meta": {"k": "v"},
            "tags": ["a", "b"],
        },
        expected_shape={"json_structure": ["id", "active"]},
    )
    code = render_pest_template(spec)
    assert code.startswith("<?php")
    assert "$this->postJson('/api/things', [" in code
    assert "'active' => true," in code
    assert "'deleted' => false," in code
    assert "'note' => null," in code
    assert "'qty' => 3," in code
    assert "'meta' => ['k' => 'v']," in code  # nested assoc array
    assert "'tags' => ['a', 'b']," in code  # nested list
    assert "$response->assertStatus(201);" in code
    assert "$response->assertJsonStructure(['id', 'active']);" in code


def test_template_renders_authenticated_get_with_default_shape() -> None:
    spec = _simple_spec(
        name="list_things",
        type=TestType.SMOKE,
        endpoint=AuthoredEndpoint("GET", "api/things"),
        expected_status=200,
        oracle_source=OracleSource.CHARACTERIZATION,
        authenticated=True,
        payload={},
        expected_shape={},
    )
    assert is_template_renderable(spec) is True
    code = render_pest_template(spec)
    assert "$this->actingAs(\\App\\Models\\User::query()->firstOrFail());" in code
    assert "$response = $this->getJson('/api/things');" in code  # no body argument
    assert "expect($response->json())->toBeArray();" in code  # default shape assertion
