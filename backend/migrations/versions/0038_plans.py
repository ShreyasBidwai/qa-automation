"""plans catalog + organizations.plan_key — pricing / entitlements (ADR-0069)

Revision ID: 0038_plans
Revises: 0037_org_suspended_at
Create Date: 2026-07-08

Forward-only and additive (Standards §14):

  1. ``plans`` — the entitlement catalog, seeded with the four launch tiers (indicative
     numbers, ADR-0069). NULL quota = unlimited; NULL price = custom.
  2. ``organizations.plan_key`` (default 'free') — every org (existing + new) starts on
     the free tier via the column's server default.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0038_plans"
down_revision: str | None = "0037_org_suspended_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column(
            "id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("price_per_seat_monthly_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("included_run_credits_monthly", sa.Integer(), nullable=True),
        sa.Column("max_projects", sa.Integer(), nullable=True),
        sa.Column("max_seats", sa.Integer(), nullable=True),
        sa.Column(
            "max_parallelism", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "retention_days",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.Column(
            "features",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_public", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint("key", name="uq_plans_key"),
    )
    op.create_index("ix_plans_key", "plans", ["key"], unique=True)

    # Seed the launch tiers (ADR-0069). Explicit jsonb casts; id/timestamps default.
    op.execute(
        """
        INSERT INTO plans (
            key, name, price_per_seat_monthly_usd, included_run_credits_monthly,
            max_projects, max_seats, max_parallelism, retention_days, features,
            is_public, sort_order
        ) VALUES
        ('free', 'Free', 0, 50, 1, 2, 1, 7, '{}'::jsonb, true, 0),
        ('team', 'Team', 49, 1000, 5, 10, 3, 30,
            '{"email_support": true}'::jsonb, true, 1),
        ('business', 'Business', 99, 5000, 25, 50, 10, 90,
            '{"sso": true, "priority_support": true}'::jsonb, true, 2),
        ('enterprise', 'Enterprise', NULL, NULL, NULL, NULL, 25, 365,
            '{"sso": true, "saml": true, "dedicated_capacity": true,
              "priority_support": true}'::jsonb, true, 3)
        """
    )

    op.add_column(
        "organizations",
        sa.Column(
            "plan_key",
            sa.String(length=32),
            server_default=sa.text("'free'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Forward-only (Standards §14); provided for completeness.
    op.drop_column("organizations", "plan_key")
    op.drop_index("ix_plans_key", table_name="plans")
    op.drop_table("plans")
