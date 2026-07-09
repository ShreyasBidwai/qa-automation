"""GenerationSignal capture + the eval aggregate (ADR-0070): outcomes are free labels,
and quality_summary rolls them up so a prompt/strategy change can be measured."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.generation_signal_repository import GenerationSignalRepository


async def test_record_and_quality_summary(db_session: AsyncSession) -> None:
    repo = GenerationSignalRepository(db_session)
    pid = uuid.uuid4()
    # A pass (accepted), a fail whose finding was rejected (false positive), an error
    # (bad generation), and a pass that needed a self-repair pass.
    await repo.record(
        project_id=pid,
        prompt_version="v1",
        strategy="full_sweep",
        outcome="pass",
        triage="accepted",
    )
    await repo.record(
        project_id=pid,
        prompt_version="v1",
        strategy="full_sweep",
        outcome="fail",
        triage="rejected",
    )
    await repo.record(
        project_id=pid, prompt_version="v1", strategy="full_sweep", outcome="error"
    )
    await repo.record(
        project_id=pid,
        prompt_version="v1",
        strategy="full_sweep",
        outcome="pass",
        repaired=True,
    )

    since = datetime.now(UTC) - timedelta(hours=1)
    quality = await repo.quality_summary(since=since, prompt_version="v1")
    assert quality.total == 4
    assert quality.by_outcome == {"pass": 2, "fail": 1, "error": 1}
    assert quality.repaired == 1
    assert quality.triaged == 2
    assert quality.triage_rejected == 1  # the one false positive


async def test_quality_summary_scopes_to_prompt_version(
    db_session: AsyncSession,
) -> None:
    repo = GenerationSignalRepository(db_session)
    pid = uuid.uuid4()
    await repo.record(
        project_id=pid, prompt_version="v1", strategy="s", outcome="error"
    )
    await repo.record(project_id=pid, prompt_version="v2", strategy="s", outcome="pass")

    since = datetime.now(UTC) - timedelta(hours=1)
    v2 = await repo.quality_summary(since=since, prompt_version="v2")
    assert v2.total == 1
    assert v2.by_outcome == {"pass": 1}  # v1's error is not counted under v2
