"""Shared route dependencies."""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
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


async def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


SuperUser = Annotated[User, Depends(get_current_active_superuser)]
