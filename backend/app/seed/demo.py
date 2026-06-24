"""The demo dataset — a single isolated org populated so every UI screen renders.

ISOLATION. Everything lives under one demo organization (``DEMO_ORG_ID``) whose
members are demo users on the ``@demo.polaris.test`` domain. Seeding deletes that
org (DB-level ``ON DELETE CASCADE`` reaches projects → runs / results / findings /
finding_results / triage / test_cases / test_heals / jobs) and those users, then
rebuilds — so it is idempotent / re-runnable and never duplicates. A clean AAHOA
database is just ``make up`` with no seed; nothing here runs at startup.

REAL SHAPES. Rows are built from the same models the app writes, so a seeded
screen is indistinguishable from a real one. One deliberate, UI-invisible choice:
a run and its RUN job share a UUID (``Run.id == Job.id``), because the run list
returns ``run.id`` while the run-detail / triage endpoints resolve a Job by that
id — sharing the id keeps the seeded data navigable end to end.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.enums import (
    AuthoredBy,
    FindingLayer,
    JobKind,
    JobStatus,
    OracleSource,
    OrgRole,
    Outcome,
    RunMode,
    RunTrigger,
    TestLayer,
    TestType,
    TriageStatus,
)
from app.models.finding import Finding
from app.models.finding_result import FindingResult
from app.models.finding_triage import FindingTriage
from app.models.job import Job
from app.models.organization import Organization
from app.models.organization_invite import OrganizationInvite
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.result import Result
from app.models.run import Run
from app.models.test_case import TestCase
from app.models.test_heal import STATUS_CONFIRMED, TestHeal
from app.models.user import User

# A fixed namespace → deterministic ids, so a reseed reproduces the same rows.
DEMO_NS = uuid.UUID("d3105eed-0000-4000-8000-000000000001")
DEMO_ORG_ID = uuid.uuid5(DEMO_NS, "org")
DEMO_EMAIL_DOMAIN = "demo.polaris.test"
# The credentials a reviewer signs in with to see the populated screens.
DEMO_LOGIN_EMAIL = f"jordan@{DEMO_EMAIL_DOMAIN}"
DEMO_LOGIN_PASSWORD = "polaris-demo"


def _id(*parts: object) -> uuid.UUID:
    return uuid.uuid5(DEMO_NS, ":".join(str(p) for p in parts))


# --- declarative specs ------------------------------------------------------


@dataclass(frozen=True)
class FindingSpec:
    title: str
    severity: str  # critical / major / minor
    oracle: OracleSource  # the trust tier
    layer: FindingLayer  # ui / api / db
    history: str  # new / known / regression / flaky
    page: str
    endpoint: str | None = None
    table: str | None = None
    status_code: int | None = None
    triage: TriageStatus | None = None  # None → open (untriaged)
    explains: int = 1
    superseded: bool = False  # masked by a confirmed heal (reconciliation)
    confidence_mixed: bool = False


@dataclass(frozen=True)
class RunSpec:
    mode: RunMode
    trigger: RunTrigger
    status: str  # passed / failed / errored
    age: timedelta  # how long ago it finished
    pass_rate: float | None  # None for an errored run that produced no results
    detail: str  # the mode subtitle (branch / prompt)
    findings: tuple[FindingSpec, ...] = ()


@dataclass(frozen=True)
class ProjectSpec:
    name: str
    slug: str
    stack: str
    repo_url: str
    app_url: str
    runs: tuple[RunSpec, ...] = ()
    db_state_tier: str = "off"


# --- the dataset ------------------------------------------------------------


def _f(**kw: Any) -> FindingSpec:
    return FindingSpec(**kw)


# Acme Billing API — the flagship: every severity / tier / layer / history /
# triage state, populated blast paths, recurring keys for real history.
_ACME_LATEST = (
    _f(
        title="Orders accepted without authentication",
        severity="critical",
        oracle=OracleSource.RULE_DERIVED,
        layer=FindingLayer.API,
        history="new",
        page="/checkout",
        endpoint="POST /api/orders",
        table="orders",
        status_code=401,
        explains=3,
    ),
    _f(
        title="Payment captured before order validation",
        severity="critical",
        oracle=OracleSource.RULE_DERIVED,
        layer=FindingLayer.API,
        history="regression",
        page="/checkout",
        endpoint="POST /api/payments",
        table="payments",
        status_code=409,
        explains=2,
    ),
    _f(
        title="User PII exposed in API error responses",
        severity="critical",
        oracle=OracleSource.SPEC_GROUNDED,
        layer=FindingLayer.API,
        history="new",
        page="/account",
        endpoint="POST /api/account",
        status_code=422,
    ),
    _f(
        title="Password reset token never expires",
        severity="major",
        oracle=OracleSource.RULE_DERIVED,
        layer=FindingLayer.API,
        history="known",
        page="/forgot",
        endpoint="POST /api/password/reset",
        status_code=400,
        triage=TriageStatus.ACKNOWLEDGED,
    ),
    _f(
        title="Soft-deleted users still returned by the directory",
        severity="major",
        oracle=OracleSource.SPEC_GROUNDED,
        layer=FindingLayer.DB,
        history="known",
        page="/admin/users",
        endpoint="GET /api/users",
        table="users",
        confidence_mixed=True,
    ),
    _f(
        title="Checkout returns 500 on an empty cart",
        severity="major",
        oracle=OracleSource.CHARACTERIZATION,
        layer=FindingLayer.UI,
        history="regression",
        page="/checkout",
        endpoint="POST /api/checkout",
        status_code=500,
    ),
    _f(
        title="Invoice total rounds down by a cent",
        severity="minor",
        oracle=OracleSource.CHARACTERIZATION,
        layer=FindingLayer.API,
        history="flaky",
        page="/billing",
        endpoint="GET /api/invoices",
        status_code=200,
    ),
    _f(
        title="Order-list pagination skips the last row",
        severity="minor",
        oracle=OracleSource.SPEC_GROUNDED,
        layer=FindingLayer.API,
        history="known",
        page="/admin/orders",
        endpoint="GET /api/orders",
        status_code=200,
        triage=TriageStatus.RESOLVED,
    ),
    _f(
        title="Refund can exceed the original charge",
        severity="major",
        oracle=OracleSource.RULE_DERIVED,
        layer=FindingLayer.DB,
        history="new",
        page="/admin/orders",
        endpoint="POST /api/refunds",
        table="refunds",
        status_code=400,
    ),
    _f(
        title="Discount code applied twice on a network retry",
        severity="major",
        oracle=OracleSource.CHARACTERIZATION,
        layer=FindingLayer.API,
        history="known",
        page="/cart",
        endpoint="POST /api/cart/discount",
        status_code=200,
        triage=TriageStatus.WONT_FIX,
    ),
    _f(
        title="Tax line dropped for guest checkout",
        severity="minor",
        oracle=OracleSource.RULE_DERIVED,
        layer=FindingLayer.API,
        history="known",
        page="/checkout",
        endpoint="GET /api/cart/total",
        status_code=200,
        triage=TriageStatus.FALSE_POSITIVE,
    ),
)

# A couple of the latest-run keys recur in the prior run, so history (regression /
# known) and occurrence counts are real cross-run facts, not just a stored label.
_ACME_PRIOR = (
    _f(
        title="Payment captured before order validation",
        severity="critical",
        oracle=OracleSource.RULE_DERIVED,
        layer=FindingLayer.API,
        history="new",
        page="/checkout",
        endpoint="POST /api/payments",
        table="payments",
        status_code=409,
    ),
    _f(
        title="Checkout returns 500 on an empty cart",
        severity="major",
        oracle=OracleSource.CHARACTERIZATION,
        layer=FindingLayer.UI,
        history="new",
        page="/checkout",
        endpoint="POST /api/checkout",
        status_code=500,
    ),
    _f(
        title="Order-list pagination skips the last row",
        severity="minor",
        oracle=OracleSource.SPEC_GROUNDED,
        layer=FindingLayer.API,
        history="new",
        page="/admin/orders",
        endpoint="GET /api/orders",
        status_code=200,
    ),
)

_ANALYTICS_LATEST = (
    _f(
        title="Stale inventory shown after a purchase",
        severity="minor",
        oracle=OracleSource.CHARACTERIZATION,
        layer=FindingLayer.UI,
        history="flaky",
        page="/product",
        endpoint="GET /api/inventory",
        status_code=200,
    ),
    _f(
        title="Event timestamps stored without a timezone",
        severity="major",
        oracle=OracleSource.SPEC_GROUNDED,
        layer=FindingLayer.DB,
        history="new",
        page="/dashboards",
        endpoint="POST /api/events",
        table="events",
    ),
    _f(
        title="Duplicate events on at-least-once delivery",
        severity="major",
        oracle=OracleSource.CHARACTERIZATION,
        layer=FindingLayer.API,
        history="known",
        page="/dashboards",
        endpoint="POST /api/ingest",
        status_code=200,
        # A confirmed heal re-addressed this test → reconciliation supersedes it.
        superseded=True,
    ),
)

_ADMIN_LATEST = (
    _f(
        title="Bulk export ignores the role filter",
        severity="critical",
        oracle=OracleSource.RULE_DERIVED,
        layer=FindingLayer.API,
        history="new",
        page="/admin/export",
        endpoint="GET /api/export",
        table="audit_log",
        status_code=403,
    ),
    _f(
        title="Audit log missing the actor on impersonation",
        severity="major",
        oracle=OracleSource.SPEC_GROUNDED,
        layer=FindingLayer.DB,
        history="regression",
        page="/admin/audit",
        endpoint="POST /api/impersonate",
        table="audit_log",
    ),
)


def _project_specs() -> list[ProjectSpec]:
    """The demo projects, spanning every projects-list status + varied stacks."""
    return [
        # action_needed (latest run failed, open findings) — the flagship.
        ProjectSpec(
            name="Acme Billing API",
            slug="acme-billing-api",
            stack="Laravel",
            repo_url="github.com/acme/billing",
            app_url="https://staging.acme.test",
            db_state_tier="read_only",
            runs=(
                RunSpec(
                    RunMode.B,
                    RunTrigger.CHANGE_IMPACT,
                    "failed",
                    timedelta(minutes=4),
                    0.78,
                    "feat/checkout-refactor",
                    _ACME_LATEST,
                ),
                RunSpec(
                    RunMode.B,
                    RunTrigger.MANUAL,
                    "failed",
                    timedelta(hours=6),
                    0.81,
                    "full sweep",
                    _ACME_PRIOR,
                ),
                RunSpec(
                    RunMode.C,
                    RunTrigger.MANUAL,
                    "failed",
                    timedelta(days=1),
                    0.75,
                    '"orders require auth"',
                ),
                RunSpec(
                    RunMode.B,
                    RunTrigger.CHANGE_IMPACT,
                    "passed",
                    timedelta(days=2),
                    0.88,
                    "main",
                ),
            ),
        ),
        # passing (latest run all-green, no open findings).
        ProjectSpec(
            name="Storefront Web",
            slug="storefront-web",
            stack="Next.js",
            repo_url="github.com/acme/storefront",
            app_url="https://staging.shop.acme.test",
            runs=(
                RunSpec(
                    RunMode.B,
                    RunTrigger.MANUAL,
                    "passed",
                    timedelta(hours=2),
                    0.96,
                    "full sweep",
                ),
                RunSpec(
                    RunMode.B,
                    RunTrigger.CHANGE_IMPACT,
                    "failed",
                    timedelta(days=1),
                    0.91,
                    "feat/cart-v2",
                    (
                        _f(
                            title="Cart badge count drifts after removal",
                            severity="minor",
                            oracle=OracleSource.CHARACTERIZATION,
                            layer=FindingLayer.UI,
                            history="new",
                            page="/cart",
                            endpoint="GET /api/cart",
                            status_code=200,
                        ),
                    ),
                ),
            ),
        ),
        # action_needed (lighter) — includes a heal-superseded finding.
        ProjectSpec(
            name="Analytics Pipeline",
            slug="analytics-pipeline",
            stack="Go",
            repo_url="github.com/acme/analytics",
            app_url="https://staging.metrics.acme.test",
            db_state_tier="full",
            runs=(
                RunSpec(
                    RunMode.B,
                    RunTrigger.MANUAL,
                    "failed",
                    timedelta(hours=9),
                    0.84,
                    "full sweep",
                    _ANALYTICS_LATEST,
                ),
                RunSpec(
                    RunMode.B,
                    RunTrigger.MANUAL,
                    "passed",
                    timedelta(days=3),
                    0.9,
                    "main",
                ),
            ),
        ),
        # action_needed — internal admin.
        ProjectSpec(
            name="Internal Admin",
            slug="internal-admin",
            stack="Rails",
            repo_url="github.com/acme/admin",
            app_url="https://admin.acme.test",
            runs=(
                RunSpec(
                    RunMode.C,
                    RunTrigger.MANUAL,
                    "failed",
                    timedelta(days=1, hours=2),
                    0.8,
                    '"exports respect roles"',
                    _ADMIN_LATEST,
                ),
            ),
        ),
        # errored (latest run could not complete → no results / findings).
        ProjectSpec(
            name="Payments Gateway",
            slug="payments-gateway",
            stack="Django",
            repo_url="github.com/acme/payments",
            app_url="https://staging.pay.acme.test",
            runs=(
                RunSpec(
                    RunMode.B,
                    RunTrigger.MANUAL,
                    "errored",
                    timedelta(hours=3),
                    None,
                    "full sweep",
                ),
                RunSpec(
                    RunMode.B,
                    RunTrigger.MANUAL,
                    "failed",
                    timedelta(days=2),
                    0.86,
                    "main",
                    (
                        _f(
                            title="Webhook signature not verified",
                            severity="critical",
                            oracle=OracleSource.RULE_DERIVED,
                            layer=FindingLayer.API,
                            history="new",
                            page="/webhooks",
                            endpoint="POST /api/webhooks/stripe",
                            status_code=401,
                        ),
                    ),
                ),
            ),
        ),
        # never_run (registered, no runs yet).
        ProjectSpec(
            name="Mobile BFF",
            slug="mobile-bff",
            stack="Node",
            repo_url="github.com/acme/mobile-bff",
            app_url="https://staging.bff.acme.test",
        ),
    ]


# --- builders ---------------------------------------------------------------


def _evidence_slug(spec: FindingSpec) -> str:
    return spec.title.lower().replace(" ", "-")[:40]


def _location(spec: FindingSpec) -> dict[str, Any]:
    """The cross-layer blast path (page → endpoint → table) the ribbon renders."""
    location: dict[str, Any] = {"page": spec.page}
    if spec.endpoint:
        location["endpoints"] = [spec.endpoint]
    if spec.table:
        location["tables"] = [spec.table]
    return location


def _root_cause_key(spec: FindingSpec) -> str:
    """``{anchor}={value}#{signature}`` — the deepest failing node + failure shape."""
    if spec.layer is FindingLayer.DB and spec.table:
        anchor = f"table={spec.table}"
    elif spec.endpoint:
        anchor = f"endpoint={spec.endpoint}"
    else:
        anchor = f"page={spec.page}"
    signature = "fail"
    if spec.status_code is not None:
        signature += f"|status={spec.status_code}"
    return f"{anchor}#{signature}"


