"""Typed pydantic request/response schemas for the v1 API (TRD §4).

The wire contract for the project + run + findings surface. The run body is a
discriminated union on ``mode`` so an unknown mode (or a change_impact request
without a changeset) fails validation as a typed 422 (ADR-0026).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field, model_validator


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
        raise ValueError("invalid email address")
    return value


# A lower-cased, lightly-validated email (no extra dependency; format is not the
# security boundary — the reset flow only matches stored records).
Email = Annotated[
    str, Field(min_length=3, max_length=320), AfterValidator(_normalize_email)
]


class ProjectCreate(BaseModel):
    """Register a project: its repo source, running app, and auth config ref.

    ``org_id`` chooses the owning team (ADR-0032); omit it to use the caller's
    personal org. The caller must have ``MANAGE_PROJECT`` in the target org.
    """

    name: str = Field(min_length=1, max_length=255)
    repo_url: str = Field(min_length=1, max_length=2048)
    app_url: str | None = Field(default=None, max_length=2048)
    auth_config_ref: str | None = Field(default=None, max_length=512)
    stack: str | None = Field(default=None, max_length=64)
    org_id: uuid.UUID | None = None


class ProjectUpdate(BaseModel):
    """Partial update for a project (PATCH). Only provided fields change.

    Sending a field as ``null`` clears it; omitting it leaves it untouched
    (resolved via ``exclude_unset`` at the handler).
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    repo_url: str | None = Field(default=None, min_length=1, max_length=2048)
    app_url: str | None = Field(default=None, max_length=2048)
    stack: str | None = Field(default=None, max_length=64)


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    repo_url: str
    app_url: str | None
    auth_config_ref: str | None
    stack: str | None = None
    created_at: datetime


# --- DB-state testing tier (B10, ADR-0043) ----------------------------------

DbStateTierLiteral = Literal["off", "read_only", "full"]


class DbStateTierResponse(BaseModel):
    """A project's DB-state-testing opt-in tier (off / read_only / full)."""

    project_id: uuid.UUID
    tier: str  # always one of DbStateTierLiteral; free str so the column maps cleanly


class DbStateTierUpdate(BaseModel):
    """Set a project's DB-state-testing tier. Bad value → 422; gated by RBAC.

    Raising to ``full`` only records intent; the non-prod safety gate (ADR-0043) is
    enforced at execution time, when a disposable target is actually written to.
    """

    tier: DbStateTierLiteral


# --- auth (B2) --------------------------------------------------------------


class SignUpRequest(BaseModel):
    email: Email
    password: str = Field(min_length=8, max_length=128)


class SignInRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None = None
    created_at: datetime


