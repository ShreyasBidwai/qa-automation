"""ImpactSelector — select only the tests a code change could affect (T8.1).

The Mode B / CI differentiator over "run everything", deterministic over the
Brain and honest about its blind spots (ADR-0024):

  ChangeSet → seed nodes (whose ``source_file`` is in the ChangeSet) → expand each
  through ``CrossLayerResolver.impact`` (the 1-hop blast radius) → select current
  cases whose ``target_node`` is in the affected set, each with a rationale.

HONESTY (the core rule): a changed file that maps to no known node is recorded as
*unmapped* and forces a full-run recommendation — even when other files mapped and
produced a selection. Widen on uncertainty, never narrow. The result distinguishes
"confidently scoped" from "scope uncertain → run all". Deterministic, project-
scoped, bounded; reads only (Standards §5, §7).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import CrossLayerError, Impact
from app.models.model_node import ModelNode
from app.repositories.node_repository import NodeRepository
from app.repositories.test_case_repository import TestCaseRepository

logger = logging.getLogger("app.impact")


class ImpactResolver(Protocol):
    """The slice of CrossLayerResolver the selector needs (injectable for tests)."""

    async def impact(self, project_id: uuid.UUID, node_id: uuid.UUID) -> Impact: ...


@dataclass(frozen=True)
class ChangeSet:
    """The set of changed source file paths driving a selection."""

    paths: frozenset[str]

    @classmethod
    def of(cls, paths: Iterable[str]) -> ChangeSet:
        """Build from any iterable of paths, dropping blanks (deduped)."""
        return cls(frozenset(p.strip() for p in paths if p and p.strip()))

    def __bool__(self) -> bool:
        return bool(self.paths)


@dataclass(frozen=True)
class CaseSelection:
    """A selected test case + why the change pulled it in."""

    case_id: uuid.UUID
    covered_node_id: uuid.UUID
    changed_file: str
    # None → the covered node's own file changed (direct); else the seed node
    # whose blast radius reached the covered node (indirect).
    via_node_id: uuid.UUID | None
    rationale: str


@dataclass(frozen=True)
class ImpactSelection:
    """The scoped case set + the honesty signal (ADR-0024)."""

    selected: tuple[CaseSelection, ...]
    unmapped_files: tuple[str, ...]

    @property
    def scope_uncertain(self) -> bool:
        """A changed file mapped to no known node — the Brain has a blind spot."""
        return bool(self.unmapped_files)

    @property
    def confidently_scoped(self) -> bool:
        """Every changed file mapped → the selection can be trusted."""
        return not self.unmapped_files

    @property
    def recommend_full_run(self) -> bool:
        """Widen on uncertainty: run everything when scope is uncertain."""
        return self.scope_uncertain

    @property
    def case_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(s.case_id for s in self.selected)


@dataclass(frozen=True)
class _Affected:
    """A node in the affected set + why it is there."""

    node: ModelNode
    changed_file: str
    via: ModelNode | None  # None = directly changed; else the seed that reached it


def node_source_file(node: ModelNode) -> str | None:
    """A node's originating source file (provenance), or None (ADR-0024)."""
    value = node.attributes.get("source_file")
    return value if isinstance(value, str) and value else None


def _blast_nodes(impact: Impact) -> list[ModelNode]:
    """The 1-hop blast radius of a node: callers + written tables + gating roles."""
    seen: set[uuid.UUID] = set()
    out: list[ModelNode] = []
    for neighbour in (*impact.callers, *impact.writes, *impact.roles):
        if neighbour.id not in seen:
            seen.add(neighbour.id)
            out.append(neighbour)
    return out


def _rationale(affected: _Affected) -> str:
    node = affected.node
    if affected.via is None:
        return f"'{affected.changed_file}' changed → {node.kind.value} '{node.name}'"
    via = affected.via
    return (
        f"'{affected.changed_file}' changed → {via.kind.value} '{via.name}' "
        f"→ impacts {node.kind.value} '{node.name}'"
    )


class ImpactSelector:
    def __init__(self, session: AsyncSession, *, resolver: ImpactResolver) -> None:
        self._nodes = NodeRepository(session)
        self._cases = TestCaseRepository(session)
        self._resolver = resolver

    async def select(
        self, project_id: uuid.UUID, changeset: ChangeSet
    ) -> ImpactSelection:
        """Select the cases a change could affect (deterministic, project-scoped)."""
        files = sorted(changeset.paths)
        if not files:  # no change → confidently nothing to run
            return ImpactSelection(selected=(), unmapped_files=())

        by_file = await self._index_by_source_file(project_id)
        seeds, unmapped = self._seed(files, by_file)
        affected = await self._expand(project_id, seeds)

        cases = await self._cases.list_current_by_target_nodes(
            project_id, set(affected)
        )
        selections: list[CaseSelection] = []
        for case in cases:
            # The query filters target_node ∈ affected, so it is set and present.
            assert case.target_node is not None
            node_id = case.target_node
            hit = affected[node_id]
            selections.append(
                CaseSelection(
                    case_id=case.id,
                    covered_node_id=node_id,
                    changed_file=hit.changed_file,
                    via_node_id=hit.via.id if hit.via is not None else None,
                    rationale=_rationale(hit),
                )
            )
        selections.sort(
            key=lambda s: (s.changed_file, str(s.covered_node_id), str(s.case_id))
        )

        result = ImpactSelection(
            selected=tuple(selections), unmapped_files=tuple(sorted(unmapped))
        )
        logger.info(
            "impact.selected",
            extra={
                "project_id": str(project_id),
                "changed_files": len(files),
                "selected": len(result.selected),
                "unmapped": len(result.unmapped_files),
                "recommend_full_run": result.recommend_full_run,
            },
        )
        return result

    async def _index_by_source_file(
        self, project_id: uuid.UUID
    ) -> dict[str, list[ModelNode]]:
        """All project nodes grouped by their source file (deterministic order)."""
        nodes = sorted(
            await self._nodes.list(project_id), key=lambda n: (n.name, str(n.id))
        )
        index: dict[str, list[ModelNode]] = {}
        for node in nodes:
            source_file = node_source_file(node)
            if source_file is not None:
                index.setdefault(source_file, []).append(node)
        return index

    def _seed(
        self, files: list[str], by_file: dict[str, list[ModelNode]]
    ) -> tuple[list[tuple[ModelNode, str]], list[str]]:
        """Split changed files into seed (node, file) pairs and unmapped files."""
        seeds: list[tuple[ModelNode, str]] = []
        unmapped: list[str] = []
        for path in files:
            matched = by_file.get(path)
            if not matched:
                unmapped.append(path)  # blind spot → drives a full-run recommendation
                continue
            seeds.extend((node, path) for node in matched)
        return seeds, unmapped

    async def _expand(
        self, project_id: uuid.UUID, seeds: list[tuple[ModelNode, str]]
    ) -> dict[uuid.UUID, _Affected]:
        """Seeds + their 1-hop blast radii; direct hits recorded before expansion."""
        affected: dict[uuid.UUID, _Affected] = {}
        for node, path in seeds:  # pass 1: seeds are directly affected
            affected.setdefault(
                node.id, _Affected(node=node, changed_file=path, via=None)
            )
        for node, path in seeds:  # pass 2: 1-hop blast radius
            try:
                impact = await self._resolver.impact(project_id, node.id)
            except CrossLayerError:
                continue  # node vanished mid-flight — keep the seed, skip expansion
            for neighbour in _blast_nodes(impact):
                affected.setdefault(
                    neighbour.id,
                    _Affected(node=neighbour, changed_file=path, via=node),
                )
        return affected
