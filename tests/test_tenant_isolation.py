"""The cross-tenant leak regression.

The inherited `crud.similarity_search` filtered by document only when
`document_ids` was supplied, so `POST /query/` with the default `null` searched
every user's chunks and returned their text verbatim.

These tests give two users *identical* embeddings, so nothing but tenant scoping
can separate them.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.models import DocumentChunk
from app.services import vectors
from tests.conftest import auth_headers, make_user

SECRET = "ALICE-CONFIDENTIAL-SALARY-DATA"


async def _seed(session: AsyncSession, owner_id: uuid.UUID, content: str) -> uuid.UUID:
    doc = await crud.create_document(
        session=session,
        owner_id=owner_id,
        title=f"doc-{content[:10]}",
        description=None,
        file_type="text/plain",
    )
    chunk = DocumentChunk(
        document_id=doc.id, content=content, chunk_index=0, embedding_model="stub-embed"
    )
    await crud.replace_chunks(session=session, document_id=doc.id, chunks=[chunk])
    # Same vector for every caller — only owner scoping can distinguish them.
    await vectors.upsert_chunks(session, owner_id, doc.id, [(chunk.id, [1.0, 0.0, 0.0, 0.0])])
    await session.commit()
    return doc.id


async def test_search_is_owner_scoped(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    await _seed(session, alice.id, SECRET)
    await _seed(session, bob.id, "BOB-DATA")

    hits = await vectors.search(session, bob.id, [1.0, 0.0, 0.0, 0.0], top_k=50)
    chunks = await crud.get_chunks_by_ids(
        session=session, chunk_ids=[h.chunk_id for h in hits]
    )
    contents = [c.content for c in chunks.values()]
    assert SECRET not in contents
    assert contents == ["BOB-DATA"]


async def test_query_endpoint_does_not_leak(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The exact call shape that leaked: document_ids omitted."""
    alice = await make_user(session)
    bob = await make_user(session)
    await _seed(session, alice.id, SECRET)
    await _seed(session, bob.id, "BOB-DATA")

    headers = await auth_headers(client, bob.email)
    response = await client.post(
        "/api/v1/query/",
        json={"question": "what is the data", "top_k": 20},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert SECRET not in response.text
    for source in body["sources"]:
        assert source["content"] != SECRET


async def test_document_filter_cannot_reach_another_owner(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Naming someone else's document ID must 403, not silently search it."""
    alice = await make_user(session)
    bob = await make_user(session)
    alice_doc = await _seed(session, alice.id, SECRET)
    await _seed(session, bob.id, "BOB-DATA")

    headers = await auth_headers(client, bob.email)
    response = await client.post(
        "/api/v1/query/",
        json={"question": "anything", "document_ids": [str(alice_doc)]},
        headers=headers,
    )
    assert response.status_code == 403
    assert SECRET not in response.text


async def test_vector_search_requires_owner_positionally() -> None:
    """`search()` must not grow an optional-owner overload.

    Guards the invariant rather than a behaviour: if someone gives `owner_id` a
    default, the leak returns silently.
    """
    import inspect

    sig = inspect.signature(vectors.search)
    owner = sig.parameters["owner_id"]
    assert owner.default is inspect.Parameter.empty, (
        "owner_id must stay required — see .claude/rules/other_agent.md finding #1"
    )


async def test_documents_list_is_owner_scoped(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    await _seed(session, alice.id, SECRET)

    headers = await auth_headers(client, bob.email)
    response = await client.get("/api/v1/documents/", headers=headers)
    assert response.status_code == 200
    titles = [d["title"] for d in response.json()["data"]]
    assert not any(SECRET[:10] in t for t in titles)


@pytest.mark.parametrize("dims", [[1.0, 2.0], [1.0] * 10])
async def test_dimension_mismatch_rejected(dims: list[float]) -> None:
    with pytest.raises(vectors.EmbeddingDimensionError):
        vectors.pack(dims)
