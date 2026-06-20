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


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    repo_url: str
    app_url: str | None
    auth_config_ref: str | None
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


class FindingResponse(BaseModel):
    id: uuid.UUID
    root_cause_key: str
    title: str
    layer: str
    severity: str
    status: str
    oracle_source: str
    explains_count: int


class FindingsResponse(BaseModel):
    run_id: uuid.UUID
    count: int
    findings: list[FindingResponse]
