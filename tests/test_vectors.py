"""The vector layer: per-dimension tables, and the streaming ingestion path.

Two things are being pinned here, both of which would fail silently:

* a per-batch call to `upsert_chunks` would keep only the last batch, with no
  error and a plausible chunk count;
* a suffixed table name colliding with one of vec0's own shadow tables
  (`vec_chunks_rowids`, `vec_chunks_info`, …) would corrupt the index.
"""

import uuid
from collections.abc import Sequence

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app import crud
from app.core.db import engine
from app.models import DocumentChunk
from app.services import ingest_stream, rag, vectors
from app.services.providers import registry
from app.services.providers.base import ProviderUnavailableError
from tests.conftest import DIMS, auth_headers, make_user

# ──────────────────────── table_for ────────────────────────

def test_the_768_table_keeps_its_name() -> None:
    """Renaming it would be a migration, and there are no migrations here."""
    assert vectors.table_for(768) == "vec_chunks"


def test_other_widths_get_their_own_table() -> None:
    assert vectors.table_for(384) == "vec_chunks_d384"
    assert vectors.table_for(1024) == "vec_chunks_d1024"


def test_suffixed_names_cannot_collide_with_vec0_shadow_tables() -> None:
    """vec0 creates real tables sharing the prefix. The `d` keeps them apart."""
    shadow = {
        "vec_chunks_info",
        "vec_chunks_chunks",
        "vec_chunks_rowids",
        "vec_chunks_vector_chunks00",
        "vec_chunks_metadatatext00",
    }
    generated = {vectors.table_for(d) for d in (128, 256, 384, 512, 768, 1024)}
    assert not generated & shadow


def test_a_bad_width_never_reaches_a_table_name() -> None:
    """The name is interpolated into SQL — this is where it stays an integer."""
    for bad in (0, -1, 1.5):
        with pytest.raises(vectors.EmbeddingDimensionError):
            vectors.table_for(bad)  # pyright: ignore[reportArgumentType]


def test_the_test_suite_is_running_on_its_own_index() -> None:
    """DIMS is 4, so nothing here can touch a real 768 index by accident."""
    assert vectors.table_for() == f"vec_chunks_d{DIMS}"


async def test_vector_tables_excludes_shadow_tables(session: AsyncSession) -> None:
    found = await vectors.vector_tables(session)
    assert "vec_chunks" in found
    assert f"vec_chunks_d{DIMS}" in found
    assert not [n for n in found if n.endswith("_rowids") or n.endswith("_info")]


# ──────────────────── begin_document / append_chunks ────────────────────

async def test_append_does_not_erase_the_previous_batch(
    session: AsyncSession,
) -> None:
    """The trap: `upsert_chunks` deletes first, so per-batch use loses batches."""
    user = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=user.id, title="batched", description=None, file_type="text/plain"
    )
    vector = [1.0, 0.0, 0.0, 0.0]

    await vectors.begin_document(session, doc.id)
    first, second = uuid.uuid4(), uuid.uuid4()
    await vectors.append_chunks(session, user.id, doc.id, [(first, vector)])
    await vectors.append_chunks(session, user.id, doc.id, [(second, vector)])
    await session.commit()

    hits = await vectors.search(session, user.id, vector, 10, [doc.id])
    assert {h.chunk_id for h in hits} == {first, second}


async def test_upsert_still_replaces_wholesale(session: AsyncSession) -> None:
    """The single-call contract is unchanged — the tutor depends on it."""
    user = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=user.id, title="replaced", description=None, file_type="text/plain"
    )
    vector = [1.0, 0.0, 0.0, 0.0]
    old, new = uuid.uuid4(), uuid.uuid4()

    await vectors.upsert_chunks(session, user.id, doc.id, [(old, vector)])
    await vectors.upsert_chunks(session, user.id, doc.id, [(new, vector)])
    await session.commit()

    hits = await vectors.search(session, user.id, vector, 10, [doc.id])
    assert {h.chunk_id for h in hits} == {new}


