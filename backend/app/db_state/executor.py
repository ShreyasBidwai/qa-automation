"""Tier-aware DB-state execution (B10, ADR-0043).

Routes every DB-state operation through the project's tier and, for any write, the
non-prod safety gate:

  - ``off``       → nothing runs (reads and writes both refused);
  - ``read_only`` → SELECT table-state assertions only; writes refused;
  - ``full``      → writes permitted, but ONLY after ``ensure_disposable`` passes.

``ensure_writable`` is the single structural choke point for writes — there is no
path to a disposable-DB write that skips the gate. ``tie_to_table_node`` stamps a
check with its Brain table node so the page→endpoint→model→table blast path is
verified at the table end.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.models.enums import NodeKind
from app.repositories.node_repository import NodeRepository

from .errors import WriteNotPermitted
from .gate import DisposableTarget, ensure_disposable
from .oracle import TableStateCheck, TableStateResult, evaluate_table_state
from .tiers import DbStateTier


class DbStateExecutor:
    """Gate DB-state reads/writes by tier; the safety gate guards every write."""

    def __init__(
        self, *, tier: DbStateTier, target: DisposableTarget | None = None
    ) -> None:
        self._tier = tier
        self._target = target

    @property
    def tier(self) -> DbStateTier:
        return self._tier

    def ensure_readable(self) -> None:
        """Permit SELECT table-state assertions (read_only + full); refuse when off."""
        if not self._tier.allows_read:
            raise WriteNotPermitted("db-state testing is off for this project")

    def ensure_writable(self) -> None:
        """The single choke point for any disposable-DB write.

        Requires the ``full`` tier AND a target that passes the non-prod safety gate
        (``ensure_disposable``). ``read_only``/``off`` refuse here; a missing or
        prod-looking target refuses via the gate. No write path bypasses this.
        """
        if not self._tier.allows_write:
            raise WriteNotPermitted(
                f"tier {self._tier.value!r} does not permit writes to the "
                "disposable DB (read-only assertions only)"
            )
        if self._target is None:
            raise WriteNotPermitted("full tier requires a configured disposable target")
        ensure_disposable(self._target)  # the load-bearing safety gate (ADR-0043)

    async def assert_state(
        self, conn: AsyncConnection | AsyncSession, check: TableStateCheck
    ) -> TableStateResult:
        """Evaluate one table-state assertion (read path; gated by tier)."""
        self.ensure_readable()
        return await evaluate_table_state(conn, check)

    async def tie_to_table_node(
        self, session: AsyncSession, project_id: uuid.UUID, check: TableStateCheck
    ) -> TableStateCheck:
        """Stamp the check with its Brain table node, completing the blast path.

        Returns the check unchanged when the Brain has no matching table node (the
        table end simply isn't wired yet — degrade, don't fabricate a link).
        """
        node = await NodeRepository(session).get_by_key(
            project_id, NodeKind.TABLE, check.table
        )
        if node is None:
            return check
        return replace(check, table_node_id=node.id)
