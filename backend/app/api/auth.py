"""Auth routes (B2, ADR-0030): sign up / in / out, password reset, current user.

Thin boundary — it builds an ``AuthService`` (with the composed mailer + config
TTLs) and maps domain errors to stable HTTP codes. Public except ``/auth/me``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidResetTokenError,
)

from .deps import CurrentUser, bearer_token, get_session
from .schemas import (
    AuthTokenResponse,
    PasswordResetConfirmBody,
    PasswordResetRequestBody,
    SignInRequest,
    SignUpRequest,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _service(request: Request, session: AsyncSession) -> AuthService:
    settings = get_settings()
    return AuthService(
        session,
        mailer=request.app.state.mailer,
        session_ttl_seconds=settings.session_ttl_seconds,
        reset_ttl_seconds=settings.password_reset_ttl_seconds,
    )


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, created_at=user.created_at)


def _token_response(user: User, token: str) -> AuthTokenResponse:
    return AuthTokenResponse(access_token=token, user=_user_response(user))


@router.post("/signup", status_code=201, response_model=AuthTokenResponse)
async def sign_up(
    body: SignUpRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthTokenResponse:
    try:
        user, token = await _service(request, session).sign_up(
            body.email, body.password
        )
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=409, detail="email already registered"
        ) from None
    return _token_response(user, token)


@router.post("/signin", response_model=AuthTokenResponse)
async def sign_in(
    body: SignInRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthTokenResponse:
    try:
        user, token = await _service(request, session).sign_in(
            body.email, body.password
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=401, detail="invalid email or password"
        ) from None
    return _token_response(user, token)


@router.post("/signout", status_code=204)
async def sign_out(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Revoke the presented session (idempotent — always 204)."""
    token = bearer_token(authorization)
    if token is not None:
        await _service(request, session).sign_out(token)
    return Response(status_code=204)


@router.post("/password-reset/request", status_code=202)
async def request_password_reset(
    body: PasswordResetRequestBody,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Always 202 (never reveals whether the account exists)."""
    await _service(request, session).request_password_reset(body.email)
    return {"status": "accepted"}


@router.post("/password-reset/confirm", status_code=204)
async def confirm_password_reset(
    body: PasswordResetConfirmBody,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    try:
        await _service(request, session).reset_password(body.token, body.password)
    except InvalidResetTokenError:
        raise HTTPException(
            status_code=400, detail="invalid or expired reset token"
        ) from None
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    """The current user (protected — 401 without a valid session)."""
    return _user_response(current_user)
