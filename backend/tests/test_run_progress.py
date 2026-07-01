"""Run-progress events for the live run view (ADR-0050).

The emitter (ordered, best-effort, fresh-session), the emit seams across a real
Mode-B run + the stub demo run, that a failing emit never breaks a run, and the
replay + SSE-stream endpoints (authorized). The emitter commits independently, so
its events outlive the per-test rolled-back transaction — emitter/orchestrator/stub
tests use a committing sessionmaker and clean up by run_id; endpoint tests seed
through the app sessionmaker (committed inside the per-test transaction).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.composition import StubRunExecutor
from app.api.ports import RunRequest
from app.models.enums import JobKind, JobStatus, NodeKind, Outcome, RunMode
from app.models.run_event import RunEvent
from app.modes.mode_b import ModeBBounds, ModeBOrchestrator
from app.modes.selection import SelectionStrategyKind, build_selection_strategy
from app.progress import (
    PHASE_CRAWL,
    PHASE_EXECUTE,
    PHASE_GENERATE,
    PHASE_REVIEW,
    PHASE_RUN,
    PHASE_SELECT,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_STARTED,
    RunProgressEmitter,
    emit,
    install_emitter,
    is_terminal,
    reset_emitter,
)
from app.repositories.run_event_repository import RunEventRepository
from app.screenshots import store_screenshot
from app.screenshots import storage as screenshot_storage
from app.services.job_queue import JobQueue
from tests.factories import make_project


@pytest.fixture
def shot_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the screenshot indirection at a tmp dir so the serve endpoint (which
    runs in-process here) reads back what the test stored."""
    directory = tmp_path / "shots"
    monkeypatch.setattr(
        screenshot_storage,
        "get_settings",
        lambda: SimpleNamespace(screenshot_dir=str(directory)),
    )
    return directory
from tests.test_mode_b import (
    _ENV,
    _FakeResolver,
    _node,
    _project,
    _StubGenerator,
    _StubRunner,
)


