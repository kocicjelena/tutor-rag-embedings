"""User management.

Note the two distinct update schemas. `PATCH /users/me` accepts `UserUpdateMe`,
which has no privilege fields at all — the inherited version accepted the full
`UserUpdate`, so any user could POST `{"is_superuser": true}` to it and promote
themselves. Only the superuser route accepts `UserUpdate`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.models import (
    Message,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/signup", response_model=UserPublic, status_code=201)
async def register(*, session: SessionDep, user_in: UserRegister) -> UserPublic:
    """Create an account. **The only unauthenticated write in the API.**

    This is the first piece of the thing the app is actually for: a person
    registers with an email, and their public handle is *derived* from it
    (`app/core/identity.py`) rather than assigned — so the same address always
    resolves to the same identity, and the app is the issuer.

    Three things about it are load-bearing.

    **The body is `UserRegister`, never `UserCreate`.** `UserCreate` inherits
    `UserBase`, which carries `is_superuser`, so accepting it here would let
    anyone become an administrator by adding one field to a JSON body. That is
    hard rule #4 exactly, on the create side instead of the update side.

    **A taken email is a 400 and says so.** This does leak whether an address
    has an account — but every signup form on the internet does, because the
    alternative is refusing to tell someone why their registration failed.
    Login is the route that must stay quiet, and it does.

    **It can be switched off.** `OPEN_REGISTRATION=false` returns 403, for a
    deployment that is public but has no rate limiting yet. Signup with no
    ceiling is a spam vector: every account can upload and embed, and embedding
    costs CPU on whoever's machine this runs.
    """
    if not settings.OPEN_REGISTRATION:
        raise HTTPException(
            403,
            "Registration is closed on this instance. Ask an administrator "
            "for an account.",
        )

    email = user_in.email.strip().lower()
    if await crud.get_user_by_email(session=session, email=email) is not None:
        raise HTTPException(400, "That email is already registered. Try signing in.")

    # Built here rather than passed through, so the privilege fields take their
    # defaults from this line and cannot arrive from the request at all.
    user = await crud.create_user(
        session=session,
        user_create=UserCreate(
            email=email,
            password=user_in.password,
            full_name=user_in.full_name,
            is_superuser=False,
            is_active=True,
        ),
    )
    return UserPublic.model_validate(user, from_attributes=True)


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
async def read_users(
    session: SessionDep, skip: int = 0, limit: int = 100
) -> UsersPublic:
    users, count = await crud.get_users(
        session=session, skip=skip, limit=min(limit, 200)
    )
    return UsersPublic(
        data=[UserPublic.model_validate(u, from_attributes=True) for u in users],
        count=count,
    )


@router.post(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
    status_code=201,
)
async def create_user(*, session: SessionDep, user_in: UserCreate) -> UserPublic:
    existing = await crud.get_user_by_email(session=session, email=user_in.email)
    if existing is not None:
        raise HTTPException(400, "Email already registered")
    user = await crud.create_user(session=session, user_create=user_in)
    return UserPublic.model_validate(user, from_attributes=True)


@router.get("/me", response_model=UserPublic)
async def read_user_me(current_user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(current_user, from_attributes=True)


@router.patch("/me", response_model=UserPublic)
async def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> UserPublic:
    """Update your own profile.

    `UserUpdateMe` intentionally has no `is_superuser` / `is_active` fields, so
    sending them is rejected as an unknown field rather than silently applied.
    """
    if user_in.email:
        existing = await crud.get_user_by_email(session=session, email=user_in.email)
        if existing is not None and existing.id != current_user.id:
            raise HTTPException(409, "Email already taken")
    user = await crud.update_user(
        session=session, db_user=current_user, user_in=user_in
    )
    return UserPublic.model_validate(user, from_attributes=True)


@router.get("/{user_id}", response_model=UserPublic)
async def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> UserPublic:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if not current_user.is_superuser and user.id != current_user.id:
        raise HTTPException(403, "Not enough permissions")
    return UserPublic.model_validate(user, from_attributes=True)


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
async def update_user(
    *, user_id: uuid.UUID, session: SessionDep, user_in: UserUpdate
) -> UserPublic:
    """Superuser-only: may change privileges."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user_in.email:
        existing = await crud.get_user_by_email(session=session, email=user_in.email)
        if existing is not None and existing.id != user.id:
            raise HTTPException(409, "Email already taken")
    updated = await crud.update_user(session=session, db_user=user, user_in=user_in)
    return UserPublic.model_validate(updated, from_attributes=True)


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_user(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Message:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == current_user.id:
        raise HTTPException(400, "Superusers cannot delete themselves")
    await crud.delete_user(session=session, db_user=user)
    return Message(message="User deleted successfully")
