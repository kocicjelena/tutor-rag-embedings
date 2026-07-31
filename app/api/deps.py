"""Shared route dependencies."""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.db import get_session
from app.models import TokenPayload, User

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        if token_data.sub is None:
            raise CREDENTIALS_ERROR
        # The subject is a UUID string. The inherited code passed it straight to
        # session.get(), where the PK is uuid.UUID — under SQLite that never matches.
        user_id = uuid.UUID(token_data.sub)
    except (InvalidTokenError, ValidationError, ValueError):
        raise CREDENTIALS_ERROR from None

    user = await session.get(User, user_id)
    # A valid token for a deleted user is an authentication failure, not a 404.
    # Returning 404 here distinguished "no such user" from "bad token", which is
    # enumerable.
    if user is None:
        raise CREDENTIALS_ERROR
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ─────────────────── The caller's own Anthropic key ───────────────────
#
# Carried per request in a header, never in the database. The Next.js layer
# holds it in an httpOnly cookie the browser cannot read and attaches it when
# proxying, so it exists here only for the life of one request.
#
# A header rather than a JWT claim on purpose: JWTs are signed, not encrypted,
# so anything inside one is readable by whoever holds the token — and tokens
# end up in logs, browser storage and bug reports. A credential must not.
ANTHROPIC_KEY_HEADER = "X-Anthropic-Key"


async def get_caller_anthropic_key(
    raw: Annotated[str | None, Header(alias=ANTHROPIC_KEY_HEADER)] = None,
) -> str | None:
    """The caller's own Anthropic key for this request, if they sent one.

    Not validated here. A wrong key surfaces as a 503 from the provider with a
    message aimed at the user, which is both cheaper and more accurate than
    pre-checking it on every request.
    """
    if not settings.USER_ANTHROPIC_KEYS:
        return None
    cleaned = (raw or "").strip()
    return cleaned or None


CallerAnthropicKey = Annotated[str | None, Depends(get_caller_anthropic_key)]


async def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


SuperUser = Annotated[User, Depends(get_current_active_superuser)]
