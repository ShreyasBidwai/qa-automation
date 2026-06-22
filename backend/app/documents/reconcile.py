"""Spec-vs-code reconciliation (B9, ADR-0039) — honest, confidence-gated.

A static pass on document ingest: does the doc reference a CONCRETE endpoint the
code Brain lacks? Only explicit ``METHOD /path`` references are considered (a strict
regex), so fuzzy prose never produces a divergence. We record both sides ("spec says
X, code shows Y") and do NOT adjudicate which is wrong. Deterministic, no AI.

Guard: if the Brain has no endpoints at all (code not ingested), we reconcile
against nothing and flag nothing — we can't honestly say "code lacks X".
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NodeKind
from app.models.project_document import ProjectDocument
from app.models.spec_divergence import SpecDivergence
from app.repositories.node_repository import NodeRepository
from app.repositories.spec_divergence_repository import SpecDivergenceRepository

# A CONCRETE HTTP route reference: an explicit verb + path. Confidence gate — prose
# without this shape is never matched (the false-positive guard).
_ROUTE_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./{}-]*)",
)
_DIVERGENCE_KIND = "endpoint_missing"


def _normalize_uri(uri: str) -> str:
    return uri.strip().strip("/")


def _excerpt(content: str, span: tuple[int, int], *, width: int = 120) -> str:
    start = max(0, span[0] - width // 4)
    end = min(len(content), span[1] + width)
    return content[start:end].strip().replace("\n", " ")


def extract_route_references(content: str) -> list[tuple[str, str, str]]:
    """Concrete (method, normalized_path, excerpt) refs, de-duped by (method,path)."""
    seen: set[tuple[str, str]] = set()
    refs: list[tuple[str, str, str]] = []
    for match in _ROUTE_RE.finditer(content):
        method = match.group(1).upper()
        # Drop trailing sentence punctuation the path class may have swallowed
        # (e.g. "POST /users." → "/users").
        path = _normalize_uri(match.group(2).rstrip(".,;:!?)"))
        if not path or (method, path) in seen:
            continue
        seen.add((method, path))
        refs.append((method, path, _excerpt(content, match.span())))
    return refs


async def reconcile_document(
    session: AsyncSession, *, project_id: uuid.UUID, document: ProjectDocument
) -> list[SpecDivergence]:
    """Flag concrete endpoints the doc references but the code Brain lacks."""
    refs = extract_route_references(document.content)
    if not refs:
        return []

    endpoints = await NodeRepository(session).list_by_kind(
        project_id, NodeKind.ENDPOINT
    )
    if not endpoints:
        return []  # no code model to reconcile against → flag nothing (honest)

    known = {
        (
            str(node.attributes.get("method", "")).upper(),
            _normalize_uri(str(node.attributes.get("uri", ""))),
        )
        for node in endpoints
    }

    divergences = [
        SpecDivergence(
            project_id=project_id,
            document_id=document.id,
            kind=_DIVERGENCE_KIND,
            spec_reference=f"{method} /{path}",
            code_observation="no matching endpoint in the code model (the Brain)",
            excerpt=excerpt,
            confidence="high",
            status="open",
        )
        for method, path, excerpt in refs
        if (method, path) not in known
    ]
    if divergences:
        await SpecDivergenceRepository(session).add_many(divergences)
    return divergences
