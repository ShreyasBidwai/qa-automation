"""Mode B autonomous orchestrator (T8.2) — fast tests.

Inject a STUB generator + STUB runner + a fake resolver and Brain/case fixtures
(no real generation or browser): FullSweep drives the whole pipeline in
deterministic order and returns ranked findings; ChangeImpact runs only impacted
targets; an uncertain scope forces a full sweep (honesty); existing current cases
are reused (human edits never clobbered); bounds and project-scoping hold.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.cross_layer import Impact, Subgraph
from app.execution.types import (
    DbHandle,
    DbRole,
    ExecutionResult,
    PestScript,
    TargetEnv,
)
from app.impact.selector import ChangeSet
from app.models.enums import CaseOrigin, NodeKind, Outcome
from app.models.model_node import ModelNode
from app.modes.errors import ModeBError
from app.modes.mode_b import ModeBBounds, ModeBOrchestrator
from app.modes.selection import (
    FullSweepStrategy,
    SelectionStrategyKind,
    Target,
    build_selection_strategy,
)
from app.repositories.node_repository import NodeRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository
from tests.factories import make_node, make_project, make_test_case, make_test_script

_ENV = TargetEnv(
    app_path="/unused",
    execution_db=DbHandle("sqlite://:memory:", DbRole.WRITABLE_TEST, ephemeral=True),
    evidence_dir="/tmp/mode-b-evidence",
)


class _FakeResolver:
    """journey + impact for the reporting pipeline; distinct anchor per node so
    findings don't collapse, and an empty blast radius (no impact expansion)."""

    async def journey(
        self, project_id: uuid.UUID, node_id: uuid.UUID, max_depth: int = 3
    ) -> Subgraph:
        root = ModelNode(
            project_id=project_id,
            kind=NodeKind.ENDPOINT,
            name=f"ep-{node_id}",
            attributes={},
        )
        return Subgraph(root=root, nodes=(root,), edges=())

    async def impact(self, project_id: uuid.UUID, node_id: uuid.UUID) -> Impact:
        node = ModelNode(
            project_id=project_id, kind=NodeKind.ENDPOINT, name="anchor", attributes={}
        )
        return Impact(node=node)


