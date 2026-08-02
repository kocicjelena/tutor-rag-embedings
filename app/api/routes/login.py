"""Token issuing."""

import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.core import security
from app.core.config import settings
from app.models import Token, UserPublic
from app.services import activity

logger = logging.getLogger(__name__)

router = APIRouter(tags=["login"])


@router.post("/login/access-token")
async def login_access_token(
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """OAuth2-compatible token login. `username` is the email address."""
    user = await crud.authenticate(
        session=session, email=form_data.username, password=form_data.password
    )
    # Same message for unknown email and wrong password — don't confirm which
    # addresses are registered.
    if user is None:
        raise HTTPException(400, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(400, "Inactive user")

    # One row, so the owner of this instance can answer "did anyone come back".
    # Wrapped because failing to *log* a sign-in must never fail the sign-in:
    # the person is authenticated, and a bookkeeping error is not their problem.
    try:
        await activity.record_sign_in(session, user.id)
    except Exception:
        logger.exception("could not record sign-in for %s", user.id)

    return Token(
        access_token=security.create_access_token(
            user.id,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
    )


@router.get("/login/test-token", response_model=UserPublic)
async def test_token(current_user: CurrentUser) -> UserPublic:
    """Verify a token and echo back the user it belongs to."""
    return UserPublic.model_validate(current_user, from_attributes=True)
