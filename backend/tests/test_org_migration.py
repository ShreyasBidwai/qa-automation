"""The owner→org data migration (0019, ADR-0032) preserves data and moves it right.

Builds a throwaway database at 0018 (user-owned projects), seeds users + owned +
legacy projects, runs ``alembic upgrade 0019``, and asserts the post-migration
shape: a personal org + owner membership per user, owned projects moved into them,
legacy NULL-owner projects assigned to a single ``Legacy`` org owned by the
earliest user, ``created_by`` preserved, and no rows lost. Uses the same
create-DB-and-migrate machinery as conftest, on its own DB so it can start at 0018.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


@pytest.fixture
def migration_url() -> Iterator[str]:
    """A fresh, empty database, with ``DATABASE_URL`` repointed at it for the test.

    Alembic's env reads the URL from settings (``DATABASE_URL``), so we repoint the
    env var (and clear the settings cache) for the duration, then restore it — this
    lets ``command.upgrade`` run against our own DB starting at 0018.
    """
    original = os.environ["DATABASE_URL"]
    base_url = make_url(original)
    db_name = f"mig_{uuid.uuid4().hex[:12]}"
    admin_url = base_url.set(database="postgres")
    rendered = base_url.set(database=db_name).render_as_string(hide_password=False)

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    os.environ["DATABASE_URL"] = rendered
    get_settings.cache_clear()
    try:
        yield rendered
    finally:
        os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin.dispose()


def _cfg(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_owner_to_org_migration_preserves_and_moves_data(migration_url: str) -> None:
    cfg = _cfg(migration_url)
    command.upgrade(cfg, "0018_project_owner")  # the B2 schema (user-owned)

    alice, bob = uuid.uuid4(), uuid.uuid4()
    p_alice, p_bob, p_legacy = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    engine = create_engine(migration_url)
    with engine.begin() as conn:
        # Two users; alice is the earlier account (controls the Legacy-org owner).
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, is_active, "
                "created_at, updated_at) VALUES "
                "(:id, :email, 'x', true, :ts, :ts)"
            ),
            [
                {"id": alice, "email": "alice@x.test", "ts": "2026-01-01 00:00+00"},
                {"id": bob, "email": "bob@x.test", "ts": "2026-01-02 00:00+00"},
            ],
        )
        # Two owned projects + one legacy (NULL owner = pre-auth shared data).
        conn.execute(
            text(
                "INSERT INTO projects (id, name, slug, owner_id, settings, "
                "created_at, updated_at) VALUES "
                "(:id, :name, :slug, :owner, '{}'::jsonb, now(), now())"
            ),
            [
                {"id": p_alice, "name": "Alice", "slug": "alice-p", "owner": alice},
                {"id": p_bob, "name": "Bob", "slug": "bob-p", "owner": bob},
                {"id": p_legacy, "name": "Legacy", "slug": "legacy-p", "owner": None},
            ],
        )
    engine.dispose()

    command.upgrade(cfg, "0019_orgs_rbac")  # the migration under test

    engine = create_engine(migration_url)
    with engine.connect() as conn:
        # Every project now belongs to exactly one org (org_id NOT NULL).
        assert (
            conn.execute(
                text("SELECT count(*) FROM projects WHERE org_id IS NULL")
            ).scalar_one()
            == 0
        )
        # No data lost: all three projects survive.
        assert conn.execute(text("SELECT count(*) FROM projects")).scalar_one() == 3

        # Each user got exactly one personal org they own.
        assert (
            conn.execute(
                text("SELECT count(*) FROM organizations WHERE is_personal")
            ).scalar_one()
            == 2
        )
        alice_row = conn.execute(
            text(
                "SELECT o.is_personal, m.role FROM projects p "
                "JOIN organizations o ON o.id = p.org_id "
                "JOIN organization_members m ON m.org_id = o.id "
                "WHERE p.id = :pid AND m.user_id = :uid"
            ),
            {"pid": p_alice, "uid": alice},
        ).one()
        assert alice_row.is_personal is True
        assert alice_row.role == "owner"

        # created_by preserves the old owner_id (renamed, not dropped).
        assert (
            conn.execute(
                text("SELECT created_by FROM projects WHERE id = :pid"),
                {"pid": p_bob},
            ).scalar_one()
            == bob
        )

        # The legacy project went to a dedicated Legacy org owned by the earliest
        # user (alice) — NOT left globally shared, NOT in anyone's personal org.
        legacy_org = conn.execute(
            text(
                "SELECT id FROM organizations "
                "WHERE name = 'Legacy' AND NOT is_personal"
            )
        ).scalar_one()
        assert (
            conn.execute(
                text("SELECT org_id FROM projects WHERE id = :pid"),
                {"pid": p_legacy},
            ).scalar_one()
            == legacy_org
        )
        assert (
            conn.execute(
                text(
                    "SELECT user_id FROM organization_members "
                    "WHERE org_id = :o AND role = 'owner'"
                ),
                {"o": legacy_org},
            ).scalar_one()
            == alice
        )
    engine.dispose()
