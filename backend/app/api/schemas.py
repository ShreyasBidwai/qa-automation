"""Typed pydantic request/response schemas for the v1 API (TRD §4).

The wire contract for the project + run + findings surface. The run body is a
discriminated union on ``mode`` so an unknown mode (or a change_impact request
without a changeset) fails validation as a typed 422 (ADR-0026).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class ProjectCreate(BaseModel):
    """Register a project: its repo source, running app, and auth config ref."""

    name: str = Field(min_length=1, max_length=255)
    repo_url: str = Field(min_length=1, max_length=2048)
    app_url: str | None = Field(default=None, max_length=2048)
    auth_config_ref: str | None = Field(default=None, max_length=512)
    stack: str | None = Field(default=None, max_length=64)


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
    """The anchor plus the full cross-layer blast path the ribbon renders."""

    anchor: FindingLocationAnchor
    page: str | None = None
    endpoints: list[str] = Field(default_factory=list)
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


class ProjectListItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    repo_url: str
    app_url: str | None
    created_at: datetime


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
