"""SelectionStrategy — what Mode B tests, pluggable like the other providers (T8.2).

Two strategies yield a deterministic ``Selection`` (ordered targets + the honesty
``scope_uncertain`` flag), declared via a small enum + factory (ADR-0025):

- ``FullSweep`` — every testable node from the Brain (endpoints + pages).
- ``ChangeImpact`` — wraps the T8.1 ``ImpactSelector``; the impacted nodes that
  have covering cases become the targets, and the selector's ``scope_uncertain``
  is propagated up so Mode B can widen.

Selection is read-only and project-scoped; the orchestrator (mode_b.py) drives it.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.impact.selector import ChangeSet, ImpactResolver, ImpactSelector
from app.models.enums import NodeKind
from app.models.model_node import ModelNode
from app.repositories.node_repository import NodeRepository

from .errors import ModeBError

# Nodes a test can directly target. Tables/models/roles are reached via impact,
# not swept directly (no executable case targets them).
_TESTABLE_KINDS: tuple[NodeKind, ...] = (NodeKind.ENDPOINT, NodeKind.PAGE)


class SelectionStrategyKind(str, enum.Enum):
    """Which selection strategy a Mode B run uses (ADR-0025)."""

    FULL_SWEEP = "full_sweep"
    CHANGE_IMPACT = "change_impact"


@dataclass(frozen=True)
class Target:
    """A Brain node Mode B will ensure a case for and execute."""

    node_id: uuid.UUID
    kind: NodeKind
    name: str


@dataclass(frozen=True)
class Selection:
    """The targets to test + the honesty signal (ADR-0025)."""

    targets: tuple[Target, ...]
    scope_uncertain: bool


class SelectionStrategy(Protocol):
    kind: SelectionStrategyKind

    async def select(self, project_id: uuid.UUID) -> Selection: ...


def _target_of(node: ModelNode) -> Target:
    return Target(node_id=node.id, kind=node.kind, name=node.name)


def _sorted_targets(targets: Iterable[Target]) -> tuple[Target, ...]:
    """Deterministic target order: (kind, name, id)."""
    return tuple(sorted(targets, key=lambda t: (t.kind.value, t.name, str(t.node_id))))


# The run layer a testable target belongs to (ADR-0052). DB has no target kind — it
# is the DB-state phase, gated separately in the orchestrator.
_LAYER_OF_KIND: dict[NodeKind, str] = {
    NodeKind.PAGE: "ui",
    NodeKind.ENDPOINT: "api",
}


def targets_for_layers(
    targets: tuple[Target, ...], layers: frozenset[str] | None
) -> tuple[Target, ...]:
    """Keep only targets whose layer is in ``layers`` (ADR-0052).

    ``layers=None`` means the full set — returned unchanged (backward-compatible). A
    target whose kind has no layer mapping is dropped when a scope is given.
    """
    if layers is None:
        return targets
    return tuple(t for t in targets if _LAYER_OF_KIND.get(t.kind) in layers)


class FullSweepStrategy:
    """Every testable node in the project's Brain (deterministic, never uncertain)."""

    kind = SelectionStrategyKind.FULL_SWEEP

    def __init__(self, session: AsyncSession) -> None:
        self._nodes = NodeRepository(session)

    async def select(self, project_id: uuid.UUID) -> Selection:
        nodes: list[ModelNode] = []
        for kind in _TESTABLE_KINDS:
            nodes.extend(await self._nodes.list_by_kind(project_id, kind))
        return Selection(
            targets=_sorted_targets(_target_of(n) for n in nodes),
            scope_uncertain=False,
        )


class ChangeImpactStrategy:
    """The impacted, covered nodes from the T8.1 ImpactSelector (propagates honesty)."""

    kind = SelectionStrategyKind.CHANGE_IMPACT

    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver: ImpactResolver,
        changeset: ChangeSet,
    ) -> None:
        self._nodes = NodeRepository(session)
        self._selector = ImpactSelector(session, resolver=resolver)
        self._changeset = changeset

    async def select(self, project_id: uuid.UUID) -> Selection:
        impact = await self._selector.select(project_id, self._changeset)
        node_ids = {s.covered_node_id for s in impact.selected}
        nodes = await self._nodes.get_many(project_id, node_ids)
        return Selection(
            targets=_sorted_targets(_target_of(n) for n in nodes),
            scope_uncertain=impact.scope_uncertain,
        )


def build_selection_strategy(
    kind: SelectionStrategyKind,
    *,
    session: AsyncSession,
    resolver: ImpactResolver | None = None,
    changeset: ChangeSet | None = None,
) -> SelectionStrategy:
    """Construct a selection strategy by kind (ADR-0025).

    ChangeImpact requires a changeset + resolver — a typed error rather than a
    silent narrow.
    """
    if kind is SelectionStrategyKind.CHANGE_IMPACT:
        if changeset is None or resolver is None:
            raise ModeBError(
                "ChangeImpact selection requires a changeset and an impact resolver"
            )
        return ChangeImpactStrategy(session, resolver=resolver, changeset=changeset)
    return FullSweepStrategy(session)
