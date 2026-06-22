"""DB-state oracles — assert table state, tagged honestly (B10, ADR-0043).

A check asserts something about a table at the DB end of the blast path: a row is
present/absent, a column holds a value, a soft-deleted row is flagged not gone. The
expectation's trust is tagged: ``rule-derived`` when it follows from a schema
constraint / documented rule (e.g. soft-delete semantics, a NOT NULL default),
``characterization`` when it merely pins current observed state. ``table_node_id``
ties the check to the Brain's table node so the page→endpoint→model→table blast path
is verified at the table end, not just mapped.

SQL safety: table/where-column identifiers are validated against a strict pattern
and double-quoted; all values are bound parameters. An invalid identifier is
refused (``UnsafeIdentifierError``), never interpolated.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.models.enums import OracleSource

from .errors import UnsafeIdentifierError

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise UnsafeIdentifierError(f"unsafe SQL identifier: {name!r}")
    return name


class TablePredicate(str, Enum):
    ROW_PRESENT = "row_present"  # a matching row exists
    ROW_ABSENT = "row_absent"  # no matching row exists (e.g. a hard delete)
    COLUMN_EQUALS = "column_equals"  # the row exists and its columns hold ``expected``
    SOFT_DELETED = "soft_deleted"  # the row exists AND its soft-delete column is set


@dataclass(frozen=True)
class TableStateCheck:
    """One DB-state assertion against ``table`` selected by ``where``."""

    table: str
    predicate: TablePredicate
    where: dict[str, Any]
    expected: dict[str, Any] = field(default_factory=dict)  # for COLUMN_EQUALS
    soft_delete_column: str = "deleted_at"  # for SOFT_DELETED
    oracle_source: OracleSource = OracleSource.CHARACTERIZATION
    # Ties the assertion to the Brain's table node — completes the blast path.
    table_node_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TableStateResult:
    check: TableStateCheck
    passed: bool
    observed: dict[str, Any] | None  # the matched row (or None if absent)
    detail: str


def classify_oracle(*, schema_backed: bool) -> OracleSource:
    """Honest oracle tagging (ADR-0043).

    ``rule-derived`` when the expectation follows from a schema constraint or a
    documented rule (the DB *must* be this way); ``characterization`` when it only
    pins the current observed state. Default-honest: callers that can't show a rule
    basis get ``characterization``.
    """
    return OracleSource.RULE_DERIVED if schema_backed else OracleSource.CHARACTERIZATION


def _evaluate(
    check: TableStateCheck, observed: dict[str, Any] | None
) -> tuple[bool, str]:
    predicate = check.predicate
    if predicate is TablePredicate.ROW_PRESENT:
        return (observed is not None), (
            "row present" if observed is not None else "expected row is absent"
        )
    if predicate is TablePredicate.ROW_ABSENT:
        return (observed is None), (
            "row absent" if observed is None else "row is unexpectedly present"
        )
    if observed is None:
        return False, "row absent — cannot evaluate column/soft-delete predicate"
    if predicate is TablePredicate.COLUMN_EQUALS:
        mismatches = {
            col: {"observed": observed.get(col), "expected": value}
            for col, value in check.expected.items()
            if observed.get(col) != value
        }
        return (not mismatches), (
            "columns match" if not mismatches else f"column mismatch: {mismatches}"
        )
    if predicate is TablePredicate.SOFT_DELETED:
        column = check.soft_delete_column
        flagged = observed.get(column) is not None
        return flagged, (
            f"soft-delete column {column!r} is set (flagged, not gone)"
            if flagged
            else f"soft-delete column {column!r} is null — row not soft-deleted"
        )
    return False, f"unknown predicate {predicate!r}"


async def evaluate_table_state(
    conn: AsyncConnection | AsyncSession, check: TableStateCheck
) -> TableStateResult:
    """Run ``check`` against ``conn`` (parameterized, identifier-validated)."""
    table = _safe_ident(check.table)
    where_cols = [_safe_ident(col) for col in check.where]
    sql = f'SELECT * FROM "{table}"'
    params: dict[str, Any] = {}
    if where_cols:
        clauses = []
        for col in where_cols:
            clauses.append(f'"{col}" = :w_{col}')
            params[f"w_{col}"] = check.where[col]
        sql += " WHERE " + " AND ".join(clauses)
    sql += " LIMIT 1"

    row = (await conn.execute(text(sql), params)).mappings().first()
    observed = dict(row) if row is not None else None
    passed, detail = _evaluate(check, observed)
    return TableStateResult(
        check=check, passed=passed, observed=observed, detail=detail
    )
