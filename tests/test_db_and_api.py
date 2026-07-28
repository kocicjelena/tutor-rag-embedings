"""Infrastructure and end-to-end API behaviour."""

import io

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import auth_headers, make_user


async def test_sqlite_vec_loaded(session: AsyncSession) -> None:
    """Guards the private-API glue in app/core/db.py.

    Loading the extension requires reaching through aiosqlite's private
    `_conn` / `_execute`. If an upgrade breaks that, vector search would
    silently stop working — this fails loudly instead.
    """
    version = (await session.execute(text("select vec_version()"))).scalar_one()
    assert str(version).startswith("v")


async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["sqlite_vec"].startswith("v")


async def test_vector_table_exists(session: AsyncSession) -> None:
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE name = 'vec_chunks'")
    )
    assert result.scalar_one_or_none() == "vec_chunks"


async def test_bootstrap_superuser_created(session: AsyncSession) -> None:
    """init_db() used to be dead code, so a fresh DB had no way to log in."""
    from app import crud
    from app.core.config import settings

    user = await crud.get_user_by_email(
        session=session, email=settings.FIRST_SUPERUSER
    )
    assert user is not None
    assert user.is_superuser is True


# ──────────────────────────── Upload flow ────────────────────────────

async def test_upload_and_query_roundtrip(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    response = await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("notes.txt", io.BytesIO(b"Bananas are yellow fruit."), "text/plain")},
    )
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc["status"] in {"pending", "processing", "ready"}

    listing = await client.get("/api/v1/documents/", headers=headers)
    assert listing.status_code == 200
    assert any(d["id"] == doc["id"] for d in listing.json()["data"])


async def test_upload_rejects_oversize(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "MAX_UPLOAD_BYTES", 100)
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    response = await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("big.txt", io.BytesIO(b"x" * 5000), "text/plain")},
    )
    assert response.status_code == 413


async def test_upload_rejects_unsupported_type(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    response = await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/x-msdownload")},
    )
    assert response.status_code == 415


async def test_upload_rejects_empty_file(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    response = await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
    )
    assert response.status_code == 422


async def test_cannot_read_another_users_document(
    session: AsyncSession, client: AsyncClient
) -> None:
    from app import crud

    alice = await make_user(session)
    bob = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=alice.id, title="Private",
        description=None, file_type="text/plain",
    )
    headers = await auth_headers(client, bob.email)
    response = await client.get(f"/api/v1/documents/{doc.id}", headers=headers)
    assert response.status_code == 403


async def test_delete_removes_vectors(
    session: AsyncSession, client: AsyncClient
) -> None:
    """SQLite FKs do not cascade into the vec0 virtual table."""
    from app import crud
    from app.models import DocumentChunk
    from app.services import vectors

    user = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=user.id, title="Doc",
        description=None, file_type="text/plain",
    )
    chunk = DocumentChunk(
        document_id=doc.id, content="text", chunk_index=0, embedding_model="stub-embed"
    )
    await crud.replace_chunks(session=session, document_id=doc.id, chunks=[chunk])
    await vectors.upsert_chunks(session, user.id, doc.id, [(chunk.id, [1.0, 0.0, 0.0, 0.0])])
    await session.commit()
    assert await vectors.count_for_owner(session, user.id) == 1

    headers = await auth_headers(client, user.email)
    response = await client.delete(f"/api/v1/documents/{doc.id}", headers=headers)
    assert response.status_code == 200
    assert await vectors.count_for_owner(session, user.id) == 0


# ──────────────────────────── Providers ────────────────────────────

async def test_providers_endpoint(session: AsyncSession, client: AsyncClient) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    response = await client.get("/api/v1/providers/", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["embedding_dimensions"] == 4
    assert {p["name"] for p in body["data"]} == {"ollama"}


async def test_unknown_provider_is_503(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    response = await client.post(
        "/api/v1/query/",
        json={"question": "hi", "provider": "openai"},
        headers=headers,
    )
    # 422 from schema validation is also acceptable; what must not happen is 500.
    assert response.status_code in {422, 503}
    assert response.status_code != 500