def _expected(spec: FindingSpec) -> dict[str, Any]:
    expected: dict[str, Any] = {"assertions": [{"kind": "status"}]}
    if spec.status_code is not None:
        expected["status"] = spec.status_code
    return expected


_TEST_LAYER = {
    FindingLayer.UI: TestLayer.UI,
    FindingLayer.API: TestLayer.API,
    FindingLayer.DB: TestLayer.INTEGRATION,
}


class _Rows:
    """Accumulated rows, kept per type so seeding can insert in FK-dependency order.

    The models declare no ORM relationships, so a single flush wouldn't order
    cross-table inserts (a result before its test case). Collecting by type and
    flushing in dependency order guarantees correctness.
    """

    def __init__(self) -> None:
        self.projects: list[Project] = []
        self.runs: list[Run] = []
        self.test_cases: list[TestCase] = []
        self.results: list[Result] = []
        self.findings: list[Finding] = []
        self.finding_results: list[FindingResult] = []
        self.triage: list[FindingTriage] = []
        self.heals: list[TestHeal] = []
        self.jobs: list[Job] = []


def _build_finding(
    rows: _Rows,
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    spec: FindingSpec,
    created_at: datetime,
) -> None:
    """One finding plus its real supporting chain (cases → results → join)."""
    key = _root_cause_key(spec)
    finding_id = _id("finding", run_id, key)
    expected = _expected(spec)
    rep_result_id: uuid.UUID | None = None
    members = max(spec.explains, 1)

    for member in range(members):
        case_id = _id("case", run_id, key, member)
        rows.test_cases.append(
            TestCase(
                id=case_id,
                project_id=project_id,
                type=TestType.NEGATIVE,
                layer=_TEST_LAYER[spec.layer],
                preconditions={},
                steps=[],
                expected=expected,
                oracle_source=spec.oracle,
                authored_by=AuthoredBy.AI,
                status="active",
                created_at=created_at,
            )
        )
        result_id = _id("result", run_id, key, member)
        rows.results.append(
            Result(
                id=result_id,
                project_id=project_id,
                run_id=run_id,
                test_case_id=case_id,
                outcome=Outcome.FAIL,
                evidence_ref=f"ev/{_evidence_slug(spec)}-{member}.zip",
                message=f"{spec.title}: assertion failed",
                created_at=created_at,
            )
        )
        if rep_result_id is None:
            rep_result_id = result_id
        else:
            rows.finding_results.append(
                FindingResult(
                    id=_id("fr", finding_id, result_id),
                    project_id=project_id,
                    finding_id=finding_id,
                    result_id=result_id,
                    created_at=created_at,
                )
            )

    assert rep_result_id is not None
    rows.findings.append(
        Finding(
            id=finding_id,
            project_id=project_id,
            run_id=run_id,
            result_id=rep_result_id,
            root_cause_key=key,
            explains_count=members,
            title=spec.title,
            layer=spec.layer,
            oracle_source=spec.oracle,
            confidence_mixed=spec.confidence_mixed,
            expected=expected,
            evidence_ref=f"ev/{_evidence_slug(spec)}.zip",
            location=_location(spec),
            severity=spec.severity,
            status=spec.history,
            created_at=created_at,
        )
    )
    rows.finding_results.append(
        FindingResult(
            id=_id("fr", finding_id, rep_result_id),
            project_id=project_id,
            finding_id=finding_id,
            result_id=rep_result_id,
            created_at=created_at,
        )
    )

    if spec.triage is not None and spec.triage is not TriageStatus.OPEN:
        rows.triage.append(
            FindingTriage(
                id=_id("triage", project_id, key),
                project_id=project_id,
                root_cause_key=key,
                status=spec.triage,
                note="Reviewed during demo triage.",
                triaged_at=created_at,
            )
        )

    if spec.superseded:
        # A confirmed addressing heal on this run+case masks the finding (B8
        # reconciliation): tagged on the dashboard, dropped from the inbox.
        rows.heals.append(
            TestHeal(
                id=_id("heal", run_id, key),
                project_id=project_id,
                run_id=run_id,
                test_case_id=_id("case", run_id, key, 0),
                kind="route_rebind",
                failure_class="location",
                before_addr=spec.endpoint or spec.page,
                after_addr=(spec.endpoint or spec.page) + "?v=2",
                rationale="Endpoint moved; re-addressed against the current model.",
                confidence="high",
                status=STATUS_CONFIRMED,
                healed_code="def test_placeholder():\n    assert True\n",
                resolved_by="demo",
                resolved_at=created_at,
            )
        )


