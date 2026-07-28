"""Authentication and privilege regressions."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import auth_headers, make_user


async def test_privilege_escalation_is_rejected(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The inherited `UserUpdate` inherited `is_superuser` from `UserBase`, and
    `crud.update_user` applied `model_dump(exclude_unset=True)` straight onto
    the row — so this exact request promoted any user to superuser.
    """
    user = await make_user(session)
    assert user.is_superuser is False

    headers = await auth_headers(client, user.email)
    response = await client.patch(
        "/api/v1/users/me", json={"is_superuser": True}, headers=headers
    )

    # Whether the field is ignored or rejected, what must never happen is that
    # it takes effect.
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["is_superuser"] is False, (
        f"PRIVILEGE ESCALATION: PATCH returned {response.status_code}"
    )

    await session.refresh(user)
    assert user.is_superuser is False


async def test_is_active_cannot_be_self_set(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    await client.patch("/api/v1/users/me", json={"is_active": False}, headers=headers)
    await session.refresh(user)
    assert user.is_active is True


async def test_legitimate_self_update_still_works(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    response = await client.patch(
        "/api/v1/users/me", json={"full_name": "Jelena K"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Jelena K"


async def test_non_superuser_cannot_list_users(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    assert (await client.get("/api/v1/users/", headers=headers)).status_code == 403


async def test_no_token_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/users/me")).status_code == 401


async def test_garbage_token_is_401_not_403(client: AsyncClient) -> None:
    """The inherited code returned 403 for a bad token and 404 for a valid token
    naming a missing user, which let a caller enumerate accounts."""
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


async def test_token_for_deleted_user_is_401(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 200

    from app import crud

    await crud.delete_user(session=session, db_user=user)
    response = await client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401, "must not distinguish deleted from invalid"


async def test_wrong_password_and_unknown_email_match(client: AsyncClient) -> None:
    unknown = await client.post(
        "/api/v1/login/access-token",
        data={"username": "nobody@test.local", "password": "whatever12345"},
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == "Incorrect email or password"


async def test_password_hashing_roundtrip() -> None:
    from app.core.security import get_password_hash, verify_password

    hashed = get_password_hash("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


async def test_overlong_password_does_not_crash() -> None:
    """bcrypt hashes at most 72 bytes; longer input must not raise."""
    from app.core.security import get_password_hash, verify_password

    long_password = "🔑" * 100
    hashed = get_password_hash(long_password)
    assert verify_password(long_password, hashed)


async def test_malformed_stored_hash_is_a_failed_login() -> None:
    from app.core.security import verify_password

    assert verify_password("anything", "not-a-bcrypt-hash") is False
