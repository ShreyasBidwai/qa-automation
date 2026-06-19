"""navigates edge_kind value for runtime frontend crawler — T4.2

Revision ID: 0011_navigates_edge_kind
Revises: 0010_authored_case_origin
Create Date: 2026-06-18

Forward-only and additive (Standards §14). Extends the ``edge_kind`` enum with
``navigates`` — a page → page navigation/link edge observed in the rendered DOM
by the stack-agnostic frontend crawler (T4.2), distinct from ``calls`` (used for
page → backend-endpoint edges). No table or column changes; existing rows are
unaffected.

As in 0008/0010, the value is added with ``ALTER TYPE ... ADD VALUE`` and is NOT
used within this migration (Postgres forbids using a freshly added enum value in
the same transaction that added it).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_navigates_edge_kind"
down_revision: str | None = "0010_authored_case_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE edge_kind ADD VALUE IF NOT EXISTS 'navigates'")


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    # An added enum value cannot be removed in Postgres without recreating the
    # type; 'navigates' is left in place (harmless, forward-only) — matching 0008.
    pass