def _build_run(
    rows: _Rows,
    *,
    project: Project,
    run_number: int,
    spec: RunSpec,
    now: datetime,
) -> None:
    finished_at = now - spec.age
    started_at = finished_at - timedelta(minutes=3)
    # Run and its RUN job share a UUID (see module docstring) so the run list
    # (run.id) and the job-keyed detail/triage endpoints line up.
    run_id = _id("run", project.slug, run_number)

    failures = len(spec.findings)
    passes = 0
    if spec.pass_rate is not None and spec.pass_rate < 1 and failures:
        passes = round(failures * spec.pass_rate / (1 - spec.pass_rate))
    elif spec.pass_rate is not None:
        passes = 20  # a green run with no findings still has passing results

    rows.runs.append(
        Run(
            id=run_id,
            project_id=project.id,
            run_number=run_number,
            trigger=spec.trigger,
            mode=spec.mode,
            commit_sha=(
                "a1b2c3d" if spec.trigger is RunTrigger.CHANGE_IMPACT else None
            ),
            status=spec.status,
            started_at=started_at,
            finished_at=finished_at,
            created_at=started_at,
        )
    )

    # Passing results (drive the live pass-rate the runs list computes).
    if passes:
        pass_case_id = _id("case", run_id, "passing")
        rows.test_cases.append(
            TestCase(
                id=pass_case_id,
                project_id=project.id,
                type=TestType.HAPPY,
                layer=TestLayer.API,
                preconditions={},
                steps=[],
                expected={},
                oracle_source=OracleSource.RULE_DERIVED,
                authored_by=AuthoredBy.AI,
                status="active",
                created_at=started_at,
            )
        )
        for i in range(passes):
            rows.results.append(
                Result(
                    id=_id("result", run_id, "pass", i),
                    project_id=project.id,
                    run_id=run_id,
                    test_case_id=pass_case_id,
                    outcome=Outcome.PASS,
                    created_at=finished_at,
                )
            )

    for finding in spec.findings:
        _build_finding(
            rows,
            project_id=project.id,
            run_id=run_id,
            spec=finding,
            created_at=finished_at,
        )

    # The RUN job: GET /runs/{id} returns job.summary; the dashboard reads it.
    rows.jobs.append(
        Job(
            id=run_id,
            kind=JobKind.RUN,
            status=(
                JobStatus.FAILED if spec.status == "errored" else JobStatus.SUCCEEDED
            ),
            project_id=project.id,
            mode={RunMode.B: "mode_b", RunMode.C: "mode_c"}.get(spec.mode, "mode_b"),
            payload={},
            run_id=run_id,
            summary={
                "pass_rate": spec.pass_rate,
                "failed": failures,
                "errors": 1 if spec.status == "errored" else 0,
                "project_id": str(project.id),
                "finished_at": finished_at.isoformat(),
                "target": project.name,
            },
            detail=spec.detail,
            finished_at=finished_at,
            created_at=started_at,
        )
    )


