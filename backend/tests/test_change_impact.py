"""Change-impact test selection (T8.1) — fast tests.

Injected Brain nodes/edges + injected cases, with the real CrossLayerResolver:
a changed file maps to its node, expands through the 1-hop blast radius, and
pulls in the covering cases — while an unmapped change widens to a full-run
recommendation (never silently narrows). Plus the pure helpers (source-file
provenance, the git-diff seam) and determinism / project-scoping.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import CrossLayerResolver, Impact, NodeNotFoundError
from app.impact import ChangeSet, ImpactSelector, changed_paths, node_source_file
from app.ingestion.commands import CommandResult
from app.models.enums import EdgeKind, NodeKind
from app.models.model_edge import ModelEdge
from app.models.model_node import ModelNode
from app.repositories.edge_repository import EdgeRepository
from app.repositories.node_repository import NodeRepository
from app.repositories.test_case_repository import TestCaseRepository
from tests.factories import make_project, make_test_case

_CTRL = "app/Http/Controllers/UserController.php"


# --- pure helpers ------------------------------------------------------------


def test_node_source_file_reads_the_provenance_attribute() -> None:
    pid = uuid.uuid4()

    def _n(attrs: dict[str, object]) -> ModelNode:
        return ModelNode(
            project_id=pid, kind=NodeKind.ENDPOINT, name="e", attributes=attrs
        )

    assert node_source_file(_n({"source_file": "a.php"})) == "a.php"
    assert node_source_file(_n({})) is None
    assert node_source_file(_n({"source_file": ""})) is None


def test_changeset_of_is_truthy_only_when_non_empty() -> None:
    assert not ChangeSet.of([])
    assert not ChangeSet.of(["", "  "])  # blanks dropped
    assert ChangeSet.of(["a.py"])


def test_changed_paths_parses_git_diff_name_only() -> None:
    def fake_runner(argv, cwd, timeout):  # type: ignore[no-untyped-def]
        assert "diff" in argv and "--name-only" in argv
        return CommandResult(returncode=0, stdout="a.py\nb/c.py\n\n", stderr="")

    changeset = changed_paths("/repo", "base", "head", runner=fake_runner)
    assert changeset.paths == frozenset({"a.py", "b/c.py"})  # blank lines dropped


# --- DB fixtures -------------------------------------------------------------


async def _project(session: AsyncSession) -> uuid.UUID:
    project = make_project()
    session.add(project)
    await session.flush()
    return project.id


async def _node(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: NodeKind,
    name: str,
    *,
    source_file: str | None = None,
) -> ModelNode:
    attributes: dict[str, object] = {}
    if source_file is not None:
        attributes["source_file"] = source_file
    return await NodeRepository(session).add(
        ModelNode(project_id=project_id, kind=kind, name=name, attributes=attributes)
    )


async def _edge(
    session: AsyncSession,
    project_id: uuid.UUID,
    src: uuid.UUID,
    dst: uuid.UUID,
    kind: EdgeKind,
) -> None:
    await EdgeRepository(session).add(
        ModelEdge(
            project_id=project_id,
            src_node_id=src,
            dst_node_id=dst,
            kind=kind,
            confidence=1.0,
        )
    )


async def _case(session: AsyncSession, project_id: uuid.UUID, target_node: uuid.UUID):
    return await TestCaseRepository(session).add(
        make_test_case(project_id, target_node=target_node)
    )


# --- DB selection ------------------------------------------------------------


async def test_controller_change_selects_endpoint_and_calling_page_cases(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    endpoint = await _node(
        db_session, project_id, NodeKind.ENDPOINT, "POST api/users", source_file=_CTRL
    )
    page = await _node(
        db_session,
        project_id,
        NodeKind.PAGE,
        "/users",
        source_file="resources/Users.vue",
    )
    table = await _node(
        db_session, project_id, NodeKind.TABLE, "users", source_file="db/users.php"
    )
    unrelated = await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "GET api/orders",
        source_file="app/Http/Controllers/OrderController.php",
    )
    await _edge(db_session, project_id, page.id, endpoint.id, EdgeKind.CALLS)
    await _edge(db_session, project_id, endpoint.id, table.id, EdgeKind.WRITES)
    case_api = await _case(db_session, project_id, endpoint.id)
    case_ui = await _case(db_session, project_id, page.id)
    case_table = await _case(db_session, project_id, table.id)
    case_unrelated = await _case(db_session, project_id, unrelated.id)

    selector = ImpactSelector(db_session, resolver=CrossLayerResolver(db_session))
    result = await selector.select(project_id, ChangeSet.of([_CTRL]))

    assert result.confidently_scoped and not result.recommend_full_run
    assert result.unmapped_files == ()
    # endpoint (direct) + calling page + written table; the unrelated endpoint's
    # case is excluded.
    assert result.case_ids == {case_api.id, case_ui.id, case_table.id}
    assert case_unrelated.id not in result.case_ids

    by_case = {s.case_id: s for s in result.selected}
    assert by_case[case_api.id].via_node_id is None  # its own file changed
    assert by_case[case_api.id].changed_file == _CTRL
    assert by_case[case_ui.id].via_node_id == endpoint.id  # pulled in via the endpoint
    assert "impacts" in by_case[case_ui.id].rationale


async def test_unmapped_change_recommends_full_run(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    await _node(
        db_session, project_id, NodeKind.ENDPOINT, "POST api/users", source_file=_CTRL
    )

    selector = ImpactSelector(db_session, resolver=CrossLayerResolver(db_session))
    result = await selector.select(project_id, ChangeSet.of(["config/app.php"]))

    assert result.unmapped_files == ("config/app.php",)
    assert result.scope_uncertain and result.recommend_full_run
    assert not result.confidently_scoped
    assert result.selected == ()  # no false confidence


async def test_mixed_change_still_widens_to_full_run(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    endpoint = await _node(
        db_session, project_id, NodeKind.ENDPOINT, "POST api/users", source_file=_CTRL
    )
    case_api = await _case(db_session, project_id, endpoint.id)

    selector = ImpactSelector(db_session, resolver=CrossLayerResolver(db_session))
    result = await selector.select(
        project_id, ChangeSet.of([_CTRL, "infra/Dockerfile"])
    )

    assert case_api.id in result.case_ids  # found a confidently-scoped test...
    assert result.unmapped_files == ("infra/Dockerfile",)
    assert result.recommend_full_run  # ...but an unmapped file still forces a full run
    assert not result.confidently_scoped


async def test_empty_changeset_selects_nothing_confidently(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    selector = ImpactSelector(db_session, resolver=CrossLayerResolver(db_session))
    result = await selector.select(project_id, ChangeSet.of([]))
    assert result.selected == () and result.unmapped_files == ()
    assert result.confidently_scoped and not result.recommend_full_run


async def test_selection_is_deterministic_and_project_scoped(
    db_session: AsyncSession,
) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    endpoint_a = await _node(
        db_session, project_a, NodeKind.ENDPOINT, "POST api/users", source_file=_CTRL
    )
    case_a = await _case(db_session, project_a, endpoint_a.id)
    # Project B has a node + case for the SAME file — must not leak into A.
    endpoint_b = await _node(
        db_session, project_b, NodeKind.ENDPOINT, "POST api/users", source_file=_CTRL
    )
    case_b = await _case(db_session, project_b, endpoint_b.id)

    selector = ImpactSelector(db_session, resolver=CrossLayerResolver(db_session))
    first = await selector.select(project_a, ChangeSet.of([_CTRL]))
    second = await selector.select(project_a, ChangeSet.of([_CTRL]))

    assert first == second  # deterministic (value-equal)
    assert first.case_ids == {case_a.id}
    assert case_b.id not in first.case_ids


async def test_resolver_failure_keeps_seed_and_skips_expansion(
    db_session: AsyncSession,
) -> None:
    class _RaisingResolver:
        async def impact(self, project_id: uuid.UUID, node_id: uuid.UUID) -> Impact:
            raise NodeNotFoundError("node vanished mid-flight")

    project_id = await _project(db_session)
    endpoint = await _node(
        db_session, project_id, NodeKind.ENDPOINT, "POST api/users", source_file=_CTRL
    )
    page = await _node(
        db_session,
        project_id,
        NodeKind.PAGE,
        "/users",
        source_file="resources/Users.vue",
    )
    await _edge(db_session, project_id, page.id, endpoint.id, EdgeKind.CALLS)
    case_api = await _case(db_session, project_id, endpoint.id)
    await _case(db_session, project_id, page.id)  # would be pulled in IF expansion ran

    selector = ImpactSelector(db_session, resolver=_RaisingResolver())
    result = await selector.select(project_id, ChangeSet.of([_CTRL]))

    # The seed's own case is kept; expansion was skipped, so the page case is not.
    assert result.case_ids == {case_api.id}
    assert result.confidently_scoped  # the file mapped — a resolver miss ≠ unmapped
