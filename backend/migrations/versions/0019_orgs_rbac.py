"""teams/RBAC: organizations + members + invites; projects org-scoped (B3)

Revision ID: 0019_orgs_rbac
Revises: 0018_project_owner
Create Date: 2026-06-21

Forward-only (Standards §14). Moves tenancy from user-owned projects (B2/ADR-0031)
to org-owned (ADR-0032):

  1. ``org_role`` enum + ``organizations`` / ``organization_members`` /
     ``organization_invites`` tables.
  2. ``users.name`` (account profile).
  3. ``projects.org_id`` (nullable for now).
  4. DATA: a personal org + owner membership per existing user; their owned
     projects move into it. Legacy NULL-owner projects go to a single ``Legacy``
     org owned by the earliest user (ADR-0032) — never left globally shared.
  5. ``projects.org_id`` set NOT NULL (every row now has one).
  6. ``projects.owner_id`` → ``created_by`` (provenance only; no longer access).

No rows are deleted; ``created_by`` keeps the old ``owner_id`` value.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_orgs_rbac"
down_revision: str | None = "0018_project_owner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_ORG_ROLE = postgresql.ENUM(
    "owner", "admin", "member", "viewer", name="org_role", create_type=False
)


def _audit_columns() -> list[sa.Column]:
    return [
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
    ]


def _backfill_orgs() -> None:
    """One-time data migration (ADR-0032). Runs inside the migration's tx."""
    bind = op.get_bind()

    users = bind.execute(
        sa.text("SELECT id, email FROM users ORDER BY created_at, id")
    ).all()
    for user in users:
        local_part = (user.email.split("@", 1)[0] or "personal")[:255]
        org_id = bind.execute(
            sa.text(
                "INSERT INTO organizations (name, is_personal) "
                "VALUES (:name, true) RETURNING id"
            ),
            {"name": local_part},
        ).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO organization_members (org_id, user_id, role) "
                "VALUES (:org_id, :user_id, 'owner')"
            ),
            {"org_id": org_id, "user_id": user.id},
        )
        bind.execute(
            sa.text(
                "UPDATE projects SET org_id = :org_id "
                "WHERE owner_id = :user_id AND org_id IS NULL"
            ),
            {"org_id": org_id, "user_id": user.id},
        )

    # Legacy (owner_id NULL) projects → a dedicated Legacy org, owned by the
    # earliest user if one exists. Never left globally shared (ADR-0032).
    legacy_count = bind.execute(
        sa.text("SELECT count(*) FROM projects WHERE org_id IS NULL")
    ).scalar_one()
    if legacy_count:
        legacy_org_id = bind.execute(
            sa.text(
                "INSERT INTO organizations (name, is_personal) "
                "VALUES ('Legacy', false) RETURNING id"
            )
        ).scalar_one()
        earliest_user = bind.execute(
            sa.text("SELECT id FROM users ORDER BY created_at, id LIMIT 1")
        ).scalar()
        if earliest_user is not None:
            bind.execute(
                sa.text(
                    "INSERT INTO organization_members (org_id, user_id, role) "
                    "VALUES (:org_id, :user_id, 'owner')"
                ),
                {"org_id": legacy_org_id, "user_id": earliest_user},
            )
        bind.execute(
            sa.text("UPDATE projects SET org_id = :org_id WHERE org_id IS NULL"),
            {"org_id": legacy_org_id},
        )


def upgrade() -> None:
    op.execute(
        "CREATE TYPE org_role AS ENUM ('owner', 'admin', 'member', 'viewer')"
    )

    op.create_table(
        "organizations",
        *_audit_columns(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_personal",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
    )

    op.create_table(
        "organization_members",
        *_audit_columns(),
        sa.Column("org_id", _UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("role", _ORG_ROLE, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_organization_members"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name="fk_organization_members_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_organization_members_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "org_id", "user_id", name="uq_organization_members_org_user"
        ),
    )
    op.create_index(
        "ix_organization_members_org_id", "organization_members", ["org_id"]
    )
    op.create_index(
        "ix_organization_members_user_id", "organization_members", ["user_id"]
    )

    op.create_table(
        "organization_invites",
        *_audit_columns(),
        sa.Column("org_id", _UUID, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", _ORG_ROLE, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by", _UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_organization_invites"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name="fk_organization_invites_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name="fk_organization_invites_invited_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "token_hash", name="uq_organization_invites_token_hash"
        ),
    )
    op.create_index(
        "ix_organization_invites_org_id", "organization_invites", ["org_id"]
    )
    op.create_index(
        "ix_organization_invites_token_hash",
        "organization_invites",
        ["token_hash"],
    )

    # Account profile (B3).
    op.add_column("users", sa.Column("name", sa.String(length=255), nullable=True))

    # Org-scope projects: add nullable, backfill, then enforce NOT NULL.
    op.add_column("projects", sa.Column("org_id", _UUID, nullable=True))
    op.create_foreign_key(
        "fk_projects_org_id",
        "projects",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_projects_org_id", "projects", ["org_id"])

    _backfill_orgs()

    op.alter_column("projects", "org_id", nullable=False)

    # owner_id is now provenance only (access is org-based): rename → created_by,
    # keeping its value and renaming the FK + index to match.
    op.alter_column("projects", "owner_id", new_column_name="created_by")
    op.execute(
        "ALTER TABLE projects "
        "RENAME CONSTRAINT fk_projects_owner_id TO fk_projects_created_by"
    )
    op.execute("ALTER INDEX ix_projects_owner_id RENAME TO ix_projects_created_by")


def downgrade() -> None:
    # Provided for completeness; production is forward-only (Standards §14).
    op.execute("ALTER INDEX ix_projects_created_by RENAME TO ix_projects_owner_id")
    op.execute(
        "ALTER TABLE projects "
        "RENAME CONSTRAINT fk_projects_created_by TO fk_projects_owner_id"
    )
    op.alter_column("projects", "created_by", new_column_name="owner_id")
    op.drop_index("ix_projects_org_id", table_name="projects")
    op.drop_constraint("fk_projects_org_id", "projects", type_="foreignkey")
    op.drop_column("projects", "org_id")
    op.drop_column("users", "name")
    op.drop_table("organization_invites")
    op.drop_table("organization_members")
    op.drop_table("organizations")
    op.execute("DROP TYPE org_role")
