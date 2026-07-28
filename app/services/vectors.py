"""The only module that touches the `vec_chunks` sqlite-vec virtual table.

Tenant scoping is the whole point of this module's shape. `owner_id` is a
metadata column on the index and a **required positional argument** to
`search()`, so there is no call shape that can omit it.

The inherited `crud.similarity_search` filtered only when `document_ids` was
supplied, which meant the default query path searched every user's chunks and
returned their text verbatim. Making the filter part of the index — rather than
an optional WHERE clause a caller must remember — is what closes that hole.
"""

import struct
import uuid
from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.config import settings

VECTOR_TABLE = "vec_chunks"


class VectorHit(NamedTuple):
    chunk_id: uuid.UUID
    distance: float


class EmbeddingDimensionError(ValueError):
    """Raised when a vector's width does not match the index."""


def pack(vector: Sequence[float]) -> bytes:
    """Serialise a float vector into sqlite-vec's compact wire format."""
    expected = settings.EMBEDDING_DIMENSIONS
    if len(vector) != expected:
        raise EmbeddingDimensionError(
            f"expected {expected}-dim vector for model "
            f"{settings.EMBEDDING_MODEL!r}, got {len(vector)}"
        )
    return struct.pack(f"{len(vector)}f", *vector)


async def create_vector_table(conn: AsyncConnection) -> None:
    """Create the vec0 virtual table. Idempotent.

    The dimension is fixed at creation time. Changing EMBEDDING_DIMENSIONS
    afterwards does NOT alter an existing table — every vector must be
    re-embedded. See docs/jelena/future3.md.
    """
    await conn.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {VECTOR_TABLE} USING vec0("
            "  chunk_id TEXT PRIMARY KEY,"
            "  owner_id TEXT,"
            "  document_id TEXT,"
            f"  embedding float[{settings.EMBEDDING_DIMENSIONS}]"
            ")"
        )
    )


async def upsert_chunks(
    session: AsyncSession,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    rows: Sequence[tuple[uuid.UUID, Sequence[float]]],
) -> None:
    """Replace all vectors for one document.

    vec0 enforces the primary key, so a re-ingestion of the same document would
    fail on duplicate chunk_id. Delete-then-insert keeps re-processing idempotent.
    """
    await delete_document(session, document_id)
    if not rows:
        return
    await session.execute(
        text(
            f"INSERT INTO {VECTOR_TABLE} (chunk_id, owner_id, document_id, embedding) "
            "VALUES (:chunk_id, :owner_id, :document_id, :embedding)"
        ),
        [
            {
                "chunk_id": str(chunk_id),
                "owner_id": str(owner_id),
                "document_id": str(document_id),
                "embedding": pack(vector),
            }
            for chunk_id, vector in rows
        ],
    )


async def search(
    session: AsyncSession,
    owner_id: uuid.UUID,
    query_vector: Sequence[float],
    top_k: int,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> list[VectorHit]:
    """K-nearest-neighbour search, always scoped to one owner.

    `owner_id` is positional and required — do not add an overload that makes it
    optional, or the cross-tenant leak this module exists to prevent comes back.
    """
    params: dict[str, object] = {
        "query": pack(query_vector),
        "k": top_k,
        "owner_id": str(owner_id),
    }
    sql = (
        f"SELECT chunk_id, distance FROM {VECTOR_TABLE} "
        "WHERE embedding MATCH :query AND k = :k AND owner_id = :owner_id"
    )
    if document_ids:
        # Named placeholders, expanded — never interpolate the values themselves.
        names = [f"doc_{i}" for i in range(len(document_ids))]
        for name, doc_id in zip(names, document_ids, strict=True):
            params[name] = str(doc_id)
        sql += " AND document_id IN (" + ", ".join(f":{n}" for n in names) + ")"

    result = await session.execute(text(sql), params)
    rows: Sequence[Row[tuple[str, float]]] = result.all()
    return [VectorHit(uuid.UUID(r[0]), float(r[1])) for r in rows]


async def delete_document(session: AsyncSession, document_id: uuid.UUID) -> None:
    """Remove every vector belonging to a document.

    SQLite foreign keys do not cascade into a virtual table, so deleting a
    Document row does not clean this up — callers must.
    """
    await session.execute(
        text(f"DELETE FROM {VECTOR_TABLE} WHERE document_id = :document_id"),
        {"document_id": str(document_id)},
    )


async def count_for_owner(session: AsyncSession, owner_id: uuid.UUID) -> int:
    result = await session.execute(
        text(f"SELECT count(*) FROM {VECTOR_TABLE} WHERE owner_id = :owner_id"),
        {"owner_id": str(owner_id)},
    )
    return int(result.scalar_one())
