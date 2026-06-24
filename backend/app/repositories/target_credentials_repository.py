"""Repository for ``target_credentials`` (ADR-0053).

One row per project; the write path UPSERTS it. Never decrypts — it stores and
returns the row as-is (the secret column is opaque ciphertext). Decryption happens
only in the run-time accessor (``app.credentials.resolver``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.target_credentials import TargetCredentials


class TargetCredentialsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: uuid.UUID) -> TargetCredentials | None:
        stmt = select(TargetCredentials).where(
            TargetCredentials.project_id == project_id
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def upsert(
        self,
        project_id: uuid.UUID,
        *,
        mode: str,
        identifier: str | None,
        encrypted_secret: bytes | None,
    ) -> TargetCredentials:
        """Set (or replace) a project's credentials. ``encrypted_secret`` is already
        ciphertext — this repository never sees plaintext."""
        record = await self.get(project_id)
        if record is None:
            record = TargetCredentials(project_id=project_id)
            self.session.add(record)
        record.mode = mode
        record.identifier = identifier
        record.encrypted_secret = encrypted_secret
        await self.session.flush()
        return record

    async def delete(self, project_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            sql_delete(TargetCredentials).where(
                TargetCredentials.project_id == project_id
            )
        )
        return bool(result.rowcount)
