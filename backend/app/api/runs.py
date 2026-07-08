"""Run + findings routes (TRD §4, ADR-0026).

POST enqueues an autonomous (mode_b) or authoring (mode_c) run as a background
job and returns the job handle as ``run_id``; status + the ranked findings are
polled. Findings are read through the reused reporting ranking.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.permissions import Permission
from app.models.ai_usage import AiUsage
from app.models.enums import JobKind, JobStatus, TriageStatus
from app.models.job import Job
from app.models.run_event import RunEvent
from app.models.user import User
from app.progress import is_terminal
from app.reporting import FindingDetailReader, rank_findings
from app.reporting.heal_reconciliation import superseded_finding_ids
from app.reporting.open_findings import OpenFindingsReader
from app.reporting.project_summary import pass_rate
from app.repositories.ai_usage_repository import (
    AiUsageRepository,
    RunUsageTotals,
    UsageBucket,
    aggregate,
)
from app.repositories.finding_repository import FindingRepository
from app.repositories.finding_triage_repository import FindingTriageRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.run_event_repository import RunEventRepository
from app.repositories.run_repository import RunRepository
from app.screenshots import get_screenshot
from app.services.job_queue import JobQueue

from .authz import authorize_project
from .deps import CurrentUser, get_session
from .finding_view import build_finding_response
from .jobs import dispatch_job
from .ports import run_request_to_payload, to_run_request
from .quota import enforce_org_can_run
from .schemas import (
    ActiveRunResponse,
    AiUsageBucket,
    AiUsageRecord,
    CiSummaryResponse,
    FindingResponse,
    FindingsResponse,
    RunCreate,
    RunEventItem,
    RunEventsResponse,
    RunListItem,
    RunListResponse,
    RunPreferences,
    RunResponse,
    RunStatusResponse,
    RunUsageAggregate,
    RunUsageResponse,
    SeverityBreakdown,
    TriagePatch,
)

router = APIRouter(prefix="/api/v1", tags=["runs"])

# Live-stream pacing: poll the run_events table on this cadence, bounded so a stream
# can never hang forever (it normally closes on the terminal run event / a terminal
# job status well before the cap). ~5 minutes of headroom for a real run.
_STREAM_POLL_SECONDS = 0.25
_STREAM_MAX_POLLS = 1200
_TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
)


async def _authorized_run_job(
    run_id: uuid.UUID,
    *,
    session: AsyncSession,
    user: User,
    permission: Permission,
) -> Job:
    """Resolve a RUN job and RBAC-check its project (ADR-0033).

    404 for an unknown run OR a non-member of the project's org (existence not
    leaked); 403 if the caller is in the org but the role lacks ``permission``.
    """
    job = await JobQueue(session).get(run_id)
    if job is None or job.kind is not JobKind.RUN:
        raise HTTPException(status_code=404, detail="run not found")
    await authorize_project(session, job.project_id, user, permission)
    return job


@router.post("/projects/{project_id}/runs", status_code=202, response_model=RunResponse)
async def create_run(
    project_id: uuid.UUID,
    body: RunCreate,
    current_user: CurrentUser,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunResponse:
    project = await authorize_project(session, project_id, current_user, Permission.RUN)
    # Enqueue gate (ADR-0068 suspension + ADR-0069 run quota): may this org run?
    await enforce_org_can_run(session, project.org_id)
    run_request = to_run_request(body)
    # A run is non-idempotent (it persists a run + findings), so it gets a single
    # attempt — no auto-replay of partial side effects. The queue itself supports
    # retry-with-backoff (ADR-0034) for jobs that opt in.
    job = await JobQueue(session).enqueue(
        kind=JobKind.RUN,
        project_id=project_id,
        mode=body.mode,
        payload=run_request_to_payload(run_request),
        max_attempts=1,
    )
    # Commit now so the durable row is visible to whoever executes it.
    await session.commit()
    # Decoupled topology (B5, ADR-0036): only dispatch in-process if THIS node
    # carries an executor (single-box stub). The slim/control-plane backend has
    # none — the run stays queued for a toolchain-present runner worker to claim.
    executor = getattr(request.app.state, "run_executor", None)
    if executor is not None:
        background_tasks.add_task(
            dispatch_job,
            sessionmaker=request.app.state.sessionmaker,
            job_id=job.id,
            executor=executor,
        )
    return RunResponse(run_id=job.id, status=job.status.value)


def _run_preferences(payload: dict[str, Any]) -> RunPreferences:
    """A readable summary of the choices a run was started with, from its durable job
    payload (ADR-0062). Prompt TEXT is deliberately not surfaced (it can hold sensitive
    detail); only the layer flag is."""
    changeset = payload.get("changeset") or []
    return RunPreferences(
        mode=str(payload.get("mode", "")),
        strategy=payload.get("strategy"),
        layers=payload.get("layers"),
        modules=payload.get("modules"),
        changeset_size=len(changeset) if changeset else None,
        layer=payload.get("layer"),
    )


@router.get("/projects/{project_id}/runs", response_model=RunListResponse)
async def list_project_runs(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunListResponse:
    await authorize_project(session, project_id, current_user, Permission.VIEW)
    run_repo = RunRepository(session)
    runs = await run_repo.list_for_project(project_id, limit=limit, offset=offset)
    run_ids = [run.id for run in runs]
    counts = await ResultRepository(session).outcome_counts_for_runs(
        project_id, run_ids
    )
    # Per-run open-findings severity breakdown — one batched, reused query (ADR-0048).
    severity = await OpenFindingsReader(session).severity_counts_by_run(run_ids)
    # A run's id equals its job's id (ADR-0036), so one batched fetch gives every run's
    # preferences (the choices it was started with) for the recent-runs list.
    jobs = await JobQueue(session).get_many(run_ids)
    items = [
        RunListItem(
            id=run.id,
            run_number=run.run_number,
            mode=run.mode.value,
            status=run.status,
            created_at=run.created_at,
            finished_at=run.finished_at,
            pass_rate=pass_rate(counts.get(run.id)),
            severity_breakdown=SeverityBreakdown(**severity.get(run.id, {})),
            preferences=(
                _run_preferences(jobs[run.id].payload) if run.id in jobs else None
            ),
        )
        for run in runs
    ]
    return RunListResponse(
        items=items,
        total=await run_repo.count_for_project(project_id),
        limit=limit,
        offset=offset,
    )


@router.get("/runs/active", response_model=ActiveRunResponse)
async def active_run(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActiveRunResponse:
    """The caller's current in-progress run, or an all-null response if none.

    Declared BEFORE ``/runs/{run_id}`` so "active" isn't parsed as a run id. Scoped by
    org membership (the query only sees runs in the user's projects) — no leak."""
    # A running run is only "active" while its lease is fresher than the watchdog bound;
    # beyond that it's orphaned/wedged, not ongoing (ADR-0067).
    job = await JobQueue(session).latest_active_run_for_user(
        current_user.id,
        running_ttl_seconds=get_settings().job_max_duration_seconds,
    )
    if job is None:
        return ActiveRunResponse()
    return ActiveRunResponse(
        run_id=job.id,
        project_id=job.project_id,
        mode=job.mode or "",
        status=job.status.value,
    )


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunStatusResponse:
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.VIEW,
    )
    # The run row carries the friendly number + timestamps (null until it exists —
    # a queued job or a mode-c authoring run produces no run). ADR-0048.
    run = (
        await RunRepository(session).get(job.project_id, job.run_id)
        if job.run_id is not None
        else None
    )
    return RunStatusResponse(
        run_id=job.id,
        project_id=job.project_id,
        mode=job.mode or "",
        status=job.status.value,
        summary=job.summary,
        run_number=run.run_number if run is not None else None,
        created_at=run.created_at if run is not None else None,
        finished_at=run.finished_at if run is not None else None,
    )


