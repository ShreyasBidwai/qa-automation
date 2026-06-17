"""core test data model: test_cases, test_scripts, runs, results

Revision ID: 0002_core_test_data_model
Revises: 0001_init_projects
Create Date: 2026-06-17

Forward-only and additive (Standards §14): only CREATEs — enum types, four
project-scoped tables, and their FK/composite indexes. No destructive ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_core_test_data_model"
down_revision: str | None = "0001_init_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types created explicitly (create_type=False on the column references).
# Values are the TRD §3 contract strings.
test_type = postgresql.ENUM(
    "smoke", "happy", "negative", "edge", "e2e", "journey", "profile",
    name="test_type", create_type=False,
)
test_layer = postgresql.ENUM(
    "api", "ui", "integration", name="test_layer", create_type=False
)
oracle_source = postgresql.ENUM(
    "rule-derived", "characterization", "spec-grounded",
    name="oracle_source", create_type=False,
)
authored_by = postgresql.ENUM("ai", "human", name="authored_by", create_type=False)
framework = postgresql.ENUM(
    "pest", "pytest", "playwright", name="framework", create_type=False
)
run_trigger = postgresql.ENUM(
    "manual", "ci", "change-impact", name="run_trigger", create_type=False
)
run_mode = postgresql.ENUM("A", "B", "C", name="run_mode", create_type=False)
outcome = postgresql.ENUM("pass", "fail", "error", name="outcome", create_type=False)
triage = postgresql.ENUM(
    "real-bug", "bad-test", "flaky", "infra", "unknown",
    name="triage", create_type=False,
)

_ENUMS = (
    test_type, test_layer, oracle_source, authored_by, framework,
    run_trigger, run_mode, outcome, triage,
)

_UUID = postgresql.UUID(as_uuid=True)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "test_cases",
        *_audit_columns(),
        sa.Column("type", test_type, nullable=False),
        sa.Column("layer", test_layer, nullable=False),
        sa.Column("target_node", _UUID, nullable=True),
        sa.Column(
            "preconditions", postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column(
            "steps", postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"), nullable=False,
        ),
        sa.Column(
            "expected", postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column("oracle_source", oracle_source, nullable=False),
        sa.Column("authored_by", authored_by, nullable=False),
        sa.Column(
            "edited_by_human", sa.Boolean(),
            server_default=sa.text("false"), nullable=False,
        ),
        sa.Column("requirement_link", sa.String(length=512), nullable=True),
        sa.Column(
            "status", sa.String(length=50),
            server_default=sa.text("'draft'"), nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("parent_version_id", _UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_test_cases"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name="fk_test_cases_project_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["test_cases.id"],
            name="fk_test_cases_parent_version_id", ondelete="SET NULL",
        ),
    )
    op.create_index("ix_test_cases_project_id", "test_cases", ["project_id"])
    op.create_index(
        "ix_test_cases_parent_version_id", "test_cases", ["parent_version_id"]
    )
    op.create_index(
        "ix_test_cases_project_id_type", "test_cases", ["project_id", "type"]
    )

    op.create_table(
        "test_scripts",
        *_audit_columns(),
        sa.Column("test_case_id", _UUID, nullable=False),
        sa.Column("framework", framework, nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(length=255), nullable=False),
        sa.Column(
            "deterministic", sa.Boolean(),
            server_default=sa.text("true"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_test_scripts"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name="fk_test_scripts_project_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"], ["test_cases.id"],
            name="fk_test_scripts_test_case_id", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_test_scripts_project_id", "test_scripts", ["project_id"])
    op.create_index(
        "ix_test_scripts_test_case_id", "test_scripts", ["test_case_id"]
    )

    op.create_table(
        "runs",
        *_audit_columns(),
        sa.Column("trigger", run_trigger, nullable=False),
        sa.Column("mode", run_mode, nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column(
            "status", sa.String(length=50),
            server_default=sa.text("'pending'"), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name="fk_runs_project_id", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_runs_project_id", "runs", ["project_id"])

    op.create_table(
        "results",
        *_audit_columns(),
        sa.Column("run_id", _UUID, nullable=False),
        sa.Column("test_case_id", _UUID, nullable=False),
        sa.Column("outcome", outcome, nullable=False),
        sa.Column("triage", triage, nullable=True),
        sa.Column("evidence_ref", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_results"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name="fk_results_project_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_results_run_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"], ["test_cases.id"],
            name="fk_results_test_case_id", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_results_project_id", "results", ["project_id"])
    op.create_index("ix_results_run_id", "results", ["run_id"])
    op.create_index("ix_results_test_case_id", "results", ["test_case_id"])


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.drop_table("results")
    op.drop_table("runs")
    op.drop_table("test_scripts")
    op.drop_table("test_cases")
    bind = op.get_bind()
    for enum_type in reversed(_ENUMS):
        enum_type.drop(bind, checkfirst=True)
