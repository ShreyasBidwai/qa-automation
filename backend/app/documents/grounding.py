"""Spec-grounded oracles (B9) — honest, deterministic doc grounding.

At generation time, retrieve the document chunks most relevant to the target
endpoint and upgrade a case's ``oracle_source`` to ``SPEC_GROUNDED`` (the blue tier)
ONLY when the case's specific field is actually documented in those chunks — not
merely because the project has documents. Deterministic over the retrieved set (no
AI): semantic retrieval narrows to relevant chunks; a word-boundary field match
confirms the grounding.
"""

from __future__ import annotations

import dataclasses
import re
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.types import EmbeddingProvider
from app.generation.plan import PlannedCase
from app.ingestion.models import EndpointSpec
from app.models.enums import OracleSource
from app.repositories.document_chunk_repository import DocumentChunkRepository


def _endpoint_query(spec: EndpointSpec) -> str:
    fields = ",".join(f.name for f in spec.validation_fields)
    return f"endpoint {spec.method} {spec.uri} fields={fields}".strip()


def _mentions(corpus: str, field: str) -> bool:
    return re.search(rf"\b{re.escape(field.lower())}\b", corpus) is not None


class SpecGroundingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embedding_provider: EmbeddingProvider,
        top_k: int = 5,
    ) -> None:
        self._chunks = DocumentChunkRepository(session)
        self._embedding = embedding_provider
        self._k = top_k

    async def ground(
        self,
        *,
        project_id: uuid.UUID,
        spec: EndpointSpec,
        cases: Sequence[PlannedCase],
    ) -> list[PlannedCase]:
        """Return cases with ``oracle_source`` upgraded to spec-grounded where a
        retrieved doc chunk documents the case's field (else unchanged)."""
        vector = self._embedding.embed([_endpoint_query(spec)])[0]
        chunks = await self._chunks.search_by_vector(project_id, vector, self._k)
        if not chunks:
            return list(cases)  # no docs retrieved → nothing is spec-grounded
        corpus = "\n".join(chunk.text for chunk in chunks).lower()
        return [self._tag(case, corpus) for case in cases]

    @staticmethod
    def _tag(case: PlannedCase, corpus: str) -> PlannedCase:
        # Only a case bound to a SPECIFIC field can be honestly doc-grounded.
        if case.target_field and _mentions(corpus, case.target_field):
            return dataclasses.replace(case, oracle_source=OracleSource.SPEC_GROUNDED)
        return case
