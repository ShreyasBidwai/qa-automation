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
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository

from .ports import Ingestor, RunExecutor

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
    """The current user, required to be an instance operator (B4, ADR-0035).

    Cross-tenant ops surface: unauthenticated → 401 (via get_current_user); an
    authenticated non-operator → 403 (it's an authorization failure, not a hidden
    per-tenant resource).
    """
    if not user.is_operator:
        raise HTTPException(status_code=403, detail="operator access required")
    return user


OperatorUser = Annotated[User, Depends(get_operator_user)]


def get_run_executor(request: Request) -> RunExecutor:
    executor: RunExecutor | None = getattr(request.app.state, "run_executor", None)
    if executor is None:
        raise HTTPException(status_code=503, detail="run executor not configured")
    return executor


def get_ingestor(request: Request) -> Ingestor:
    ingestor: Ingestor | None = getattr(request.app.state, "ingestor", None)
    if ingestor is None:
        raise HTTPException(status_code=503, detail="ingestor not configured")
    return ingestor