def _build_project(
    rows: _Rows,
    *,
    org_id: uuid.UUID,
    owner_id: uuid.UUID,
    spec: ProjectSpec,
    now: datetime,
) -> None:
    project = Project(
        id=_id("project", spec.slug),
        name=spec.name,
        slug=spec.slug,
        org_id=org_id,
        created_by=owner_id,
        app_url=spec.app_url,
        settings={"repo_url": spec.repo_url, "stack": spec.stack, "demo": True},
        db_state_tier=spec.db_state_tier,
        run_counter=len(spec.runs),
        created_at=now - timedelta(days=14),
    )
    rows.projects.append(project)
    # Newest run carries the highest number; build oldest → newest.
    ordered = sorted(spec.runs, key=lambda r: r.age, reverse=True)
    for number, run_spec in enumerate(ordered, start=1):
        _build_run(rows, project=project, run_number=number, spec=run_spec, now=now)


# --- entrypoint -------------------------------------------------------------


async def _clear(session: AsyncSession) -> None:
    """Remove any prior demo data (idempotent). DB cascades do the deep cleanup."""
    # Deleting the org cascades to projects → runs/results/findings/jobs/etc. and
    # to memberships + invites; deleting the demo users clears their accounts.
    await session.execute(delete(Organization).where(Organization.id == DEMO_ORG_ID))
    await session.execute(delete(User).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}")))
    await session.flush()


