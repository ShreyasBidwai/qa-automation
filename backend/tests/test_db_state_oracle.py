"""DB-state oracles (B10, ADR-0043) — table-state assertions + honest tagging.

Runs against a real ``orders`` table created inside the test's own transaction (per-
test isolation rolls it back). Covers each predicate passing/failing, the
rule-derived vs characterization tag, and identifier safety.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_state.errors import UnsafeIdentifierError
from app.db_state.oracle import (
    TablePredicate,
    TableStateCheck,
    classify_oracle,
    evaluate_table_state,
)
from app.models.enums import OracleSource


async def _orders(session: AsyncSession) -> None:
    await session.execute(
        text(
            "CREATE TABLE orders ("
            "  id integer PRIMARY KEY, status text, total integer, "
            "  deleted_at timestamptz)"
        )
    )


async def test_row_present_and_absent(db_session: AsyncSession) -> None:
    await _orders(db_session)
    await db_session.execute(
        text("INSERT INTO orders (id, status, total) VALUES (1, 'paid', 500)")
    )

    present = await evaluate_table_state(
        db_session, TableStateCheck("orders", TablePredicate.ROW_PRESENT, {"id": 1})
    )
    assert present.passed and present.observed is not None
    assert present.observed["status"] == "paid"

    # ROW_ABSENT passes for a missing row; ROW_PRESENT fails for it.
    absent = await evaluate_table_state(
        db_session, TableStateCheck("orders", TablePredicate.ROW_ABSENT, {"id": 999})
    )
    assert absent.passed
    missing = await evaluate_table_state(
        db_session, TableStateCheck("orders", TablePredicate.ROW_PRESENT, {"id": 999})
    )
    assert not missing.passed and missing.observed is None


async def test_column_equals_passes_then_fails(db_session: AsyncSession) -> None:
    await _orders(db_session)
    await db_session.execute(
        text("INSERT INTO orders (id, status, total) VALUES (7, 'pending', 500)")
    )

    ok = await evaluate_table_state(
        db_session,
        TableStateCheck(
            "orders",
            TablePredicate.COLUMN_EQUALS,
            {"id": 7},
            expected={"status": "pending", "total": 500},
        ),
    )
    assert ok.passed
    bad = await evaluate_table_state(
        db_session,
        TableStateCheck(
            "orders",
            TablePredicate.COLUMN_EQUALS,
            {"id": 7},
            expected={"status": "shipped"},  # not what landed
        ),
    )
    assert not bad.passed and "mismatch" in bad.detail


async def test_soft_deleted_flagged_not_gone(db_session: AsyncSession) -> None:
    await _orders(db_session)
    # A soft-deleted row: still present, but its deleted_at is set.
    await db_session.execute(
        text("INSERT INTO orders (id, status, deleted_at) VALUES (3, 'x', now())")
    )
    await db_session.execute(
        text("INSERT INTO orders (id, status, deleted_at) VALUES (4, 'x', NULL)")
    )

    flagged = await evaluate_table_state(
        db_session, TableStateCheck("orders", TablePredicate.SOFT_DELETED, {"id": 3})
    )
    assert flagged.passed  # row exists AND deleted_at set → soft-deleted, not gone
    live = await evaluate_table_state(
        db_session, TableStateCheck("orders", TablePredicate.SOFT_DELETED, {"id": 4})
    )
    assert not live.passed  # present but deleted_at null → not soft-deleted


def test_oracle_tagging_is_honest() -> None:
    # rule-derived when the expectation follows from a schema constraint / rule;
    # characterization when it merely pins observed state.
    assert classify_oracle(schema_backed=True) is OracleSource.RULE_DERIVED
    assert classify_oracle(schema_backed=False) is OracleSource.CHARACTERIZATION
    # The honest default on a bare check is characterization.
    assert (
        TableStateCheck("orders", TablePredicate.ROW_PRESENT, {"id": 1}).oracle_source
        is OracleSource.CHARACTERIZATION
    )


async def test_unsafe_identifier_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(UnsafeIdentifierError):
        await evaluate_table_state(
            db_session,
            TableStateCheck("orders; DROP TABLE users", TablePredicate.ROW_PRESENT, {}),
        )
