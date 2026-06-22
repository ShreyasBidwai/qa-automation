"""Spec-grounded oracles (B9) — honest doc grounding.

A case whose field is documented in the project's docs is upgraded to
spec-grounded; a case whose field is NOT documented is left unchanged — even though
docs exist (the honesty requirement). Deterministic, no model.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.grounding import SpecGroundingService
from app.documents.service import DocumentService
from app.embeddings.stub import StubEmbeddingProvider
from app.generation.plan import plan_cases
from app.models.enums import OracleSource
from tests.factories import make_project


async def _project(db_session: AsyncSession):  # type: ignore[no-untyped-def]
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    return project


async def test_documented_field_is_spec_grounded_others_unchanged(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project = await _project(db_session)
    provider = StubEmbeddingProvider()

    # A doc that documents the `email` field (a real contract), but says nothing
    # about `age` or `country_id`.
    await DocumentService(db_session, embedding_provider=provider).add_document(
        project_id=project.id,
        title="User contract",
        doc_kind="api_contract",
        content="The email address must be unique across all users.",
    )

    cases = plan_cases(endpoint_spec)  # type: ignore[arg-type]
    grounder = SpecGroundingService(db_session, embedding_provider=provider)
    grounded = await grounder.ground(
        project_id=project.id, spec=endpoint_spec, cases=cases  # type: ignore[arg-type]
    )

    by_field = {(c.target_field, c.rule): c for c in grounded}
    # A case targeting the DOCUMENTED field is upgraded to the blue tier.
    email_cases = [c for c in grounded if c.target_field == "email"]
    assert email_cases and all(
        c.oracle_source is OracleSource.SPEC_GROUNDED for c in email_cases
    )
    # A case for an UNDOCUMENTED field is left as the plan tagged it (not upgraded).
    age_cases = [c for c in grounded if c.target_field == "age"]
    assert age_cases and all(
        c.oracle_source is not OracleSource.SPEC_GROUNDED for c in age_cases
    )
    assert by_field  # sanity


async def test_no_documents_grounds_nothing(
    db_session: AsyncSession, endpoint_spec: object
) -> None:
    project = await _project(db_session)
    cases = plan_cases(endpoint_spec)  # type: ignore[arg-type]
    before = [c.oracle_source for c in cases]

    grounder = SpecGroundingService(
        db_session, embedding_provider=StubEmbeddingProvider()
    )
    grounded = await grounder.ground(
        project_id=project.id, spec=endpoint_spec, cases=cases  # type: ignore[arg-type]
    )
    # No docs → nothing is spec-grounded; oracle stances are untouched.
    assert [c.oracle_source for c in grounded] == before
    assert not any(c.oracle_source is OracleSource.SPEC_GROUNDED for c in grounded)