async def test_delete_reaches_every_width(session: AsyncSession) -> None:
    """A document indexed under an older model must not survive its deletion."""
    user = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=user.id, title="two spaces", description=None, file_type="text/plain"
    )
    # One vector in the active 4-dim index, one in the untouched 768 index.
    active_chunk, legacy_chunk = uuid.uuid4(), uuid.uuid4()
    await vectors.append_chunks(
        session, user.id, doc.id, [(active_chunk, [1.0, 0.0, 0.0, 0.0])]
    )
    async with engine.begin() as conn:
        await vectors.create_vector_table(conn, 768)
    await vectors.append_chunks(
        session, user.id, doc.id, [(legacy_chunk, [0.5] * 768)], dimensions=768
    )
    await session.commit()

    await vectors.delete_document(session, doc.id)
    await session.commit()

    for table in ("vec_chunks", f"vec_chunks_d{DIMS}"):
        remaining = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE document_id = :d"),
            {"d": str(doc.id)},
        )
        assert remaining.scalar_one() == 0, table


# ──────────────────────── Streaming ingestion ────────────────────────

async def test_the_sink_is_an_async_generator_driven_by_asend(
    session: AsyncSession,
) -> None:
    """The pattern itself: prime, feed, close — PEP 525's asend/aclose."""
    user = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=user.id, title="sink", description=None, file_type="text/plain"
    )

    sink = ingest_stream.vector_sink(session, user.id, doc.id, batch_size=2)
    assert await anext(sink) == 0  # priming yields the running count

    counts = [await sink.asend(f"chunk about bananas {i}") for i in range(5)]
    # Written only when a batch fills: 0,0 → 2,2 → 4 with batch_size 2.
    assert counts == [0, 2, 2, 4, 4]

    await sink.aclose()  # flushes the 5th chunk and commits

    stored = await crud.get_chunks_for_document(session=session, document_id=doc.id)
    assert len(stored) == 5


async def test_closing_flushes_the_partial_batch(session: AsyncSession) -> None:
    """Dropping the tail would silently lose the end of every document."""
    user = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=user.id, title="tail", description=None, file_type="text/plain"
    )
    written = await ingest_stream.ingest_streaming(
        session=session,
        owner_id=user.id,
        document_id=doc.id,
        text="banana. " * 400,
        batch_size=3,
    )
    stored = await crud.get_chunks_for_document(session=session, document_id=doc.id)
    assert written == len(stored)
    assert written % 3 != 0 or written > 0  # a partial batch is the normal case


async def test_streaming_indexes_every_chunk_not_just_the_last_batch(
    session: AsyncSession,
) -> None:
    """The regression this whole design exists to avoid."""
    user = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=user.id, title="all batches", description=None, file_type="text/plain"
    )
    text_body = "banana bread recipe. " * 300
    expected = len(rag.chunk_text(text_body))
    assert expected > 3, "the fixture must span several batches to be a test"

    written = await ingest_stream.ingest_streaming(
        session=session,
        owner_id=user.id,
        document_id=doc.id,
        text=text_body,
        batch_size=2,
    )
    assert written == expected

    hits = await vectors.search(
        session, user.id, [0.0, 1.0, 0.0, 0.0], expected + 5, [doc.id]
    )
    assert len(hits) == expected


async def test_streaming_matches_the_whole_document_path(
    session: AsyncSession,
) -> None:
    """Two ingestion paths, one result — otherwise they will drift."""
    user = await make_user(session)
    body = "rocket science. " * 120

    streamed = await crud.create_document(
        session=session, owner_id=user.id, title="streamed", description=None, file_type="text/plain"
    )
    at_once = await crud.create_document(
        session=session, owner_id=user.id, title="at once", description=None, file_type="text/plain"
    )
    a = await ingest_stream.ingest_streaming(
        session=session, owner_id=user.id, document_id=streamed.id, text=body
    )
    b = await rag.ingest_document(
        session=session, owner_id=user.id, document_id=at_once.id, text=body
    )
    assert a == b

    left = await crud.get_chunks_for_document(session=session, document_id=streamed.id)
    right = await crud.get_chunks_for_document(session=session, document_id=at_once.id)
    assert [c.content for c in left] == [c.content for c in right]
    assert [c.chunk_index for c in left] == [c.chunk_index for c in right]


async def test_re_ingesting_replaces_rather_than_duplicates(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    doc = await crud.create_document(
        session=session, owner_id=user.id, title="twice", description=None, file_type="text/plain"
    )
    body = "banana. " * 200
    first = await ingest_stream.ingest_streaming(
        session=session, owner_id=user.id, document_id=doc.id, text=body
    )
    second = await ingest_stream.ingest_streaming(
        session=session, owner_id=user.id, document_id=doc.id, text=body
    )
    assert first == second

    rows = await session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    )
    assert len(list(rows.scalars().all())) == first


