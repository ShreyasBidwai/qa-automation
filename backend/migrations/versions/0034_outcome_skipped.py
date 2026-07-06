"""skipped outcome value — reachable-but-unverified results (ADR-0064)

Revision ID: 0034_outcome_skipped
Revises: 0033_target_totp_secret
Create Date: 2026-07-06

Forward-only and additive (Standards §14). Extends the ``outcome`` enum with
``skipped`` — a test that RAN and reached the endpoint but could not verify success
because the endpoint returned a precondition status (a 4xx/redirect: auth, a missing
record, required query params, or a route that the in-process test boot does not
serve). It is NEITHER a pass nor a fail, so a static-generation run stops reading as
all-red-or-all-green and instead self-explains. A framework ``<skipped>`` (e.g. the
unavailable-factory skip of ADR-0037) also maps here now, instead of the misleading
``error``.

As in 0008/0010/0011, the value is added with ``ALTER TYPE ... ADD VALUE`` and is
NOT used within this migration (Postgres forbids using a freshly added enum value in
the same transaction that added it). Existing rows are unaffected.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034_outcome_skipped"
down_revision: str | None = "0033_target_totp_secret"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE outcome ADD VALUE IF NOT EXISTS 'skipped'")


def downgrade() -> None:
    # Forward-only (Standards §14). An added enum value cannot be dropped in Postgres
    # without recreating the type; 'skipped' is left in place (harmless) — as in 0011.
    pass