class AuthTokenResponse(BaseModel):
    """Sign-up / sign-in result: the bearer token + the authenticated user."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class PasswordResetRequestBody(BaseModel):
    email: Email


class PasswordResetConfirmBody(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=8, max_length=128)


# --- account profile (B3) ---------------------------------------------------


class ProfileUpdate(BaseModel):
    """Partial account-profile update (PATCH /auth/me). Only provided fields change.

    ``name`` may be sent as null to clear it; ``email`` (if provided) must be valid
    and unused.
    """

    name: str | None = Field(default=None, max_length=255)
    email: Email | None = None


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# --- organizations / membership / invites (B3, ADR-0032/0033) ---------------

# The role names on the wire (the OrgRole enum values).
OrgRoleName = Literal["owner", "admin", "member", "viewer"]


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_personal: bool
    role: OrgRoleName  # the caller's role in this org
    created_at: datetime


class OrgListResponse(BaseModel):
    items: list[OrgResponse]
    total: int


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str | None = None
    role: OrgRoleName
    created_at: datetime  # when they joined the org


class MemberListResponse(BaseModel):
    items: list[MemberResponse]
    total: int


class RoleUpdate(BaseModel):
    role: OrgRoleName


class InviteCreate(BaseModel):
    email: Email
    role: OrgRoleName = "member"


class InviteResponse(BaseModel):
    """A pending/accepted invite — deliberately WITHOUT the token (ADR-0033)."""

    id: uuid.UUID
    email: str
    role: OrgRoleName
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime


class InviteListResponse(BaseModel):
    items: list[InviteResponse]
    total: int


class InviteAccept(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class InviteAcceptResponse(BaseModel):
    org_id: uuid.UUID
    role: OrgRoleName


# --- operator status view (B4, ADR-0034/0035) -------------------------------


class QueueStatsResponse(BaseModel):
    """Cross-tenant queue snapshot for the operator view. ``queued`` is the depth;
    ``stuck`` is running past the threshold; ``runner_healthy`` is the at-a-glance
    signal (no stuck jobs)."""

    queued: int
    running: int
    succeeded: int
    failed: int
    cancelled: int
    stuck: int
    total: int
    runner_healthy: bool


class JobSummary(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    project_id: uuid.UUID
    mode: str | None = None
    attempts: int
    max_attempts: int
    detail: str | None = None
    created_at: datetime
    locked_at: datetime | None = None
    finished_at: datetime | None = None


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int


class IngestResponse(BaseModel):
    job_id: uuid.UUID
    status: str


class JobStatusResponse(BaseModel):
    job_id: uuid.UUID
    kind: str
    status: str
    run_id: uuid.UUID | None = None
    detail: str | None = None


class ModeBRunRequest(BaseModel):
    """Autonomous run: a selection strategy + (for change_impact) a changeset."""

    mode: Literal["mode_b"]
    strategy: Literal["full_sweep", "change_impact"]
    changeset: list[str] | None = None
    max_targets: int = Field(default=50, ge=1, le=1000)

    @model_validator(mode="after")
    def _require_changeset_for_change_impact(self) -> ModeBRunRequest:
        if self.strategy == "change_impact" and not self.changeset:
            raise ValueError("changeset is required for the change_impact strategy")
        return self


class ModeCRunRequest(BaseModel):
    """Natural-language authoring run."""

    mode: Literal["mode_c"]
    prompt: str = Field(min_length=1, max_length=4096)


# Discriminated on ``mode`` — an unknown mode is a 422, not a silent default.
RunCreate = Annotated[ModeBRunRequest | ModeCRunRequest, Field(discriminator="mode")]


class RunResponse(BaseModel):
    run_id: uuid.UUID  # the job handle the client polls
    status: str


class RunStatusResponse(BaseModel):
    run_id: uuid.UUID
    mode: str
    status: str
    summary: dict[str, Any] | None = None


class FindingLocationAnchor(BaseModel):
    """The deepest failing node (the grouping anchor) — what broke, structurally."""

    node_type: str | None = None  # a NodeKind value: table / endpoint / page
    identifier: str | None = None
    label: str


class FindingLocation(BaseModel):
    """The anchor plus the full cross-layer blast path the ribbon renders.

    The path is page → endpoint → model → table; ``models`` is additive and empty
    when the Brain didn't resolve the endpoint→model edge (the ribbon then renders
    the shorter page → endpoint → table path).
    """

    anchor: FindingLocationAnchor
    page: str | None = None
    endpoints: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """One failing test: a short "what failed" line and the trust signal.

    ``oracle_source`` (rule-derived / characterization / spec-grounded) is the
    point — it says how much to trust the failure, surfaced as a trust badge.
    """

    summary: str
    oracle_source: str
    reference: str | None = None


class FindingHistory(BaseModel):
    """Cross-run history: the T7.4 classification + its supporting fields."""

    classification: str  # new / known / regression / flaky
    occurrence_count: int
    first_seen_run: uuid.UUID | None = None
    last_seen_run: uuid.UUID | None = None


class TriageInfo(BaseModel):
    """A finding's current triage disposition (ADR-0027). Absent record = open.

    ``triaged_at`` is recorded; the actor (who triaged) is deferred to Tier-2 user
    auth — not faked here.
    """

    status: str  # a TriageStatus value
    note: str | None = None
    triaged_at: datetime | None = None


class TriagePatch(BaseModel):
    """Set a finding's triage disposition (PATCH body). Bad status → 422."""

    status: Literal["open", "acknowledged", "resolved", "wont_fix", "false_positive"]
    note: str | None = Field(default=None, max_length=2000)


class FindingResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID  # which project (the global inbox spans projects)
    run_id: uuid.UUID  # the run this finding row belongs to
    root_cause_key: str
    title: str
    layer: str
    severity: str
    status: str
    oracle_source: str
    explains_count: int
    confidence_mixed: bool
    # Widened detail the engine already computed (finding-detail drawer).
    expected: dict[str, Any]
    location: FindingLocation
    evidence: list[EvidenceItem]
    history: FindingHistory
    evidence_ref: str | None = None
    # Triage disposition, keyed by root_cause_key (ADR-0027); absent record = open.
    triage: TriageInfo
    # True when an active heal masks this finding (B8): a LOCATION failure that's
    # addressing drift ("test needs re-addressing"), not a broken app. Dropped from
    # the default inbox; reachable via the heals list or ``include_superseded``.
    superseded_by_heal: bool = False