@router.delete("/runs/{run_id}", response_model=RunResponse)
async def cancel_run(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunResponse:
    """Cancel a run (RUN permission). A QUEUED run never starts; a RUNNING run stops
    cooperatively at the next generation boundary (mode_b checks the cancel flag) and
    its terminal status is not clobbered. Already-finished runs are unchanged."""
    job = await _authorized_run_job(
        run_id, session=session, user=current_user, permission=Permission.RUN
    )
    await JobQueue(session).cancel(run_id)
    await session.commit()
    refreshed = await JobQueue(session).get(run_id)
    return RunResponse(run_id=run_id, status=(refreshed or job).status.value)


@router.post("/runs/{run_id}/rerun", status_code=202, response_model=RunResponse)
async def rerun_run(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunResponse:
    """Start a fresh run with the SAME preferences as an existing one (RUN). Copies the
    original run's durable job payload verbatim (ADR-0062) — a faithful re-run without
    re-entering the options. The original run is untouched; a new run id is returned."""
    job = await _authorized_run_job(
        run_id, session=session, user=current_user, permission=Permission.RUN
    )
    new_job = await JobQueue(session).enqueue(
        kind=JobKind.RUN,
        project_id=job.project_id,  # same project — never re-targets elsewhere
        mode=job.mode,
        payload=dict(job.payload),  # the exact, already-validated preferences
        max_attempts=1,
    )
    await session.commit()
    executor = getattr(request.app.state, "run_executor", None)
    if executor is not None:
        background_tasks.add_task(
            dispatch_job,
            sessionmaker=request.app.state.sessionmaker,
            job_id=new_job.id,
            executor=executor,
        )
    return RunResponse(run_id=new_job.id, status=new_job.status.value)


@router.get("/runs/{run_id}/ci", response_model=CiSummaryResponse)
async def run_ci_summary(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CiSummaryResponse:
    """A CI/PR-gate verdict for a run (VIEW). Trigger with POST /projects/{id}/runs,
    then poll this until ``terminal`` and gate the pipeline on ``gate`` (block iff
    ``fail``). Fails on any open critical/major finding; minor findings don't block."""
    job = await _authorized_run_job(
        run_id, session=session, user=current_user, permission=Permission.VIEW
    )
    counts = (await OpenFindingsReader(session).severity_counts_by_run([run_id])).get(
        run_id, {}
    )
    critical = counts.get("critical", 0)
    major = counts.get("major", 0)
    minor = counts.get("minor", 0)
    terminal = job.status in _TERMINAL_JOB_STATUSES
    gate = (
        "pending"
        if not terminal
        else ("fail" if critical or major or job.status is JobStatus.FAILED else "pass")
    )
    return CiSummaryResponse(
        run_id=run_id,
        status=job.status.value,
        terminal=terminal,
        gate=gate,
        critical=critical,
        major=major,
        minor=minor,
    )


def _usage_bucket(bucket: UsageBucket) -> AiUsageBucket:
    return AiUsageBucket(
        call_count=bucket.call_count,
        total_cost_usd=bucket.total_cost_usd,
        input_tokens=bucket.input_tokens,
        output_tokens=bucket.output_tokens,
        cache_creation_input_tokens=bucket.cache_creation_input_tokens,
        cache_read_input_tokens=bucket.cache_read_input_tokens,
    )


def _usage_aggregate(agg: RunUsageTotals) -> RunUsageAggregate:
    return RunUsageAggregate(
        call_count=agg.call_count,
        available_call_count=agg.available_call_count,
        unavailable_call_count=agg.unavailable_call_count,
        error_count=agg.error_count,
        total_cost_usd=agg.total_cost_usd,
        input_tokens=agg.input_tokens,
        output_tokens=agg.output_tokens,
        cache_creation_input_tokens=agg.cache_creation_input_tokens,
        cache_read_input_tokens=agg.cache_read_input_tokens,
        per_phase={k: _usage_bucket(v) for k, v in agg.per_phase.items()},
        per_model={k: _usage_bucket(v) for k, v in agg.per_model.items()},
    )


def _usage_record(record: AiUsage) -> AiUsageRecord:
    return AiUsageRecord(
        phase=record.phase,
        model=record.model,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cache_creation_input_tokens=record.cache_creation_input_tokens,
        cache_read_input_tokens=record.cache_read_input_tokens,
        # Stored as Numeric (Decimal at runtime); the float schema field coerces it.
        total_cost_usd=record.total_cost_usd,
        model_cost_usd=record.model_cost_usd,
        usage_available=record.usage_available,
        is_error=record.is_error,
        created_at=record.created_at,
    )


@router.get("/runs/{run_id}/usage", response_model=RunUsageResponse)
async def get_run_usage(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunUsageResponse:
    """Per-call AI usage + the per-run aggregate (actual billed cost, ADR-0049).

    Authorized read (VIEW); a queued/authoring run with no executed run row returns
    an empty record set + zeroed aggregate.
    """
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.VIEW,
    )
    if job.run_id is None:
        return RunUsageResponse(run_id=run_id)
    records = await AiUsageRepository(session).list_for_run(job.project_id, job.run_id)
    return RunUsageResponse(
        run_id=run_id,
        aggregate=_usage_aggregate(aggregate(job.run_id, records)),
        records=[_usage_record(record) for record in records],
    )


# --- run-progress events for the live run view (ADR-0050) -------------------


def _event_item(event: RunEvent) -> RunEventItem:
    return RunEventItem(
        seq=event.seq,
        phase=event.phase,
        step=event.step,
        status=event.status,
        detail=event.detail,
        timestamp=event.created_at,
        has_screenshot=event.screenshot_ref is not None,
    )


def _sse_frame(event: RunEvent) -> str:
    """One Server-Sent-Events frame for a progress event."""
    payload = json.dumps(
        {
            "seq": event.seq,
            "phase": event.phase,
            "step": event.step,
            "status": event.status,
            "detail": event.detail,
            "timestamp": event.created_at.isoformat(),
            "has_screenshot": event.screenshot_ref is not None,
        }
    )
    return f"id: {event.seq}\nevent: progress\ndata: {payload}\n\n"


@router.get("/runs/{run_id}/events", response_model=RunEventsResponse)
async def get_run_events(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    after_seq: Annotated[int | None, Query(ge=0)] = None,
) -> RunEventsResponse:
    """Replay/poll the ordered progress events for a run (ADR-0050).

    Authorized read (VIEW). Works for a finished OR in-progress run; ``after_seq``
    returns only events past that cursor (cheap incremental polling).
    """
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.VIEW,
    )
    events = await RunEventRepository(session).list_for_run(
        job.project_id, run_id, after_seq=after_seq
    )
    return RunEventsResponse(
        run_id=run_id, events=[_event_item(event) for event in events]
    )


async def _run_event_sse(
    sessionmaker: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AsyncIterator[str]:
    """Yield SSE frames for a run's progress, live (ADR-0050).

    Polls the committed ``run_events`` (a seq cursor → only new events each round)
    and closes on the terminal run event, or when the job is terminal and drained,
    or at the safety cap — so a stream can never hang forever.
    """
    after = -1
    for _ in range(_STREAM_MAX_POLLS):
        async with sessionmaker() as session:
            events = await RunEventRepository(session).list_for_run(
                project_id, run_id, after_seq=after
            )
            job = await JobQueue(session).get(run_id)
        for event in events:
            after = event.seq
            yield _sse_frame(event)
            if is_terminal(event.phase, event.status):
                return
        job_done = job is None or job.status in _TERMINAL_JOB_STATUSES
        if not events and job_done:
            return  # drained + the run is over (no terminal event was emitted)
        await asyncio.sleep(_STREAM_POLL_SECONDS)


@router.get("/runs/{run_id}/events/stream")
async def stream_run_events(
    run_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
) -> StreamingResponse:
    """Stream a run's progress events live over SSE (ADR-0050). Authorized (VIEW).

    Authorizes up front on its own session, then streams from short read sessions
    off the app sessionmaker so newly-committed events become visible mid-run.
    """
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        job = await _authorized_run_job(
            run_id,
            session=session,
            user=current_user,
            permission=Permission.VIEW,
        )
        project_id = job.project_id
    return StreamingResponse(
        _run_event_sse(sessionmaker, project_id, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/events/screenshot")
async def get_run_event_screenshot(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    seq: Annotated[int, Query(ge=0)],
) -> Response:
    """Serve the screenshot bytes for one progress step — the live "browser frame".

    Authorized (VIEW) like every ``/runs`` route; the opaque ref never leaves the
    server (the client addresses a frame by its ``seq``). 404 for an unknown run /
    seq, a step with no screenshot, or bytes the runner wrote on a filesystem this
    node can't reach (ADR-0051) — existence is not leaked (ADR-0033).
    """
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.VIEW,
    )
    event = await RunEventRepository(session).get(job.project_id, run_id, seq)
    if event is None or event.screenshot_ref is None:
        raise HTTPException(status_code=404, detail="no screenshot for this step")
    data = get_screenshot(event.screenshot_ref)
    if data is None:
        raise HTTPException(status_code=404, detail="screenshot not available")
    return Response(content=data, media_type="image/png")


@router.get("/runs/{run_id}/findings", response_model=FindingsResponse)
async def get_run_findings(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FindingsResponse:
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.VIEW,
    )
    if job.run_id is None:  # not executed yet, or an authoring (mode_c) run
        return FindingsResponse(run_id=run_id, count=0, findings=[])
    findings = await FindingRepository(session).list_for_run(job.project_id, job.run_id)
    ranked = rank_findings(findings)
    detail = await FindingDetailReader(session).detail_for(
        job.project_id, job.run_id, ranked
    )
    # Triage block merged in one batched lookup by root_cause_key (no N+1, ADR-0027).
    triage = await FindingTriageRepository(session).get_for_keys(
        job.project_id, [f.root_cause_key for f in ranked]
    )
    # The run dashboard shows every finding but TAGS heal-superseded ones (addressing
    # drift) rather than dropping them — the per-run view is non-lossy by design.
    superseded = await superseded_finding_ids(session, ranked)
    items = [
        build_finding_response(
            f,
            detail[f.id],
            triage.get(f.root_cause_key),
            superseded_by_heal=f.id in superseded,
        )
        for f in ranked
    ]
    return FindingsResponse(run_id=run_id, count=len(items), findings=items)


@router.patch("/runs/{run_id}/findings/{finding_id}", response_model=FindingResponse)
async def triage_finding(
    run_id: uuid.UUID,
    finding_id: uuid.UUID,
    body: TriagePatch,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FindingResponse:
    """Set a finding's triage disposition, keyed by its root_cause_key (ADR-0027).

    The disposition follows the logical issue, not this run's row, so a later run
    producing the same root_cause_key inherits it. Requires the TRIAGE permission
    (a viewer is denied → 403); bad status → 422 (schema); unknown finding → 404.
    """
    job = await _authorized_run_job(
        run_id,
        session=session,
        user=current_user,
        permission=Permission.TRIAGE,
    )
    if job.run_id is None:
        raise HTTPException(status_code=404, detail="run not found")
    finding = await FindingRepository(session).get(job.project_id, finding_id)
    if finding is None or finding.run_id != job.run_id:
        raise HTTPException(status_code=404, detail="finding not found")

    record = await FindingTriageRepository(session).upsert(
        job.project_id,
        finding.root_cause_key,
        status=TriageStatus(body.status),
        note=body.note,
    )
    detail = await FindingDetailReader(session).detail_for(
        job.project_id, job.run_id, [finding]
    )
    superseded = await superseded_finding_ids(session, [finding])
    return build_finding_response(
        finding,
        detail[finding.id],
        record,
        superseded_by_heal=finding.id in superseded,
    )
