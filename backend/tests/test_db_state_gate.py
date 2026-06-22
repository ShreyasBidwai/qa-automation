"""The non-prod safety gate (B10, ADR-0043) — the load-bearing safety test.

DB-state testing must NEVER run against a production database. The gate refuses an
unflagged target, a prod/staging-looking target (even if flagged), and an
unrecognized remote target — and only permits an explicitly-disposable, non-prod
one. Erring toward refusing is the point, so the refuse-cases are the bulk here.
"""

from __future__ import annotations

import pytest

from app.db_state.errors import ProdTargetRefused
from app.db_state.gate import DisposableTarget, ensure_disposable, looks_prod

_LOCAL = "postgresql+psycopg://u:p@localhost:5432/app_dbstate_xyz"


# --- REFUSE (the safety property) --------------------------------------------


def test_refuses_unflagged_target() -> None:
    with pytest.raises(ProdTargetRefused, match="not explicitly flagged disposable"):
        ensure_disposable(DisposableTarget(url=_LOCAL, disposable=False))


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@db-prod.internal:5432/app",
        "postgresql+psycopg://u:p@10.0.0.5:5432/app_production",
        "postgresql+psycopg://u:p@host:5432/app_staging",
        "postgresql+psycopg://u:p@live-db:5432/orders",
        "postgresql+psycopg://u:p@stg.internal:5432/app",
    ],
)
def test_refuses_prod_or_staging_even_when_flagged_disposable(url: str) -> None:
    # The explicit flag is NOT sufficient — a mislabeled prod/staging DB is refused.
    with pytest.raises(ProdTargetRefused, match="production-ish"):
        ensure_disposable(DisposableTarget(url=url, disposable=True))


def test_refuses_unrecognized_remote_target_even_when_flagged() -> None:
    # Flagged + not prod-named, but a remote host with no disposable marker → refuse
    # (err toward refusing; it could be prod under an innocuous name).
    url = "postgresql+psycopg://u:p@some-remote-host:5432/app"
    with pytest.raises(ProdTargetRefused, match="neither a local host nor name-marked"):
        ensure_disposable(DisposableTarget(url=url, disposable=True))


# --- ALLOW (only the explicitly-disposable, non-prod target) -----------------


def test_allows_local_disposable_target() -> None:
    ensure_disposable(DisposableTarget(url=_LOCAL, disposable=True))  # no raise


def test_allows_name_marked_disposable_remote_target() -> None:
    url = "postgresql+psycopg://u:p@runner-7:5432/orders_disposable_42"
    ensure_disposable(DisposableTarget(url=url, disposable=True))  # no raise


# --- the prod heuristic in isolation -----------------------------------------


def test_looks_prod_flags_markers_and_clears_clean_names() -> None:
    assert looks_prod("postgresql+psycopg://u:p@h:5432/app_production") is not None
    assert looks_prod("postgresql+psycopg://u:p@prod-host:5432/app") is not None
    assert looks_prod(_LOCAL) is None
