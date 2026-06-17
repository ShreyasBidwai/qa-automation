"""Ingest a target straight from a git remote (Architecture §4, §9).

Chains the read-only GitProvider into the T2.2 LaravelIngester:
checkout → ingest(path, source_sha=resolved) → cleanup. The temp clone is
removed on success AND failure (no leaks, Standards §11). Re-pulling the same
SHA updates the Brain in place via the idempotent upserts.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.git.types import GitProvider
from app.ingestion.laravel.ingester import IngestResult, LaravelIngester


async def ingest_from_git(
    *,
    session: AsyncSession,
    project_id: uuid.UUID,
    repo_url: str,
    ref: str,
    provider: GitProvider,
    ingester: LaravelIngester,
) -> IngestResult:
    handle = provider.checkout(repo_url, ref)
    try:
        return await ingester.ingest(
            session=session,
            project_id=project_id,
            repo_path=handle.path,
            source_sha=handle.sha,
        )
    finally:
        provider.cleanup(handle)
