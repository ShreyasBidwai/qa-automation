"""``test_cases`` — versioned, project-scoped test cases (TRD §3)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProjectScopedMixin, pg_enum
from .enums import (
    AuthoredBy,
    CaseOrigin,
    OracleSource,
    ProposalStatus,
    TestLayer,
    TestType,
)


class TestCase(Base, ProjectScopedMixin):
    __tablename__ = "test_cases"
    __table_args__ = (
        Index("ix_test_cases_project_id_type", "project_id", "type"),
        # History lookups for a logical case (all versions of a lineage).
        Index("ix_test_cases_project_id_lineage_id", "project_id", "lineage_id"),
        # (Re)generation matching: find the lineage for a deterministic case_key.
        Index("ix_test_cases_project_id_case_key", "project_id", "case_key"),
        # EXACTLY ONE current version per (project_id, lineage_id), enforced at
        # the DB level (TRD §3 never-clobber): a partial unique index over the
        # current rows only. Appending a second current row for a lineage is
        # rejected by Postgres, so the invariant cannot be violated by any path.
        Index(
            "uq_test_cases_one_current",
            "project_id",
            "lineage_id",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
    )

    type: Mapped[TestType] = mapped_column(
        pg_enum(TestType, "test_type"), nullable=False
    )
    layer: Mapped[TestLayer] = mapped_column(
        pg_enum(TestLayer, "test_layer"), nullable=False
    )
    # References a Brain model_nodes.id once that table exists; FK deferred until then.
    target_node: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    preconditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    steps: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    expected: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    oracle_source: Mapped[OracleSource] = mapped_column(
        pg_enum(OracleSource, "oracle_source"), nullable=False
    )
    authored_by: Mapped[AuthoredBy] = mapped_column(
        pg_enum(AuthoredBy, "authored_by"), nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requirement_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'draft'")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Lineage: every version of one logical case shares ``lineage_id``. A brand-new
    # root case gets a fresh lineage from the server default; forks carry the
    # parent's lineage_id forward (see TestCaseRepository.new_version).
    lineage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        server_default=text("gen_random_uuid()"),
    )
    # The current-version pointer. Exactly one row per (project_id, lineage_id)
    # is current, enforced by the partial unique index in __table_args__.
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Per-version provenance: what produced *this* row. A fresh case is
    # "generated"; an edit appends an "edited" version. oracle_source is carried
    # forward as-is by an edit unless the edit itself changes the oracle (a
    # "human-vouched" oracle tier is a later refinement — not added now).
    origin: Mapped[CaseOrigin] = mapped_column(
        pg_enum(CaseOrigin, "case_origin"),
        nullable=False,
        server_default=text("'generated'"),
    )
    # Editor identity for edited versions; null for generated/backfilled rows.
    # The edit timestamp is the row's own ``created_at`` (each version is a new
    # row), so no separate column is needed.
    edited_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Deterministic identity of the logical case, derived from its plan (endpoint
    # + case type + targeted rule/field). Stable across runs, so re-generation
    # matches "the same logical case" by (project_id, case_key) instead of
    # duplicating it. Carried forward across versions; nullable for rows that
    # predate keying. See [[compute_case_key]] / [[CaseMergeService]].
    case_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Set only on ``origin="proposed"`` versions (a re-gen against a human-edited
    # case awaiting accept/reject); null otherwise.
    proposal_status: Mapped[ProposalStatus | None] = mapped_column(
        pg_enum(ProposalStatus, "proposal_status"), nullable=True
    )
