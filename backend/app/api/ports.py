"""Ports the API drives — the seams to the existing orchestrators (ADR-0026).

Routes depend on these Protocols, not on concrete orchestrators, so the surface
is testable in the fast lane with stubs and wired to the real components in
composition. The contracts are shaped to the orchestrators' real signatures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RunMode
from app.modes.selection import SelectionStrategyKind

from .schemas import ModeBRunRequest, ModeCRunRequest


@dataclass(frozen=True)
class RunRequest:
    """A parsed, transport-agnostic run request handed to the executor."""

    mode: RunMode
    strategy: SelectionStrategyKind | None = None
    changeset: tuple[str, ...] = ()
    max_targets: int = 50
    prompt: str | None = None
    # Optional layer scope (ADR-0052); None = the full set (UI/API/DB). Mode B only.
    layers: frozenset[str] | None = None
    # Mode C only: which authoring engine ("ui" page-journey | "api" endpoint tests).
    layer: str | None = None


@dataclass(frozen=True)
class RunExecution:
    """What an executed run produced: the DB run id (if any) + a summary."""

    run_id: uuid.UUID | None
    summary: dict[str, Any] = field(default_factory=dict)


class RunExecutor(Protocol):
    """Executes a run request against a session (wraps the Mode B/C orchestrators)."""

    async def execute(
        self,
        *,
        session: AsyncSession,
        project_id: uuid.UUID,
        request: RunRequest,
    ) -> RunExecution: ...


class Ingestor(Protocol):
    """Builds the Brain for a project (wraps the existing ingestion)."""

    async def ingest(
        self, *, session: AsyncSession, project_id: uuid.UUID
    ) -> dict[str, Any]: ...


def to_run_request(body: ModeBRunRequest | ModeCRunRequest) -> RunRequest:
    """Map a validated request body to the executor's domain request."""
    if isinstance(body, ModeBRunRequest):
        return RunRequest(
            mode=RunMode.B,
            strategy=SelectionStrategyKind(body.strategy),
            changeset=tuple(body.changeset or ()),
            max_targets=body.max_targets,
            layers=frozenset(body.layers) if body.layers else None,
        )
    return RunRequest(mode=RunMode.C, prompt=body.prompt, layer=body.layer)


def run_request_to_payload(request: RunRequest) -> dict[str, Any]:
    """Serialize a run request for the durable job payload (B4) — survives restart."""
    return {
        "mode": request.mode.value,
        "strategy": request.strategy.value if request.strategy else None,
        "changeset": list(request.changeset),
        "max_targets": request.max_targets,
        "prompt": request.prompt,
        "layers": sorted(request.layers) if request.layers else None,
        "layer": request.layer,
    }


def run_request_from_payload(payload: dict[str, Any]) -> RunRequest:
    """Rebuild a run request from a durable job payload (the worker's input)."""
    strategy = payload.get("strategy")
    layers = payload.get("layers")
    return RunRequest(
        mode=RunMode(payload["mode"]),
        strategy=SelectionStrategyKind(strategy) if strategy else None,
        changeset=tuple(payload.get("changeset") or ()),
        max_targets=payload.get("max_targets", 50),
        prompt=payload.get("prompt"),
        layers=frozenset(layers) if layers else None,
        layer=payload.get("layer"),
    )
