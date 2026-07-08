"""staff_role — instance-level staff RBAC for the operator/admin console (ADR-0068)

Revision ID: 0035_staff_roles
Revises: 0034_outcome_skipped
Create Date: 2026-07-08

Forward-only and additive (Standards §14). Introduces cross-tenant staff RBAC,
superseding the boolean ``users.is_operator`` (ADR-0035):

  1. ``staff_role`` enum (superadmin / support / billing / read_only_ops).
  2. ``users.staff_role`` (nullable — NULL = not staff).
  3. DATA: existing operators (``is_operator = true``) are backfilled to
     ``read_only_ops`` — least privilege, preserving their prior read-only
     cross-tenant visibility without granting any mutation. Promote real admins out
     of band / via the admin API. ``is_operator`` is left in place (deprecated; the
     deps layer still honours it during the transition).

A freshly-created enum type is usable within the same migration (unlike ADD VALUE to
an existing type — see 0034), so the backfill runs here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0035_staff_roles"
down_revision: str | None = "0034_outcome_skipped"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAFF_ROLE = postgresql.ENUM(
    "superadmin",
    "support",
    "billing",
    "read_only_ops",
    name="staff_role",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        "CREATE TYPE staff_role AS ENUM "
        "('superadmin', 'support', 'billing', 'read_only_ops')"
    )
    op.add_column("users", sa.Column("staff_role", _STAFF_ROLE, nullable=True))
    op.execute("UPDATE users SET staff_role = 'read_only_ops' WHERE is_operator = true")


def downgrade() -> None:
    # Forward-only (Standards §14); provided for completeness.
    op.drop_column("users", "staff_role")
    op.execute("DROP TYPE staff_role")