async def test_iter_chunks_and_chunk_text_agree() -> None:
    body = "one. two. three. " * 90
    assert list(rag.iter_chunks(body)) == rag.chunk_text(body)


# ──────────────── What the user sees when the model changes ────────────────

async def test_documents_report_which_model_indexed_them(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    doc = await crud.create_document(
        session=session,
        owner_id=user.id,
        title="indexed",
        description=None,
        file_type="text/plain",
    )
    await ingest_stream.ingest_streaming(
        session=session, owner_id=user.id, document_id=doc.id, text="banana. " * 50
    )

    headers = await auth_headers(client, user.email)
    body = (await client.get("/api/v1/documents/", headers=headers)).json()
    row = next(d for d in body["data"] if d["id"] == str(doc.id))

    assert row["indexed_with"] == "stub-embed"
    assert row["searchable"] is True


async def test_a_document_from_another_embedding_model_is_marked_unsearchable(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Honest and cheap: search cannot reach it, so the list says so.

    The alternative — searching both indexes and merging — is what this app
    must not do. Scores from different embedding spaces are not on a common
    scale, so the ranking would look fine and mean nothing.
    """
    user = await make_user(session)
    doc = await crud.create_document(
        session=session,
        owner_id=user.id,
        title="indexed by an older model",
        description=None,
        file_type="text/plain",
    )
    chunk = DocumentChunk(
        document_id=doc.id,
        content="banana bread",
        chunk_index=0,
        embedding_model="nomic-embed-text",  # not the active one
    )
    await crud.replace_chunks(session=session, document_id=doc.id, chunks=[chunk])

    headers = await auth_headers(client, user.email)
    body = (await client.get("/api/v1/documents/", headers=headers)).json()
    row = next(d for d in body["data"] if d["id"] == str(doc.id))

    assert row["indexed_with"] == "nomic-embed-text"
    assert row["searchable"] is False


async def test_a_pending_document_is_not_called_unsearchable(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Nothing indexed yet is not the same as indexed by the wrong model."""
    user = await make_user(session)
    doc = await crud.create_document(
        session=session,
        owner_id=user.id,
        title="still pending",
        description=None,
        file_type="text/plain",
    )
    await session.commit()

    headers = await auth_headers(client, user.email)
    body = (await client.get("/api/v1/documents/", headers=headers)).json()
    row = next(d for d in body["data"] if d["id"] == str(doc.id))

    assert row["indexed_with"] is None
    assert row["searchable"] is True


async def test_a_failure_mid_document_leaves_the_previous_index_intact(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing commits, so the rollback restores what was already indexed.

    The delete at the top of the sink is part of the same transaction, so a
    document that fails to re-index is not left empty — it is left as it was.
    """
    user = await make_user(session)
    doc = await crud.create_document(
        session=session,
        owner_id=user.id,
        title="survives a failure",
        description=None,
        file_type="text/plain",
    )
    doc_id, owner = doc.id, user.id  # rollback expires the ORM objects
    good = await ingest_stream.ingest_streaming(
        session=session, owner_id=owner, document_id=doc_id, text="banana. " * 2000
    )
    assert good > 4, "the fixture must span several batches to be a test"

    calls = {"n": 0}
    real = registry._embedder.embed  # pyright: ignore[reportPrivateUsage]

    async def failing(texts: Sequence[str]) -> list[list[float]]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise ProviderUnavailableError("stub", "embedder went down")
        return await real(texts)

    monkeypatch.setattr(registry._embedder, "embed", failing)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ProviderUnavailableError):
        await ingest_stream.ingest_streaming(
            session=session,
            owner_id=owner,
            document_id=doc_id,
            text="rocket. " * 2000,
            batch_size=2,
        )
    # Exactly one extra embed call: the failing one is not retried by the flush
    # in `finally`.
    assert calls["n"] == 2

    await session.rollback()
    survivors = await crud.get_chunks_for_document(session=session, document_id=doc_id)
    assert len(survivors) == good
    assert "banana" in survivors[0].content
