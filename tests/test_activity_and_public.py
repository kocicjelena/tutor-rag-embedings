"""Knowing who used the app, and what the sign-in page is allowed to publish.

The heaviest assertion here is a negative one: **the demo password must not
leave the server unless two separate settings both say so.** A default that
published a working password would be silent, public, and look entirely
correct — the worst combination available.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import activity
from tests.conftest import auth_headers, make_user


# ─────────────────────────── the sign-in page ───────────────────────────


async def test_demo_password_is_not_published_by_default(
    client: AsyncClient,
) -> None:
    """The default must publish nothing. This is the one that matters."""
    assert settings.PUBLISH_DEMO_CREDENTIALS is False

    body = (await client.get("/api/v1/public/signin-info")).json()
    assert body["demo_email"] is None
    assert body["demo_password"] is None


async def test_publishing_needs_both_settings(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A demo account with publishing off, and publishing on with no account,
    must each publish nothing. Only both together open the door."""
    monkeypatch.setattr(settings, "DEMO_USER", "demo@example.com")
    monkeypatch.setattr(settings, "DEMO_USER_PASSWORD", "demopassword123")
    monkeypatch.setattr(settings, "PUBLISH_DEMO_CREDENTIALS", False)
    body = (await client.get("/api/v1/public/signin-info")).json()
    assert body["demo_password"] is None

    monkeypatch.setattr(settings, "DEMO_USER", "")
    monkeypatch.setattr(settings, "PUBLISH_DEMO_CREDENTIALS", True)
    body = (await client.get("/api/v1/public/signin-info")).json()
    assert body["demo_password"] is None

    monkeypatch.setattr(settings, "DEMO_USER", "demo@example.com")
    body = (await client.get("/api/v1/public/signin-info")).json()
    assert body["demo_email"] == "demo@example.com"
    assert body["demo_password"] == "demopassword123"


async def test_signin_info_needs_no_token(client: AsyncClient) -> None:
    """It has to work before anyone can authenticate — that is its whole job."""
    assert (await client.get("/api/v1/public/signin-info")).status_code == 200


async def test_signin_info_reports_the_limits(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So the page can say what a new account gets, before signing up."""
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UPLOADS", 3)
    monkeypatch.setattr(settings, "FREE_LESSONS", 10)
    monkeypatch.setattr(settings, "OPEN_REGISTRATION", True)

    body = (await client.get("/api/v1/public/signin-info")).json()
    assert body["quota_enabled"] is True
    assert body["free_uploads"] == 3
    assert body["free_lessons"] == 10
    assert body["registration_open"] is True


# ─────────────────────────── the activity report ───────────────────────────


async def test_signing_in_is_recorded(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The one signal that had to be stored rather than counted."""
    user = await make_user(session, "seen@example.com")
    await auth_headers(client, user.email)
    await auth_headers(client, user.email)

    report = await activity.build_report(session, days=7)
    mine = next(p for p in report.users if p.email == user.email)
    assert mine.sign_ins == 2
    assert mine.first_sign_in is not None
    assert mine.last_sign_in is not None
    assert report.sign_ins >= 2


async def test_report_counts_what_costs_money(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Uploads and lessons per person — the numbers that show up on a bill."""
    import io

    user = await make_user(session, "busy@example.com")
    headers = await auth_headers(client, user.email)

    await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("a.txt", io.BytesIO(b"some text"), "text/plain")},
    )
    await client.post(
        "/api/v1/tutor/interactions",
        headers=headers,
        json={"term": "T", "question": "Q?", "answer": "A."},
    )

    report = await activity.build_report(session, days=7)
    mine = next(p for p in report.users if p.email == user.email)
    assert mine.uploads == 1
    assert mine.lessons == 1
    assert report.total_uploads >= 1
    assert report.total_lessons >= 1


async def test_the_busiest_account_is_first(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The row that matters on a bill should not need looking for."""
    import io

    quiet = await make_user(session, "quiet@example.com")
    loud = await make_user(session, "loud@example.com")
    await auth_headers(client, quiet.email)
    headers = await auth_headers(client, loud.email)
    for name in ("a.txt", "b.txt", "c.txt"):
        await client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": (name, io.BytesIO(b"text"), "text/plain")},
        )

    report = await activity.build_report(session, days=7)
    assert report.users[0].email == loud.email


async def test_activity_is_superuser_only(
    session: AsyncSession, client: AsyncClient
) -> None:
    """It names every account. That must never be one mistake from public."""
    user = await make_user(session, "nosy@example.com")
    headers = await auth_headers(client, user.email)

    assert (await client.get("/api/v1/admin/activity", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/admin/activity")).status_code in (401, 403)


async def test_a_superuser_can_read_it(
    session: AsyncSession, client: AsyncClient
) -> None:
    from app import crud
    from app.models import UserCreate

    admin = await crud.create_user(
        session=session,
        user_create=UserCreate(
            email="admin-activity@example.com",
            password="password12345",
            is_superuser=True,
        ),
    )
    headers = await auth_headers(client, admin.email)
    response = await client.get("/api/v1/admin/activity?days=30", headers=headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["window_days"] == 30
    assert body["total_users"] >= 1
    assert any(u["email"] == admin.email for u in body["users"])


async def test_a_failed_sign_in_records_nothing(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Otherwise the report would count password guesses as visits."""
    user = await make_user(session, "wrongpass@example.com")
    await client.post(
        "/api/v1/login/access-token",
        data={"username": user.email, "password": "not-the-password"},
    )
    report = await activity.build_report(session, days=7)
    mine = next(p for p in report.users if p.email == user.email)
    assert mine.sign_ins == 0
