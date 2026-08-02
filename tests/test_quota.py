"""The free tier.

Two properties carry the most weight and are asserted hardest: **off by
default**, because a limit that switched itself on locally would gate Jelena's
own laptop and the test suite; and **seeded lessons do not count**, because a
new account starting at 6 of 10 used would be indefensible.
"""

import io

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import quota, seed, tutor_model
from tests.conftest import auth_headers, make_user


def _upload(client: AsyncClient, headers: dict[str, str], name: str):
    return client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": (name, io.BytesIO(b"Some text worth embedding."), "text/plain")},
    )


async def test_off_by_default(session: AsyncSession) -> None:
    """The default must never gate local development or this suite."""
    assert settings.QUOTA_ENABLED is False

    user = await make_user(session, "quota-default@example.com")
    allowance = await quota.usage_for(session, user)
    assert allowance.enforced is False
    assert allowance.can_upload and allowance.can_learn


async def test_seeded_lessons_do_not_count(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new account must not open at 6 of 10 used because the app seeded it."""
    user = await make_user(session, "quota-seeded@example.com")
    monkeypatch.setattr(settings, "DEMO_USER", user.email)
    monkeypatch.setattr(settings, "SEED_ON_STARTUP", True)
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)

    installed = await seed.seed_if_empty(session)
    assert installed > 0, "nothing was seeded, so this asserts nothing"

    allowance = await quota.usage_for(session, user)
    assert allowance.lessons_used == 0
    assert allowance.can_learn


async def test_uploads_are_counted_and_then_refused(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UPLOADS", 2)

    user = await make_user(session, "quota-uploads@example.com")
    headers = await auth_headers(client, user.email)

    assert (await _upload(client, headers, "one.txt")).status_code == 201
    assert (await _upload(client, headers, "two.txt")).status_code == 201

    refused = await _upload(client, headers, "three.txt")
    assert refused.status_code == 402, refused.text


async def test_the_refusal_explains_itself(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The message is the feature. A bare 402 would read as a broken app."""
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UPLOADS", 1)
    monkeypatch.setattr(settings, "SUPPORT_EMAIL", "help@example.com")

    user = await make_user(session, "quota-message@example.com")
    headers = await auth_headers(client, user.email)
    await _upload(client, headers, "one.txt")

    detail = (await _upload(client, headers, "two.txt")).json()["detail"]

    assert "1 of 1" in detail                       # what happened
    assert "costs real money" in detail             # why
    assert "downloading your model" in detail       # what still works
    assert "without these limits" in detail         # what to do about it
    # No promise of a product that does not exist. Jelena, 2026-08-02:
    # payments are not built and are not going to be, so the message must
    # not imply otherwise.
    for promise in ("planned", "coming soon", "subscription", "upgrade", "buy"):
        assert promise not in detail.lower(), promise
    assert "help@example.com" in detail             # who to ask
    assert "deleting one" in detail                 # how to recover


async def test_no_support_email_means_no_dangling_sentence(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UPLOADS", 1)
    monkeypatch.setattr(settings, "SUPPORT_EMAIL", "")

    user = await make_user(session, "quota-noemail@example.com")
    headers = await auth_headers(client, user.email)
    await _upload(client, headers, "one.txt")
    detail = (await _upload(client, headers, "two.txt")).json()["detail"]

    assert "write to" not in detail
    assert "@" not in detail


async def test_deleting_a_document_frees_a_slot(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented consequence of counting rows instead of keeping a tally.

    The refusal message promises this, so it is pinned rather than assumed.
    """
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UPLOADS", 1)

    user = await make_user(session, "quota-delete@example.com")
    headers = await auth_headers(client, user.email)

    first = await _upload(client, headers, "one.txt")
    doc_id = first.json()["id"]
    assert (await _upload(client, headers, "two.txt")).status_code == 402

    await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
    assert (await _upload(client, headers, "two.txt")).status_code == 201


async def test_lessons_are_refused_at_both_doors(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/teach refuses early so no answer streams in that cannot be kept, and
    /interactions refuses regardless of how the caller got there."""
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_LESSONS", 1)

    user = await make_user(session, "quota-lessons@example.com")
    headers = await auth_headers(client, user.email)

    first = await client.post(
        "/api/v1/tutor/interactions",
        headers=headers,
        json={"term": "Embeddings", "question": "What?", "answer": "A vector."},
    )
    assert first.status_code == 201

    again = await client.post(
        "/api/v1/tutor/interactions",
        headers=headers,
        json={"term": "RAG", "question": "What?", "answer": "Retrieval."},
    )
    assert again.status_code == 402

    teach = await client.post(
        "/api/v1/tutor/teach",
        headers=headers,
        json={"term": "RAG", "question": "Explain", "mode": "casual"},
    )
    assert teach.status_code == 402


async def test_a_superuser_is_never_locked_out(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The account that administers the instance cannot be stopped by its own
    free tier — on this deployment that account is Jelena's."""
    from app import crud
    from app.models import UserCreate

    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UPLOADS", 0)

    admin = await crud.create_user(
        session=session,
        user_create=UserCreate(
            email="quota-admin@example.com",
            password="password12345",
            is_superuser=True,
        ),
    )
    headers = await auth_headers(client, admin.email)
    assert (await _upload(client, headers, "one.txt")).status_code == 201


async def test_the_quota_route_reports_what_is_left(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So the UI can show the limit before it bites."""
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UPLOADS", 3)
    monkeypatch.setattr(settings, "SUPPORT_EMAIL", "help@example.com")

    user = await make_user(session, "quota-route@example.com")
    headers = await auth_headers(client, user.email)
    await _upload(client, headers, "one.txt")

    body = (await client.get("/api/v1/quota/", headers=headers)).json()
    assert body["enforced"] is True
    assert body["uploads_used"] == 1
    assert body["uploads_left"] == 2
    assert body["can_upload"] is True
    assert body["support_email"] == "help@example.com"


async def test_quota_is_per_person(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One learner's uploads must not spend another's allowance."""
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UPLOADS", 1)

    alice = await make_user(session, "quota-alice@example.com")
    bob = await make_user(session, "quota-bob@example.com")
    alice_headers = await auth_headers(client, alice.email)
    bob_headers = await auth_headers(client, bob.email)

    assert (await _upload(client, alice_headers, "a.txt")).status_code == 201
    assert (await _upload(client, alice_headers, "a2.txt")).status_code == 402
    assert (await _upload(client, bob_headers, "b.txt")).status_code == 201


async def test_imported_lessons_count(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing a model file is storage like any other, so it counts —
    unlike seeding, which nobody asked for. Stated because the difference is
    not obvious and someone will wonder."""
    monkeypatch.setattr(settings, "QUOTA_ENABLED", True)

    user = await make_user(session, "quota-import@example.com")
    await tutor_model.record_lesson(
        session=session,
        owner_id=user.id,
        term="Mine",
        question="Q?",
        answer="A.",
        provider="claude",
    )
    allowance = await quota.usage_for(session, user)
    assert allowance.lessons_used == 1
