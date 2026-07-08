"""FastAPI dependencies for the v1 API (Standards §5 — thin wiring).

A per-request DB session (commit on success, rollback on error) and accessors for
the shared ``app.state`` collaborators (job registry + the injectable ports).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.embeddings.types import EmbeddingProvider
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository

# 401 with the standard challenge header — the same body for every auth failure so
# nothing leaks why (no account / bad token / expired all look identical).
_UNAUTHENTICATED = HTTPException(
    status_code=401,
    detail="authentication required",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A request-scoped session from the app sessionmaker (commit/rollback)."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def bearer_token(authorization: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """The authenticated user, or 401 (ADR-0030). Protects data endpoints.

    Hashes the bearer token, loads the live (unexpired) session, then the active
    user. Never logs the token; any failure is an identical 401.
    """
    token = bearer_token(authorization)
    if token is None:
        raise _UNAUTHENTICATED
    record = await SessionRepository(session).get_by_token_hash(hash_token(token))
    if record is None or record.expires_at <= datetime.now(UTC):
        raise _UNAUTHENTICATED
    user = await UserRepository(session).get(record.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_operator_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """The current user, required to be platform staff (ADR-0068; ADR-0035).

    Cross-tenant ops surface (queue / incidents): unauthenticated → 401 (via
    get_current_user); an authenticated non-staff user → 403. Any staff role — down
    to the least-privileged ``read_only_ops`` — satisfies this read gate; finer
    admin-console actions gate on ``require_staff(<permission>)`` (app.api.staff_authz)
    instead. Still honours the deprecated ``is_operator`` flag during the transition.
    """
    if user.staff_role is None and not user.is_operator:
        raise HTTPException(status_code=403, detail="staff access required")
    return user


OperatorUser = Annotated[User, Depends(get_operator_user)]


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    """The configured embedding provider (B9). 503 if absent (a misconfiguration —
    document ingest needs it to embed chunks)."""
    provider: EmbeddingProvider | None = getattr(
        request.app.state, "embedding_provider", None
    )
    if provider is None:
        raise HTTPException(status_code=503, detail="embedding provider not configured")
    return provider
