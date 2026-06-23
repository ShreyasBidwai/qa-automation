"""The demo seed builds a real, isolated, idempotent dataset (demo-only).

Runs the seed against the per-test transaction (rolled back at teardown) and
asserts it populates one isolated org with the variety every UI screen needs —
and that re-running clears + rebuilds rather than duplicating.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FindingLayer, OracleSource, OrgRole, TriageStatus
from app.models.finding import Finding
from app.models.finding_triage import FindingTriage
from app.models.job import Job
from app.models.organization import Organization
from app.models.organization_invite import OrganizationInvite
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.run import Run
from app.models.test_heal import STATUS_CONFIRMED, TestHeal
from app.models.user import User
from app.seed.demo import DEMO_LOGIN_EMAIL, DEMO_ORG_ID, seed_demo


async def test_seed_builds_an_isolated_populated_demo_org(db_session: AsyncSession) -> None:
    await seed_demo(db_session)

    org = await db_session.get(Organization, DEMO_ORG_ID)
    assert org is not None and not org.is_personal

    # The reviewer's sign-in account exists.
    login = (
        await db_session.scalars(select(User).where(User.email == DEMO_LOGIN_EMAIL))
    ).first()
    assert login is not None

    # Team: one of each role + a pending invite.
    members = (
        await db_session.scalars(
            select(OrganizationMember).where(OrganizationMember.org_id == DEMO_ORG_ID)
        )
    ).all()
    assert {m.role for m in members} == {
        OrgRole.OWNER,
        OrgRole.ADMIN,
        OrgRole.MEMBER,
        OrgRole.VIEWER,
    }
    invites = (
        await db_session.scalars(
            select(OrganizationInvite).where(OrganizationInvite.org_id == DEMO_ORG_ID)
        )
    ).all()
    assert len(invites) == 1 and invites[0].accepted_at is None

    # Projects span the list statuses — a never-run one carries no runs.
    projects = (
        await db_session.scalars(select(Project).where(Project.org_id == DEMO_ORG_ID))
    ).all()
    assert len(projects) >= 5
    by_slug = {p.slug: p for p in projects}
    never_run_id = by_slug["mobile-bff"].id
    assert (
        await db_session.scalars(select(Run).where(Run.project_id == never_run_id))
    ).all() == []

    # Every run has a RUN job under the SAME id, so the run list links resolve.
    runs = (await db_session.scalars(select(Run))).all()
    assert runs
    for run in runs:
        job = await db_session.get(Job, run.id)
        assert job is not None and job.run_id == run.id

    # Findings cover the full matrix the UI must render.
    findings = (await db_session.scalars(select(Finding))).all()
    assert len(findings) >= 12
    assert {f.severity for f in findings} >= {"critical", "major", "minor"}
    assert {f.oracle_source for f in findings} >= {
        OracleSource.RULE_DERIVED,
        OracleSource.CHARACTERIZATION,
        OracleSource.SPEC_GROUNDED,
    }
    assert {f.layer for f in findings} >= {
        FindingLayer.UI,
        FindingLayer.API,
        FindingLayer.DB,
    }
    assert {f.status for f in findings} >= {"new", "known", "regression", "flaky"}
    # Populated cross-layer blast paths (page → endpoint → table).
    assert any(f.location.get("endpoints") for f in findings)
    assert any(f.location.get("tables") for f in findings)

    # Every triage disposition + a heal-superseded finding (reconciliation).
    triage = (await db_session.scalars(select(FindingTriage))).all()
    assert {t.status for t in triage} >= {
        TriageStatus.ACKNOWLEDGED,
        TriageStatus.RESOLVED,
        TriageStatus.WONT_FIX,
        TriageStatus.FALSE_POSITIVE,
    }
    heals = (await db_session.scalars(select(TestHeal))).all()
    assert any(h.status == STATUS_CONFIRMED for h in heals)


async def test_seed_is_idempotent(db_session: AsyncSession) -> None:
    await seed_demo(db_session)
    projects_first = len(
        (
            await db_session.scalars(
                select(Project).where(Project.org_id == DEMO_ORG_ID)
            )
        ).all()
    )
    findings_first = len((await db_session.scalars(select(Finding))).all())

    await seed_demo(db_session)  # clears + rebuilds, never duplicates
    projects_second = len(
        (
            await db_session.scalars(
                select(Project).where(Project.org_id == DEMO_ORG_ID)
            )
        ).all()
    )
    findings_second = len((await db_session.scalars(select(Finding))).all())

    assert projects_first == projects_second
    assert findings_first == findings_second