class FindingsResponse(BaseModel):
    run_id: uuid.UUID
    count: int
    findings: list[FindingResponse]


class OpenFindingsResponse(BaseModel):
    """The currently-open findings inbox (ADR-0028), paginated, severity-ranked."""

    items: list[FindingResponse]
    total: int
    limit: int
    offset: int


class BulkTriageRequest(BaseModel):
    """Triage several findings at once (the inbox bulk action). Bad status → 422."""

    finding_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    status: Literal["open", "acknowledged", "resolved", "wont_fix", "false_positive"]
    note: str | None = Field(default=None, max_length=2000)


class BulkTriageResponse(BaseModel):
    """Outcome of a bulk triage: applied status + per-id partial-failure detail."""

    status: str
    requested: int
    updated: list[uuid.UUID]  # finding ids whose disposition was set
    not_found: list[uuid.UUID]  # finding ids that do not exist (partial failure)


# --- list endpoints ---------------------------------------------------------


class LastRunSummary(BaseModel):
    """A project's most-recent run, compactly (for the projects list)."""

    run_id: uuid.UUID
    mode: str
    status: str
    pass_rate: float | None = None  # passed / total over the run's results
    finished_at: datetime | None = None  # null while running / never finished
    created_at: datetime  # when the run was created (for relative-time display)


class ProjectListItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    repo_url: str
    app_url: str | None
    created_at: datetime
    # Widened, read-time summary fields (B-follow-up, ADR-0045). Additive: existing
    # list consumers ignore unknown fields; defaults cover a project with no runs.
    stack: str | None = None
    status: str = "never_run"  # overall: never_run / errored / action_needed / passing
    open_findings_count: int = 0  # the inbox's "currently open" count for this project
    last_run: LastRunSummary | None = None


class ProjectListResponse(BaseModel):
    items: list[ProjectListItem]
    total: int
    limit: int
    offset: int


class RunListItem(BaseModel):
    id: uuid.UUID
    mode: str
    status: str
    created_at: datetime
    pass_rate: float | None = None  # passed / total over the run's results


class RunListResponse(BaseModel):
    items: list[RunListItem]
    total: int
    limit: int
    offset: int


# --- business documents (B9) ------------------------------------------------

DocumentKind = Literal[
    "requirements", "api_contract", "user_flow", "acceptance_criteria", "other"
]


class DocumentCreate(BaseModel):
    """Attach a business document to a project (chunked + embedded into the Brain)."""

    title: str = Field(min_length=1, max_length=512)
    doc_kind: DocumentKind = "requirements"
    content: str = Field(min_length=1, max_length=1_000_000)  # no hard doc cap (B9)


class DocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    doc_kind: str
    chunk_count: int
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class SpecDivergenceResponse(BaseModel):
    """A concrete, high-confidence spec-vs-code divergence (B9, ADR-0039)."""

    id: uuid.UUID
    document_id: uuid.UUID
    kind: str
    spec_reference: str  # what the doc says ("X")
    code_observation: str  # what the code model shows ("Y")
    excerpt: str
    status: str
    created_at: datetime


class SpecDivergenceListResponse(BaseModel):
    items: list[SpecDivergenceResponse]
    total: int


# --- self-healing (B8, ADR-0040) --------------------------------------------


class HealResponse(BaseModel):
    """One proposed/confirmed addressing heal.

    ``trusted`` is the lower-trust marker made explicit: a freshly-proposed heal is
    untrusted (awaiting review); only a confirmed heal is trusted. Heals never
    change assertions — ``before_addr``/``after_addr`` are addressing only.
    """

    id: uuid.UUID
    run_id: uuid.UUID | None
    test_case_id: uuid.UUID
    kind: str
    failure_class: str
    before_addr: str
    after_addr: str
    rationale: str
    confidence: str
    status: str
    trusted: bool
    created_at: datetime


class HealListResponse(BaseModel):
    items: list[HealResponse]
    total: int


class HealScanResponse(BaseModel):
    """The honest post-run summary: N healed (review), M real findings, K unhealed."""

    run_id: uuid.UUID
    healed: int
    real_findings: int
    unhealed: int
    items: list[HealResponse]