class _StubGenerator:
    """Generates a real case + script for a target; records what it was asked for."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.generated_for: list[uuid.UUID] = []

    async def generate(self, *, project_id: uuid.UUID, target: Target) -> PestScript:
        node_id = target.node_id
        self.generated_for.append(node_id)
        case = await TestCaseRepository(self._session).add(
            make_test_case(project_id, target_node=node_id)
        )
        script = await TestScriptRepository(self._session).add(
            make_test_script(project_id, case.id)
        )
        return PestScript(
            test_case_id=case.id,
            script_id=script.id,
            name=f"gen-{node_id.hex[:8]}",
            code=script.code,
        )


class _StubRunner:
    framework = "stub"

    def __init__(self, outcome: Outcome = Outcome.FAIL) -> None:
        self._outcome = outcome
        self.ran: list[PestScript] = []

    def run(
        self, scripts: list[PestScript], target_env: TargetEnv
    ) -> list[ExecutionResult]:
        self.ran = list(scripts)
        return [
            ExecutionResult(
                test_case_id=s.test_case_id,
                script_id=s.script_id,
                name=s.name,
                outcome=self._outcome,
                evidence_ref=f"ev/{s.name}",
            )
            for s in scripts
        ]

    def teardown(self, target_env: TargetEnv) -> None:
        return None


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
    attributes = {} if source_file is None else {"source_file": source_file}
    return await NodeRepository(session).add(
        make_node(project_id, kind=kind, name=name, attributes=attributes)
    )


async def _seed_case(
    session: AsyncSession,
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    *,
    with_script: bool = True,
    **overrides: object,
):
    case = await TestCaseRepository(session).add(
        make_test_case(project_id, target_node=node_id, **overrides)
    )
    if with_script:
        await TestScriptRepository(session).add(make_test_script(project_id, case.id))
    return case


def _orchestrator(
    session: AsyncSession,
    generator: _StubGenerator,
    runner: _StubRunner,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> ModeBOrchestrator:
    return ModeBOrchestrator(
        session=session,
        runner=runner,
        target_env=_ENV,
        resolver=_FakeResolver(),
        generator=generator,
        clock=clock,
    )


async def test_full_sweep_drives_pipeline_and_returns_ranked_findings(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    endpoint = await _node(db_session, project_id, NodeKind.ENDPOINT, "GET api/orders")
    page = await _node(db_session, project_id, NodeKind.PAGE, "/orders")
    # A table node is not a testable target (no executable case targets it).
    table = await _node(db_session, project_id, NodeKind.TABLE, "orders")

    generator = _StubGenerator(db_session)
    runner = _StubRunner(Outcome.FAIL)
    orchestrator = _orchestrator(db_session, generator, runner)
    strategy = build_selection_strategy(
        SelectionStrategyKind.FULL_SWEEP, session=db_session
    )

    report = await orchestrator.run(
        project_id=project_id, strategy=strategy, bounds=ModeBBounds(max_targets=10)
    )

    assert report.strategy is SelectionStrategyKind.FULL_SWEEP
    assert report.full_sweep_fallback is False
    assert report.targets_selected == 2  # endpoint + page; the table is not testable
    assert report.cases_generated == 2 and report.cases_reused == 0
    assert set(generator.generated_for) == {endpoint.id, page.id}
    assert table.id not in generator.generated_for
    assert len(report.ranked_findings) == 2  # one per failing target
    # Deterministic target ordering.
    first = await FullSweepStrategy(db_session).select(project_id)
    second = await FullSweepStrategy(db_session).select(project_id)
    assert first.targets == second.targets


async def test_change_impact_runs_only_impacted_targets(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    changed = await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "GET api/orders",
        source_file="app/Http/Controllers/OrdersController.php",
    )
    unrelated = await _node(
        db_session,
        project_id,
        NodeKind.ENDPOINT,
        "GET api/users",
        source_file="app/Http/Controllers/UsersController.php",
    )
    changed_case = await _seed_case(db_session, project_id, changed.id)
    await _seed_case(db_session, project_id, unrelated.id)

    generator = _StubGenerator(db_session)
    runner = _StubRunner(Outcome.PASS)
    orchestrator = _orchestrator(db_session, generator, runner)
    strategy = build_selection_strategy(
        SelectionStrategyKind.CHANGE_IMPACT,
        session=db_session,
        resolver=_FakeResolver(),
        changeset=ChangeSet.of(["app/Http/Controllers/OrdersController.php"]),
    )

    report = await orchestrator.run(
        project_id=project_id, strategy=strategy, bounds=ModeBBounds(max_targets=10)
    )

    assert report.strategy is SelectionStrategyKind.CHANGE_IMPACT
    assert report.full_sweep_fallback is False
    assert report.targets_selected == 1  # only the impacted endpoint
    assert report.cases_reused == 1 and report.cases_generated == 0
    assert generator.generated_for == []  # existing case reused, nothing generated
    assert len(runner.ran) == 1
    assert runner.ran[0].test_case_id == changed_case.id  # the unrelated one excluded


async def test_scope_uncertain_falls_back_to_full_sweep(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    ep_a = await _node(
        db_session, project_id, NodeKind.ENDPOINT, "GET api/a", source_file="app/A.php"
    )
    ep_b = await _node(db_session, project_id, NodeKind.ENDPOINT, "GET api/b")

    generator = _StubGenerator(db_session)
    runner = _StubRunner(Outcome.PASS)
    orchestrator = _orchestrator(db_session, generator, runner)
    # A changed file that maps to NO node → ImpactSelector reports scope_uncertain.
    strategy = build_selection_strategy(
        SelectionStrategyKind.CHANGE_IMPACT,
        session=db_session,
        resolver=_FakeResolver(),
        changeset=ChangeSet.of(["config/unmapped.php"]),
    )

    report = await orchestrator.run(
        project_id=project_id, strategy=strategy, bounds=ModeBBounds(max_targets=10)
    )

    assert report.full_sweep_fallback is True  # honesty: widened to a full sweep
    assert report.strategy is SelectionStrategyKind.CHANGE_IMPACT  # requested kind kept
    assert report.targets_selected == 2  # ALL testable nodes, not the narrowed set
    assert set(generator.generated_for) == {ep_a.id, ep_b.id}


async def test_existing_human_edited_case_is_reused_never_clobbered(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    endpoint = await _node(db_session, project_id, NodeKind.ENDPOINT, "GET api/orders")
    human_case = await _seed_case(
        db_session,
        project_id,
        endpoint.id,
        edited_by_human=True,
        origin=CaseOrigin.EDITED,
        edited_by="alice",
    )

    generator = _StubGenerator(db_session)
    runner = _StubRunner(Outcome.PASS)
    orchestrator = _orchestrator(db_session, generator, runner)
    strategy = build_selection_strategy(
        SelectionStrategyKind.FULL_SWEEP, session=db_session
    )

    report = await orchestrator.run(
        project_id=project_id, strategy=strategy, bounds=ModeBBounds(max_targets=10)
    )

    assert report.cases_reused == 1 and report.cases_generated == 0
    assert generator.generated_for == []  # generator never touched the human edit
    assert len(runner.ran) == 1 and runner.ran[0].test_case_id == human_case.id
    reloaded = await TestCaseRepository(db_session).get(project_id, human_case.id)
    assert reloaded is not None
    assert reloaded.edited_by_human is True and reloaded.is_current is True


async def test_case_without_script_falls_through_to_generation(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    endpoint = await _node(db_session, project_id, NodeKind.ENDPOINT, "GET api/x")
    await _seed_case(db_session, project_id, endpoint.id, with_script=False)

    generator = _StubGenerator(db_session)
    runner = _StubRunner(Outcome.PASS)
    orchestrator = _orchestrator(db_session, generator, runner)
    strategy = build_selection_strategy(
        SelectionStrategyKind.FULL_SWEEP, session=db_session
    )

    report = await orchestrator.run(
        project_id=project_id, strategy=strategy, bounds=ModeBBounds(max_targets=10)
    )

    # The current case has no runnable script → Mode B generates one.
    assert generator.generated_for == [endpoint.id]
    assert report.cases_generated == 1 and report.cases_reused == 0


async def test_max_targets_bound_is_enforced(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    for i in range(3):
        await _node(db_session, project_id, NodeKind.ENDPOINT, f"GET api/{i}")

    generator = _StubGenerator(db_session)
    runner = _StubRunner(Outcome.PASS)
    orchestrator = _orchestrator(db_session, generator, runner)
    strategy = build_selection_strategy(
        SelectionStrategyKind.FULL_SWEEP, session=db_session
    )

    report = await orchestrator.run(
        project_id=project_id, strategy=strategy, bounds=ModeBBounds(max_targets=1)
    )

    assert report.targets_selected == 1  # capped, despite 3 testable nodes
    assert len(generator.generated_for) == 1
    assert len(runner.ran) == 1


async def test_time_bound_stops_the_ensure_loop(db_session: AsyncSession) -> None:
    project_id = await _project(db_session)
    for i in range(3):
        await _node(db_session, project_id, NodeKind.ENDPOINT, f"GET api/{i}")

    # Clock: start=0, first target sees 0 (<1, processed), second sees 5 (>=1 → stop).
    ticks = iter([0.0, 0.0, 5.0, 5.0])

    def clock() -> float:
        return next(ticks)

    generator = _StubGenerator(db_session)
    runner = _StubRunner(Outcome.PASS)
    orchestrator = _orchestrator(db_session, generator, runner, clock=clock)
    strategy = build_selection_strategy(
        SelectionStrategyKind.FULL_SWEEP, session=db_session
    )

    report = await orchestrator.run(
        project_id=project_id,
        strategy=strategy,
        bounds=ModeBBounds(max_targets=10, max_seconds=1.0),
    )

    assert report.targets_selected == 3  # all selected (count bound is 10)
    assert report.cases_generated == 1  # but only one ensured before time ran out
    assert len(runner.ran) == 1


async def test_run_is_project_scoped(db_session: AsyncSession) -> None:
    project_a = await _project(db_session)
    project_b = await _project(db_session)
    await _node(db_session, project_a, NodeKind.ENDPOINT, "GET api/a")
    await _node(db_session, project_b, NodeKind.ENDPOINT, "GET api/b")

    generator = _StubGenerator(db_session)
    runner = _StubRunner(Outcome.PASS)
    orchestrator = _orchestrator(db_session, generator, runner)
    strategy = build_selection_strategy(
        SelectionStrategyKind.FULL_SWEEP, session=db_session
    )

    report = await orchestrator.run(
        project_id=project_a, strategy=strategy, bounds=ModeBBounds(max_targets=10)
    )

    # Only project A's node is swept — no cross-project bleed.
    assert report.targets_selected == 1


async def test_change_impact_factory_requires_changeset_and_resolver(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ModeBError):
        build_selection_strategy(
            SelectionStrategyKind.CHANGE_IMPACT,
            session=db_session,
            resolver=_FakeResolver(),  # changeset missing
        )
    with pytest.raises(ModeBError):
        build_selection_strategy(
            SelectionStrategyKind.CHANGE_IMPACT,
            session=db_session,
            changeset=ChangeSet.of(["x"]),  # resolver missing
        )