async def seed_demo(session: AsyncSession) -> None:
    """Clear and rebuild the isolated demo dataset, then commit."""
    now = datetime.now(UTC)
    await _clear(session)

    # Org → users → memberships + invite, flushed in FK order.
    session.add(Organization(id=DEMO_ORG_ID, name="Polaris Demo Co", is_personal=False))
    await session.flush()

    people = [
        ("jordan", "Jordan Lee", OrgRole.OWNER),
        ("sam", "Sam Rivera", OrgRole.ADMIN),
        ("alex", "Alex Chen", OrgRole.MEMBER),
        ("riley", "Riley Kim", OrgRole.VIEWER),
    ]
    password = hash_password(DEMO_LOGIN_PASSWORD)
    owner_id = _id("user", "jordan")
    for key, name, _role in people:
        session.add(
            User(
                id=_id("user", key),
                email=f"{key}@{DEMO_EMAIL_DOMAIN}",
                name=name,
                password_hash=password,
            )
        )
    await session.flush()
    for key, _name, role in people:
        session.add(
            OrganizationMember(
                id=_id("member", key),
                org_id=DEMO_ORG_ID,
                user_id=_id("user", key),
                role=role,
            )
        )
    # A pending invite so the team screen shows the "Invite pending" state.
    session.add(
        OrganizationInvite(
            id=_id("invite", "priya"),
            org_id=DEMO_ORG_ID,
            email=f"priya@{DEMO_EMAIL_DOMAIN}",
            role=OrgRole.MEMBER,
            token_hash=hashlib.sha256(b"demo-invite-priya").hexdigest(),
            expires_at=now + timedelta(days=7),
            accepted_at=None,
            invited_by=owner_id,
        )
    )
    await session.flush()

    rows = _Rows()
    for spec in _project_specs():
        _build_project(rows, org_id=DEMO_ORG_ID, owner_id=owner_id, spec=spec, now=now)

    # Insert in strict FK-dependency order (one flush per level).
    for batch in (
        rows.projects,
        rows.runs,
        rows.test_cases,
        rows.results,
        rows.findings,
        rows.finding_results,
        rows.triage,
        rows.heals,
        rows.jobs,
    ):
        session.add_all(batch)
        await session.flush()

    await session.commit()