@pytest_asyncio.fixture
async def committing_sm(
    test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A real, independently-committing sessionmaker — what the emitter uses in
    production (its commits are real, so tests clean up by run_id)."""
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _events_for(
    maker: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> list[RunEvent]:
    async with maker() as session:
        return await RunEventRepository(session).list_for_run(project_id, run_id)


async def _cleanup(
    maker: async_sessionmaker[AsyncSession], run_id: uuid.UUID
) -> None:
    async with maker() as session:
        await session.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
        await session.commit()


# --- emitter unit: ordering, no-op, best-effort, terminal --------------------


async def test_emitter_persists_events_in_seq_order(
    committing_sm: async_sessionmaker[AsyncSession],
) -> None:
    run_id, project_id = uuid.uuid4(), uuid.uuid4()
    emitter = RunProgressEmitter(committing_sm, run_id=run_id, project_id=project_id)
    try:
        await emitter.emit(phase=PHASE_RUN, step="run", status=STATUS_STARTED)
        await emitter.emit(
            phase=PHASE_GENERATE, step="gen x", status=STATUS_PASSED, detail={"n": "x"}
        )
        await emitter.emit(phase=PHASE_RUN, step="run", status=STATUS_PASSED)

        events = await _events_for(committing_sm, project_id, run_id)
        assert [e.seq for e in events] == [0, 1, 2]  # monotonic, deterministic
        assert [(e.phase, e.status) for e in events] == [
            (PHASE_RUN, STATUS_STARTED),
            (PHASE_GENERATE, STATUS_PASSED),
            (PHASE_RUN, STATUS_PASSED),
        ]
        assert events[1].detail == {"n": "x"}
        assert events[0].step == "run"
    finally:
        await _cleanup(committing_sm, run_id)


async def test_emitter_persists_a_step_screenshot_ref(
    committing_sm: async_sessionmaker[AsyncSession],
) -> None:
    # A crawl/execute step can carry an opaque screenshot ref — the live "browser
    # frame" the operator watches. It round-trips onto the event row verbatim.
    run_id, project_id = uuid.uuid4(), uuid.uuid4()
    ref = f"{project_id}/{'a' * 32}"
    emitter = RunProgressEmitter(committing_sm, run_id=run_id, project_id=project_id)
    try:
        await emitter.emit(
            phase=PHASE_CRAWL,
            step="Visited /",
            status=STATUS_PASSED,
            screenshot_ref=ref,
        )
        await emitter.emit(phase=PHASE_RUN, step="run", status=STATUS_PASSED)
        events = await _events_for(committing_sm, project_id, run_id)
        assert events[0].screenshot_ref == ref
        assert events[1].screenshot_ref is None  # not every step has a frame
    finally:
        await _cleanup(committing_sm, run_id)


async def test_emit_without_installed_emitter_is_a_silent_noop() -> None:
    # No emitter installed → must not raise and must record nothing.
    await emit(phase=PHASE_RUN, step="run", status=STATUS_STARTED)


async def test_emit_failure_is_swallowed_and_seq_still_advances() -> None:
    def _broken_sm() -> AsyncSession:  # called by emit → raises
        raise RuntimeError("db down")

    emitter = RunProgressEmitter(
        _broken_sm,  # type: ignore[arg-type]
        run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )
    # Best-effort: a failing write never propagates; seq advances regardless.
    await emitter.emit(phase=PHASE_RUN, step="run", status=STATUS_STARTED)
    await emitter.emit(phase=PHASE_RUN, step="run", status=STATUS_PASSED)
    assert emitter._seq == 2  # noqa: SLF001 — asserting the deterministic counter


def test_is_terminal_only_for_run_completion() -> None:
    assert is_terminal(PHASE_RUN, STATUS_PASSED)
    assert is_terminal(PHASE_RUN, STATUS_FAILED)
    assert not is_terminal(PHASE_RUN, STATUS_STARTED)
    assert not is_terminal(PHASE_EXECUTE, STATUS_FAILED)


# --- the emit seam across a real Mode-B run ----------------------------------

_EXPECTED_JOURNEY = [
    (PHASE_RUN, STATUS_STARTED),
    (PHASE_SELECT, STATUS_PASSED),
    (PHASE_GENERATE, STATUS_STARTED),
    (PHASE_GENERATE, STATUS_PASSED),
    (PHASE_EXECUTE, STATUS_STARTED),
    (PHASE_EXECUTE, STATUS_FAILED),
    (PHASE_REVIEW, STATUS_STARTED),
    (PHASE_REVIEW, STATUS_PASSED),
    (PHASE_RUN, STATUS_FAILED),
]


async def test_mode_b_run_emits_the_ordered_journey(
    db_session: AsyncSession,
    committing_sm: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await _project(db_session)
    await _node(db_session, project_id, NodeKind.ENDPOINT, "GET api/orders")

    run_id = uuid.uuid4()  # the durable run handle the emitter keys events by
    emitter = RunProgressEmitter(committing_sm, run_id=run_id, project_id=project_id)
    token = install_emitter(emitter)
    try:
        orchestrator = ModeBOrchestrator(
            session=db_session,
            runner=_StubRunner(Outcome.FAIL),
            target_env=_ENV,
            resolver=_FakeResolver(),
            generator=_StubGenerator(db_session),
        )
        strategy = build_selection_strategy(
            SelectionStrategyKind.FULL_SWEEP, session=db_session
        )
        await orchestrator.run(
            project_id=project_id,
            strategy=strategy,
            bounds=ModeBBounds(max_targets=10),
        )
    finally:
        reset_emitter(token)

    try:
        events = await _events_for(committing_sm, project_id, run_id)
        assert [e.seq for e in events] == list(range(len(events)))  # ordered, gapless
        assert [(e.phase, e.status) for e in events] == _EXPECTED_JOURNEY
        # the per-test execute step carries which test + its outcome
        exec_fail = next(
            e for e in events if e.phase == PHASE_EXECUTE and e.status == STATUS_FAILED
        )
        assert exec_fail.detail is not None and exec_fail.detail["outcome"] == "fail"
    finally:
        await _cleanup(committing_sm, run_id)


async def test_emit_failure_does_not_break_the_run(
    db_session: AsyncSession,
) -> None:
    def _broken_sm() -> AsyncSession:
        raise RuntimeError("db down")

    project_id = await _project(db_session)
    await _node(db_session, project_id, NodeKind.ENDPOINT, "GET api/orders")

    emitter = RunProgressEmitter(
        _broken_sm,  # type: ignore[arg-type]
        run_id=uuid.uuid4(),
        project_id=project_id,
    )
    token = install_emitter(emitter)
    try:
        orchestrator = ModeBOrchestrator(
            session=db_session,
            runner=_StubRunner(Outcome.FAIL),
            target_env=_ENV,
            resolver=_FakeResolver(),
            generator=_StubGenerator(db_session),
        )
        strategy = build_selection_strategy(
            SelectionStrategyKind.FULL_SWEEP, session=db_session
        )
        # Every emit raises inside the emitter and is swallowed — the run still
        # completes normally and produces its finding.
        report = await orchestrator.run(
            project_id=project_id,
            strategy=strategy,
            bounds=ModeBBounds(max_targets=10),
        )
    finally:
        reset_emitter(token)

    assert report.status == "failed"
    assert len(report.ranked_findings) == 1


# --- the stub/demo run emits a believable sequence ---------------------------


async def test_stub_run_executor_emits_a_believable_sequence(
    db_session: AsyncSession,
    committing_sm: async_sessionmaker[AsyncSession],
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()

    run_id = uuid.uuid4()
    emitter = RunProgressEmitter(committing_sm, run_id=run_id, project_id=project.id)
    token = install_emitter(emitter)
    try:
        await StubRunExecutor().execute(
            session=db_session,
            project_id=project.id,
            request=RunRequest(mode=RunMode.B),
        )
    finally:
        reset_emitter(token)

    try:
        events = await _events_for(committing_sm, project.id, run_id)
        assert [(e.phase, e.status) for e in events] == [
            (PHASE_RUN, STATUS_STARTED),
            (PHASE_GENERATE, STATUS_PASSED),
            (PHASE_EXECUTE, STATUS_STARTED),
            (PHASE_EXECUTE, STATUS_FAILED),
            (PHASE_REVIEW, STATUS_PASSED),
            (PHASE_RUN, STATUS_FAILED),  # terminal — ends the live stream
        ]
        assert is_terminal(events[-1].phase, events[-1].status)
    finally:
        await _cleanup(committing_sm, run_id)


# --- the read endpoints: replay + SSE stream + authz -------------------------


async def _personal_org_id(client: AsyncClient) -> uuid.UUID:
    body = (await client.get("/api/v1/orgs")).json()
    for org in body["items"]:
        if org["is_personal"]:
            return uuid.UUID(org["id"])
    raise AssertionError("authed user has no personal org")


async def _seed_run_events(
    app: FastAPI,
    org_id: uuid.UUID,
    sequence: list[tuple[str, str]],
    *,
    job_status: JobStatus,
    screenshot_at: dict[int, str] | None = None,
) -> uuid.UUID:
    """Commit a project + a RUN job + the given (phase, status) events; return job id.

    ``screenshot_at`` maps a seq → an opaque screenshot ref to attach to that event.
    """
    shots = screenshot_at or {}
    async with app.state.sessionmaker() as session:
        project = make_project(org_id=org_id)
        session.add(project)
        await session.flush()
        job = await JobQueue(session).enqueue(
            kind=JobKind.RUN, project_id=project.id, mode="mode_b", max_attempts=1
        )
        job.status = job_status
        job_id = job.id
        for seq, (phase, status) in enumerate(sequence):
            session.add(
                RunEvent(
                    run_id=job_id,
                    project_id=project.id,
                    seq=seq,
                    phase=phase,
                    step=f"step {seq}",
                    status=status,
                    detail={"seq": seq},
                    screenshot_ref=shots.get(seq),
                )
            )
        await session.commit()
    return job_id


def _parse_sse(text: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for block in text.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:") :].strip()))
    return frames


async def test_get_run_events_replays_in_order_with_cursor(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    job_id = await _seed_run_events(
        app,
        org_id,
        [
            (PHASE_RUN, STATUS_STARTED),
            (PHASE_EXECUTE, STATUS_FAILED),
            (PHASE_RUN, STATUS_FAILED),
        ],
        job_status=JobStatus.SUCCEEDED,
    )

    body = (await client.get(f"/api/v1/runs/{job_id}/events")).json()
    assert body["run_id"] == str(job_id)
    assert [e["seq"] for e in body["events"]] == [0, 1, 2]
    assert [(e["phase"], e["status"]) for e in body["events"]] == [
        (PHASE_RUN, STATUS_STARTED),
        (PHASE_EXECUTE, STATUS_FAILED),
        (PHASE_RUN, STATUS_FAILED),
    ]
    assert body["events"][0]["detail"] == {"seq": 0}

    # after_seq cursor returns only newer events (incremental polling).
    page = (await client.get(f"/api/v1/runs/{job_id}/events?after_seq=0")).json()
    assert [e["seq"] for e in page["events"]] == [1, 2]


async def test_stream_run_events_delivers_an_in_progress_run_over_sse(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    # Job still RUNNING (in-progress), events already emitted incl. the terminal one
    # so the stream drains them from the live table and closes promptly.
    job_id = await _seed_run_events(
        app,
        org_id,
        [
            (PHASE_RUN, STATUS_STARTED),
            (PHASE_GENERATE, STATUS_PASSED),
            (PHASE_EXECUTE, STATUS_FAILED),
            (PHASE_RUN, STATUS_FAILED),
        ],
        job_status=JobStatus.RUNNING,
    )

    resp = await client.get(f"/api/v1/runs/{job_id}/events/stream")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse(resp.text)
    assert [f["seq"] for f in frames] == [0, 1, 2, 3]
    assert (frames[-1]["phase"], frames[-1]["status"]) == (PHASE_RUN, STATUS_FAILED)


async def test_stream_closes_when_job_is_terminal_without_a_terminal_event(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    # No terminal run event, but the job is terminal → the stream drains + closes.
    job_id = await _seed_run_events(
        app,
        org_id,
        [(PHASE_RUN, STATUS_STARTED), (PHASE_EXECUTE, STATUS_PASSED)],
        job_status=JobStatus.SUCCEEDED,
    )

    resp = await client.get(f"/api/v1/runs/{job_id}/events/stream")
    assert resp.status_code == 200
    assert [f["seq"] for f in _parse_sse(resp.text)] == [0, 1]


async def test_run_events_endpoints_require_a_known_authorized_run(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    missing = uuid.uuid4()
    assert (await client.get(f"/api/v1/runs/{missing}/events")).status_code == 404
    assert (
        await client.get(f"/api/v1/runs/{missing}/events/stream")
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/runs/{missing}/events/screenshot?seq=0")
    ).status_code == 404


# --- the live "browser frame": has_screenshot + the per-seq serve endpoint ----


async def test_replay_flags_steps_that_have_a_screenshot(
    authed_client: tuple[AsyncClient, FastAPI], shot_dir
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    ref = store_screenshot(b"\x89PNG-frame")  # default (monkeypatched tmp) dir
    job_id = await _seed_run_events(
        app,
        org_id,
        [(PHASE_RUN, STATUS_STARTED), (PHASE_CRAWL, STATUS_PASSED)],
        job_status=JobStatus.RUNNING,
        screenshot_at={1: ref},
    )

    events = (await client.get(f"/api/v1/runs/{job_id}/events")).json()["events"]
    # has_screenshot is exposed; the opaque ref itself never is.
    assert events[0]["has_screenshot"] is False
    assert events[1]["has_screenshot"] is True
    assert "screenshot_ref" not in events[1]


async def test_event_screenshot_is_served_by_seq_to_an_authorized_caller(
    authed_client: tuple[AsyncClient, FastAPI], shot_dir
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    ref = store_screenshot(b"\x89PNG-the-frame")
    job_id = await _seed_run_events(
        app,
        org_id,
        [(PHASE_RUN, STATUS_STARTED), (PHASE_CRAWL, STATUS_PASSED)],
        job_status=JobStatus.RUNNING,
        screenshot_at={1: ref},
    )

    resp = await client.get(f"/api/v1/runs/{job_id}/events/screenshot?seq=1")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == b"\x89PNG-the-frame"

    # A step with no screenshot, and an unknown seq, both 404 (existence not leaked).
    assert (
        await client.get(f"/api/v1/runs/{job_id}/events/screenshot?seq=0")
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/runs/{job_id}/events/screenshot?seq=99")
    ).status_code == 404


async def test_event_screenshot_404_when_ref_recorded_but_bytes_missing(
    authed_client: tuple[AsyncClient, FastAPI], shot_dir
) -> None:
    client, app = authed_client
    org_id = await _personal_org_id(client)
    # A well-formed ref the runner wrote on a filesystem this node can't reach
    # (ADR-0051) → 404, not a 500.
    job_id = await _seed_run_events(
        app,
        org_id,
        [(PHASE_CRAWL, STATUS_PASSED)],
        job_status=JobStatus.RUNNING,
        screenshot_at={0: uuid.uuid4().hex},
    )
    assert (
        await client.get(f"/api/v1/runs/{job_id}/events/screenshot?seq=0")
    ).status_code == 404
