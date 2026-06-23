"""AI usage + actual billed cost capture (ADR-0049).

Parsing the ``claude -p --output-format json`` envelope (real shape + every
fallback), the per-run aggregate, the provider seam (output unchanged whether or
not parsing succeeds; usage recorded; is_error surfaced; stub records too), the
repository, the mode-b flush attributed to the run, and the read endpoint. No real
model is ever invoked — a fake CommandRunner returns injected envelopes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_cli import ClaudeCliProvider, CommandResult
from app.ai.stub import StubAIProvider
from app.ai.types import Subgraph, SubgraphNode
from app.ai.usage import (
    PHASE_GENERATION,
    PHASE_TRIAGE,
    CliUsage,
    UsageCollector,
    install_collector,
    parse_envelope,
    record_usage,
    reset_collector,
)
from app.core.config import Settings
from app.models.ai_usage import AiUsage
from app.models.enums import JobKind, JobStatus, NodeKind, Outcome
from app.modes.mode_b import ModeBBounds, ModeBOrchestrator
from app.modes.selection import SelectionStrategyKind, build_selection_strategy
from app.repositories.ai_usage_repository import AiUsageRepository, aggregate
from app.services.job_queue import JobQueue
from tests.factories import make_project, make_run
from tests.test_mode_b import (
    _ENV,
    _FakeResolver,
    _node,
    _project,
    _StubGenerator,
    _StubRunner,
)

# A real-shape envelope (mirrors the v2.1.186 probe): new input + cache split, the
# precomputed billed cost, and a per-model rollup.
_ENVELOPE = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "GENERATED CODE",
        "total_cost_usd": 0.0174089,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 60,
            "cache_creation_input_tokens": 7384,
            "cache_read_input_tokens": 17659,
        },
        "modelUsage": {
            "claude-opus-4-8": {
                "costUSD": 0.0168439,
                "inputTokens": 10,
                "outputTokens": 60,
            }
        },
    }
)


# --- parse_envelope: real shape + every fallback -----------------------------


def test_parse_real_envelope_extracts_text_cost_and_split_cache() -> None:
    text, usage = parse_envelope(_ENVELOPE, model="claude-opus-4-8")
    assert text == "GENERATED CODE"  # the result field, not the raw JSON
    assert usage.available and not usage.is_error
    assert usage.model == "claude-opus-4-8"
    assert usage.input_tokens == 10
    assert usage.output_tokens == 60
    # cache kept SEPARATE from input_tokens (ADR-0049).
    assert usage.cache_creation_input_tokens == 7384
    assert usage.cache_read_input_tokens == 17659
    assert usage.total_cost_usd == pytest.approx(0.0174089)
    assert usage.model_cost_usd == pytest.approx(0.0168439)


def test_parse_surfaces_is_error_honestly() -> None:
    envelope = json.dumps(
        {"result": "partial", "is_error": True, "usage": {"input_tokens": 5}}
    )
    text, usage = parse_envelope(envelope, model="m")
    assert text == "partial"
    assert usage.available and usage.is_error is True


def test_parse_non_json_falls_back_to_stdout_text_and_flags_unavailable() -> None:
    text, usage = parse_envelope("just some raw text", model="claude-opus-4-8")
    assert text == "just some raw text"  # stdout used as the output
    assert usage.available is False
    assert usage.model == "claude-opus-4-8"  # model still attributed
    assert usage.total_cost_usd is None and usage.input_tokens is None


def test_parse_json_without_usage_block_is_unavailable_but_keeps_text() -> None:
    text, usage = parse_envelope(json.dumps({"result": "hi", "is_error": True}))
    assert text == "hi"
    assert usage.available is False
    assert usage.is_error is True  # surfaced even with no usage block


def test_parse_json_without_result_uses_stdout_as_text() -> None:
    envelope = json.dumps({"usage": {"input_tokens": 3, "output_tokens": 4}})
    text, usage = parse_envelope(envelope)
    assert text == envelope  # no result field → fall back to raw stdout
    assert usage.available is True
    assert usage.input_tokens == 3 and usage.output_tokens == 4


def test_parse_model_cost_matches_dated_suffix_key() -> None:
    envelope = json.dumps(
        {
            "result": "x",
            "usage": {"input_tokens": 1},
            "modelUsage": {"claude-haiku-4-5-20251001": {"costUSD": 0.5}},
        }
    )
    _text, usage = parse_envelope(envelope, model="claude-haiku-4-5")
    assert usage.model_cost_usd == pytest.approx(0.5)


# --- the provider seam: behaviour unchanged; usage recorded ------------------


@pytest.fixture(autouse=True)
def _forbid_real_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("real `claude -p` subprocess was invoked in tests")

    monkeypatch.setattr("app.ai.claude_cli.subprocess.run", _boom)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
        "ai_max_attempts": 1,
        "ai_retry_base_delay_seconds": 0.0,
        "ai_retry_max_delay_seconds": 0.0,
        "ai_budget_strategy": "truncate",
    }
    values.update(overrides)
    return Settings(**values)


def _noop(_delay: float) -> None:
    return None


def _subgraph() -> Subgraph:
    return Subgraph(nodes=[SubgraphNode(id="n1", kind="endpoint", name="GET /x")])


def _runner_for(stdout: str, *, code: int = 0):
    def runner(argv: Sequence[str], stdin_text: str, timeout: float) -> CommandResult:
        return CommandResult(code, stdout, "")

    return runner


def _collecting():
    """A fresh collector installed for the test; returns (collector, reset)."""
    collector = UsageCollector()
    token = install_collector(collector)
    return collector, lambda: reset_collector(token)


def test_provider_requests_json_output_format() -> None:
    captured: dict[str, Any] = {}

    def runner(argv: Sequence[str], stdin_text: str, timeout: float) -> CommandResult:
        captured["argv"] = list(argv)
        return CommandResult(0, _ENVELOPE, "")

    ClaudeCliProvider(_settings(), runner=runner, sleep=_noop).generate(
        "p", _subgraph(), 5000
    )
    argv = captured["argv"]
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "json"


def test_provider_returns_result_text_and_records_usage() -> None:
    collector, reset = _collecting()
    try:
        provider = ClaudeCliProvider(
            _settings(ai_generate_model="claude-opus-4-8"),
            runner=_runner_for(_ENVELOPE),
            sleep=_noop,
        )
        out = provider.generate("p", _subgraph(), 5000)
    finally:
        reset()

    assert out == "GENERATED CODE"  # external behaviour unchanged: callers get text
    assert len(collector.records) == 1
    record = collector.records[0]
    assert record.phase == PHASE_GENERATION
    assert record.usage.available
    assert record.usage.total_cost_usd == pytest.approx(0.0174089)
    assert record.usage.cache_read_input_tokens == 17659


def test_provider_malformed_output_still_succeeds_and_flags_unavailable() -> None:
    collector, reset = _collecting()
    try:
        provider = ClaudeCliProvider(
            _settings(), runner=_runner_for("not json at all"), sleep=_noop
        )
        out = provider.generate("p", _subgraph(), 5000)
    finally:
        reset()

    # The call STILL succeeds with stdout as the text; usage flagged unavailable.
    assert out == "not json at all"
    assert len(collector.records) == 1
    assert collector.records[0].usage.available is False


def test_provider_output_is_identical_whether_or_not_usage_parses() -> None:
    good = ClaudeCliProvider(_settings(), runner=_runner_for(_ENVELOPE), sleep=_noop)
    bad_envelope = json.dumps({"result": "GENERATED CODE"})  # valid JSON, no usage
    bad = ClaudeCliProvider(_settings(), runner=_runner_for(bad_envelope), sleep=_noop)
    # Same model text out of both paths — capture never alters generation.
    assert good.generate("p", _subgraph(), 5000) == "GENERATED CODE"
    assert bad.generate("p", _subgraph(), 5000) == "GENERATED CODE"


def test_stub_provider_records_flagged_usage() -> None:
    collector, reset = _collecting()
    try:
        out = StubAIProvider().generate("p", _subgraph(), 5000)
    finally:
        reset()
    assert out.strip()  # canned stub output unchanged
    assert len(collector.records) == 1
    assert collector.records[0].usage.available is False
    assert collector.records[0].usage.model == "stub"


def test_record_usage_without_collector_is_a_silent_noop() -> None:
    # No collector installed → must not raise and must record nothing observable.
    record_usage(CliUsage.unavailable(model="m"), phase=PHASE_GENERATION)


# --- aggregate(): sums, per-phase, per-model, unavailable/errors -------------


def _usage_row(
    run_id: uuid.UUID,
    *,
    phase: str = PHASE_GENERATION,
    model: str | None = "claude-opus-4-8",
    cost: float | None = None,
    inp: int | None = None,
    out: int | None = None,
    cache_create: int | None = None,
    cache_read: int | None = None,
    available: bool = True,
    is_error: bool = False,
    project_id: uuid.UUID | None = None,
) -> AiUsage:
    return AiUsage(
        project_id=project_id or uuid.uuid4(),
        run_id=run_id,
        phase=phase,
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cache_creation_input_tokens=cache_create,
        cache_read_input_tokens=cache_read,
        total_cost_usd=cost,
        model_cost_usd=cost,
        usage_available=available,
        is_error=is_error,
    )


def test_aggregate_sums_cost_tokens_and_breaks_down_by_phase_and_model() -> None:
    run_id = uuid.uuid4()
    records = [
        _usage_row(run_id, model="opus", cost=0.02, inp=10, out=60, cache_read=100),
        _usage_row(run_id, model="opus", cost=0.03, inp=5, out=20, cache_create=50),
        _usage_row(
            run_id, phase=PHASE_TRIAGE, model="haiku", cost=0.01, inp=2, out=4
        ),
    ]
    agg = aggregate(run_id, records)

    assert agg.call_count == 3
    assert agg.total_cost_usd == pytest.approx(0.06)
    assert agg.input_tokens == 17 and agg.output_tokens == 84
    assert agg.cache_read_input_tokens == 100
    assert agg.cache_creation_input_tokens == 50
    # per-phase
    assert agg.per_phase[PHASE_GENERATION].total_cost_usd == pytest.approx(0.05)
    assert agg.per_phase[PHASE_TRIAGE].total_cost_usd == pytest.approx(0.01)
    # per-model
    assert agg.per_model["opus"].call_count == 2
    assert agg.per_model["opus"].total_cost_usd == pytest.approx(0.05)
    assert agg.per_model["haiku"].input_tokens == 2


def test_aggregate_counts_unavailable_and_errors_without_adding_cost() -> None:
    run_id = uuid.uuid4()
    records = [
        _usage_row(run_id, cost=0.02, inp=10),
        _usage_row(run_id, available=False, model="stub"),  # null cost/tokens
        _usage_row(run_id, cost=0.01, inp=5, is_error=True),
    ]
    agg = aggregate(run_id, records)
    assert agg.call_count == 3
    assert agg.available_call_count == 2
    assert agg.unavailable_call_count == 1
    assert agg.error_count == 1
    # Unavailable record contributes no cost/tokens.
    assert agg.total_cost_usd == pytest.approx(0.03)
    assert agg.input_tokens == 15


def test_aggregate_empty_is_all_zero() -> None:
    agg = aggregate(uuid.uuid4(), [])
    assert agg.call_count == 0
    assert agg.total_cost_usd == 0.0
    assert agg.per_phase == {} and agg.per_model == {}


# --- repository: add_all / list_for_run / aggregate_for_run (DB) -------------


async def test_repository_persists_lists_and_aggregates_scoped(
    db_session: AsyncSession,
) -> None:
    project = make_project()
    db_session.add(project)
    await db_session.flush()
    run_id, other_run = uuid.uuid4(), uuid.uuid4()

    repo = AiUsageRepository(db_session)
    await repo.add_all(
        [
            _usage_row(run_id, project_id=project.id, cost=0.02, inp=10, out=60),
            _usage_row(run_id, project_id=project.id, cost=0.03, inp=5, out=20),
            _usage_row(other_run, project_id=project.id, cost=9.9, inp=999),
        ]
    )

    rows = await repo.list_for_run(project.id, run_id)
    assert len(rows) == 2  # other run's row excluded

    agg = await repo.aggregate_for_run(project.id, run_id)
    assert agg.call_count == 2
    assert agg.total_cost_usd == pytest.approx(0.05)
    assert agg.input_tokens == 15 and agg.output_tokens == 80


# --- mode-b flush: usage persisted, attributed to the run --------------------


class _UsageRecordingGenerator:
    """A target generator that records a usage entry (as a provider would) then
    produces a runnable case, so the mode-b flush has something to persist."""

    def __init__(self, session: AsyncSession, usage: CliUsage) -> None:
        self._inner = _StubGenerator(session)
        self._usage = usage

    async def generate(self, *, project_id: uuid.UUID, target: Any) -> Any:
        record_usage(self._usage, phase=PHASE_GENERATION)
        return await self._inner.generate(project_id=project_id, target=target)


async def test_mode_b_persists_usage_attributed_to_the_run(
    db_session: AsyncSession,
) -> None:
    project_id = await _project(db_session)
    await _node(db_session, project_id, NodeKind.ENDPOINT, "GET api/orders")

    usage = CliUsage(
        available=True,
        model="claude-opus-4-8",
        input_tokens=10,
        output_tokens=60,
        cache_creation_input_tokens=7384,
        cache_read_input_tokens=17659,
        total_cost_usd=0.0174089,
        model_cost_usd=0.0168439,
    )
    orchestrator = ModeBOrchestrator(
        session=db_session,
        runner=_StubRunner(Outcome.FAIL),
        target_env=_ENV,
        resolver=_FakeResolver(),
        generator=_UsageRecordingGenerator(db_session, usage),
    )
    strategy = build_selection_strategy(
        SelectionStrategyKind.FULL_SWEEP, session=db_session
    )
    report = await orchestrator.run(
        project_id=project_id,
        strategy=strategy,
        bounds=ModeBBounds(max_targets=10),
    )

    rows = await AiUsageRepository(db_session).list_for_run(project_id, report.run_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.run_id == report.run_id  # attributed to the run created this sweep
    assert row.phase == PHASE_GENERATION
    assert row.total_cost_usd == Decimal("0.01740890")
    assert row.cache_read_input_tokens == 17659
    assert row.usage_available is True


# --- the read endpoint -------------------------------------------------------


async def _personal_org_id(client: AsyncClient) -> uuid.UUID:
    body = (await client.get("/api/v1/orgs")).json()
    for org in body["items"]:
        if org["is_personal"]:
            return uuid.UUID(org["id"])
    raise AssertionError("authed user has no personal org")


@pytest_asyncio.fixture
async def _seeded_run_with_usage(
    authed_client: tuple[AsyncClient, FastAPI],
) -> tuple[AsyncClient, uuid.UUID]:
    """A committed project + run + RUN job + two usage rows; returns (client, job_id)."""
    client, app = authed_client
    org_id = await _personal_org_id(client)
    async with app.state.sessionmaker() as session:
        project = make_project(org_id=org_id)
        session.add(project)
        await session.flush()
        run = make_run(project.id, run_number=1, status="failed")
        session.add(run)
        await session.flush()
        job = await JobQueue(session).enqueue(
            kind=JobKind.RUN, project_id=project.id, mode="mode_b", max_attempts=1
        )
        job.run_id = run.id
        job.status = JobStatus.SUCCEEDED
        session.add_all(
            [
                AiUsage(
                    project_id=project.id,
                    run_id=run.id,
                    phase=PHASE_GENERATION,
                    model="claude-opus-4-8",
                    input_tokens=10,
                    output_tokens=60,
                    cache_creation_input_tokens=7384,
                    cache_read_input_tokens=17659,
                    total_cost_usd=Decimal("0.01740890"),
                    model_cost_usd=Decimal("0.01684390"),
                    usage_available=True,
                    is_error=False,
                ),
                AiUsage(
                    project_id=project.id,
                    run_id=run.id,
                    phase=PHASE_GENERATION,
                    model="stub",
                    usage_available=False,
                    is_error=False,
                ),
            ]
        )
        job_id = job.id
        await session.commit()
    return client, job_id


async def test_get_run_usage_returns_records_and_aggregate(
    _seeded_run_with_usage: tuple[AsyncClient, uuid.UUID],
) -> None:
    client, job_id = _seeded_run_with_usage
    body = (await client.get(f"/api/v1/runs/{job_id}/usage")).json()

    assert body["run_id"] == str(job_id)
    assert len(body["records"]) == 2
    agg = body["aggregate"]
    assert agg["call_count"] == 2
    assert agg["available_call_count"] == 1
    assert agg["unavailable_call_count"] == 1
    assert agg["total_cost_usd"] == pytest.approx(0.0174089)
    assert agg["input_tokens"] == 10
    assert agg["cache_read_input_tokens"] == 17659  # kept separate from input_tokens
    assert agg["per_model"]["claude-opus-4-8"]["total_cost_usd"] == pytest.approx(
        0.0174089
    )


async def test_get_run_usage_unknown_run_is_404(
    authed_client: tuple[AsyncClient, FastAPI],
) -> None:
    client, _ = authed_client
    resp = await client.get(f"/api/v1/runs/{uuid.uuid4()}/usage")
    assert resp.status_code == 404
