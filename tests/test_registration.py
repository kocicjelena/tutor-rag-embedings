"""Public self-registration.

`POST /users/signup` is the only unauthenticated write in this API, which makes
it the one route where a schema mistake is reachable by anybody. Most of what
follows asserts on *shape* rather than behaviour, because the failure would be
silent: an account created with `is_superuser` set looks exactly like an
ordinary one until it reads somebody else's data.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models import User, UserRegister
from tests.conftest import make_user


def test_userregister_does_not_inherit_userbase() -> None:
    """Hard rule #4, on the create side.

    `UserBase` carries `is_superuser` and `is_active`. If `UserRegister` ever
    inherits it — directly or through `UserCreate` — a stranger can promote
    themselves in the signup body. `UserUpdateMe` exists for this reason on the
    update side; this is the same defect's other half.
    """
    from app.models import UserBase

    assert not issubclass(UserRegister, UserBase)

    forbidden = {"is_superuser", "is_active", "id", "hashed_password"}
    assert not forbidden & set(UserRegister.model_fields), (
        "UserRegister exposes a privilege field: "
        f"{sorted(forbidden & set(UserRegister.model_fields))}"
    )


async def test_signup_creates_an_ordinary_user(
    session: AsyncSession, client: AsyncClient
) -> None:
    response = await client.post(
        "/api/v1/users/signup",
        json={"email": "newcomer@example.com", "password": "password12345"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["email"] == "newcomer@example.com"
    assert body["is_superuser"] is False
    assert body["is_active"] is True
    # The derived handle is what the whole identity idea rests on.
    assert body["public_id"]
    assert "@" not in body["public_id"]
    assert "password" not in response.text.lower()


async def test_signup_cannot_make_a_superuser(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The attack, spelled out: extra fields in the body must not stick."""
    response = await client.post(
        "/api/v1/users/signup",
        json={
            "email": "sneaky@example.com",
            "password": "password12345",
            "is_superuser": True,
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["is_superuser"] is False

    # And in the database, not only in the response.
    result = await session.execute(
        select(User).where(User.email == "sneaky@example.com")
    )
    user = result.scalars().one()
    assert user.is_superuser is False


async def test_signup_then_sign_in(session: AsyncSession, client: AsyncClient) -> None:
    """Registration is worth nothing if the account cannot then log in."""
    await client.post(
        "/api/v1/users/signup",
        json={"email": "roundtrip@example.com", "password": "password12345"},
    )
    login = await client.post(
        "/api/v1/login/access-token",
        data={"username": "roundtrip@example.com", "password": "password12345"},
    )
    assert login.status_code == 200, login.text

    token = login.json()["access_token"]
    me = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "roundtrip@example.com"


async def test_duplicate_email_is_refused(
    session: AsyncSession, client: AsyncClient
) -> None:
    await make_user(session, "taken@example.com")
    response = await client.post(
        "/api/v1/users/signup",
        json={"email": "taken@example.com", "password": "password12345"},
    )
    assert response.status_code == 400


async def test_email_is_normalised(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Case and whitespace must not create two identities from one address.

    The public handle is derived from the email, so `A@b.com` and `a@b.com`
    would otherwise be two different people with two different corpora.
    """
    await client.post(
        "/api/v1/users/signup",
        json={"email": "Mixed.Case@Example.com", "password": "password12345"},
    )
    result = await session.execute(
        select(User).where(User.email == "mixed.case@example.com")
    )
    assert result.scalars().one()

    clash = await client.post(
        "/api/v1/users/signup",
        json={"email": "MIXED.CASE@EXAMPLE.COM", "password": "password12345"},
    )
    assert clash.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "password12345"},
        {"email": "short@example.com", "password": "tiny"},
        {"password": "password12345"},
        {"email": "nopass@example.com"},
    ],
)
async def test_bad_input_is_refused(
    client: AsyncClient, payload: dict[str, str]
) -> None:
    response = await client.post("/api/v1/users/signup", json=payload)
    assert response.status_code == 422, response.text


async def test_registration_can_be_closed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For a public URL that does not have rate limiting yet."""
    monkeypatch.setattr(settings, "OPEN_REGISTRATION", False)
    response = await client.post(
        "/api/v1/users/signup",
        json={"email": "too-late@example.com", "password": "password12345"},
    )
    assert response.status_code == 403


async def test_signup_needs_no_token(client: AsyncClient) -> None:
    """Deliberately unauthenticated — and the only write that is.

    Pinned so that adding a global auth dependency later cannot quietly make
    the app impossible to join.
    """
    response = await client.post(
        "/api/v1/users/signup",
        json={"email": "anonymous@example.com", "password": "password12345"},
    )
    assert response.status_code == 201
