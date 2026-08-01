"""The only module that touches the sqlite-vec virtual tables.

Tenant scoping is the whole point of this module's shape. `owner_id` is a
metadata column on the index and a **required positional argument** to
`search()`, so there is no call shape that can omit it.

The inherited `crud.similarity_search` filtered only when `document_ids` was
supplied, which meant the default query path searched every user's chunks and
returned their text verbatim. Making the filter part of the index — rather than
an optional WHERE clause a caller must remember — is what closes that hole.

## One table per embedding dimension

`vec0` fixes a column's vector width at creation time, so a 384-dimension model
cannot share a `float[768]` index — not "should not", *cannot* (hard rule #5).
Each width therefore gets its own table, and **the original keeps its name**:

    768  →  vec_chunks          (unchanged, never migrated)
    384  →  vec_chunks_d384

With one provider configured every call resolves to `vec_chunks` and behaves
exactly as before, which is what makes this addition safe to ship.

Searching still cannot mix spaces — vectors from two models are not comparable,
and the distances would rank plausibly while meaning nothing. So a query
searches exactly one table: the active provider's. Documents indexed under a
different model are *reported* as unsearchable rather than silently missed; see
`.claude/rules/VECTORS.md` and `app/scripts/reembed.py`.

## Two indexes, and they are not two copies

`vec_chunks` and `vec_learning` hold different things for different reasons, and
conflating them would undo both.

    vec_chunks    the search index. Canonical chunks of finished documents and
                  saved lessons. What retrieval reaches, what a citation points
                  at, what `reembed` maintains.

    vec_learning  the learner's model as it is being built. One vector per piece
                  of learning, at the boundary it actually arrived on, written
                  live by `app/services/learning_stream.py`.

Jelena's decision, 2026-07-31, overruling an earlier plan to keep only the row:

> *"Keep it. Without that it is not worth having embeddings. Finding similarity
> in the corpus, and making embeddings in a new model built from a base model
> for embedding in the app, is where embedding algorithms shine."*

She was right and the earlier reasoning was too narrow — it judged the vector by
whether anything searched it *today*. Kept, it makes piece-to-piece similarity
possible without re-embedding, and it is the raw material for an embedding model
of the learner's own.

**The live pipeline still never writes to the search index.** That property is
tested, and it is what keeps a half-finished sentence out of the thing citations
point at. Boundaries have to be canonical only for index chunks, because a
search must not depend on how the text arrived; model material has no canonical
boundary to preserve.
"""

import re
import struct
import uuid
from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.config import settings

VECTOR_TABLE = "vec_chunks"

# The second index, and it is a *different kind of thing* — see the section at
# the bottom of this module. `vec_chunks` is the search index: what a query
# reaches. `vec_learning` holds the pieces of learning as they arrived, so the
# learner's own model has vectors of its own without a re-embedding pass.
#
# They are never unioned, never merged, and never searched together. The same
# reason as hard rule #5: two sets of distances that are not on a common scale
# produce a ranking that looks fine and means nothing.
LEARNING_TABLE = "vec_learning"

# The width the original table was created with. Kept as a literal rather than
# read from settings: it is a fact about rows already on disk, not a setting.
BASE_DIMENSIONS = 768

# Suffixed tables carry a `d` so they cannot collide with vec0's own shadow
# tables, which share the prefix (`vec_chunks_rowids`, `vec_chunks_info`, ...).
_SUFFIXED = re.compile(rf"^{VECTOR_TABLE}_d(\d+)$")
_LEARNING_SUFFIXED = re.compile(rf"^{LEARNING_TABLE}_d(\d+)$")


class VectorHit(NamedTuple):
    chunk_id: uuid.UUID
    distance: float


class LearningHit(NamedTuple):
    """A neighbouring piece of learning, and how far away it is."""

    event_id: uuid.UUID
    session_id: uuid.UUID
    distance: float


class EmbeddingDimensionError(ValueError):
    """Raised when a vector's width does not match the index."""


def active_dimensions() -> int:
    """The width the configured embedding model produces."""
    return settings.EMBEDDING_DIMENSIONS


def table_for(dimensions: int | None = None) -> str:
    """The index holding vectors of this width.

    The 768 table keeps the name `vec_chunks`. Renaming it would be a
    migration, and there are no migrations here.
    """
    width = _checked(dimensions)
    return VECTOR_TABLE if width == BASE_DIMENSIONS else f"{VECTOR_TABLE}_d{width}"


def _checked(dimensions: int | None) -> int:
    """Validate a width before it reaches a table name.

    The name is interpolated into SQL, so this is the boundary that keeps it an
    integer. It never comes from a request today — but a config value that
    reaches string formatting deserves the check anyway.
    """
    width = active_dimensions() if dimensions is None else dimensions
    if width != int(width) or width <= 0:
        raise EmbeddingDimensionError(
            f"embedding dimensions must be a positive integer, got {width!r}"
        )
    return int(width)


def pack(vector: Sequence[float], dimensions: int | None = None) -> bytes:
    """Serialise a float vector into sqlite-vec's compact wire format."""
    expected = _checked(dimensions)
    if len(vector) != expected:
        raise EmbeddingDimensionError(
            f"expected {expected}-dim vector for model "
            f"{settings.EMBEDDING_MODEL!r}, got {len(vector)}"
        )
    return struct.pack(f"{len(vector)}f", *vector)


async def create_vector_table(
    conn: AsyncConnection, dimensions: int | None = None
) -> str:
    """Create the vec0 virtual table for one width. Idempotent.

    The dimension is fixed at creation time. Changing EMBEDDING_DIMENSIONS
    afterwards does NOT alter an existing table — it selects a *different*
    table, and anything indexed under the old width stays where it is until
    `app/scripts/reembed.py` moves it.
    """
    width = _checked(dimensions)
    table = table_for(width)
    await conn.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
            "  chunk_id TEXT PRIMARY KEY,"
            "  owner_id TEXT,"
            "  document_id TEXT,"
            f"  embedding float[{width}]"
            ")"
        )
    )
    return table


async def vector_tables(session: AsyncSession) -> list[str]:
    """Every vec0 index that exists, active or not.

    Both filters matter. vec0 creates ordinary shadow tables sharing the
    prefix — `vec_chunks_rowids`, `vec_chunks_info`, `vec_chunks_vector_chunks00`
    — so matching on the name alone would return tables that are not indexes
    and cannot be queried as one. `USING vec0` in the stored DDL is what
    separates them.

    Used by the operations that must reach *all* widths: deleting a document,
    and counting what a user owns.
    """
    result = await session.execute(
        text(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND sql LIKE '%USING vec0%' AND (name = :base OR name LIKE :pattern)"
        ),
        {"base": VECTOR_TABLE, "pattern": f"{VECTOR_TABLE}_d%"},
    )
    names = [str(row[0]) for row in result.all()]
    return [n for n in names if n == VECTOR_TABLE or _SUFFIXED.match(n)]


# ──────────────────────────── Writing ────────────────────────────

async def begin_document(session: AsyncSession, document_id: uuid.UUID) -> None:
    """Clear a document's vectors so it can be indexed from scratch.

    Split out of `upsert_chunks` for the streaming path, which appends batch by
    batch and must delete exactly **once**. Calling `upsert_chunks` per batch
    would erase the previous batch every time and leave only the last one
    indexed, with no error and a plausible-looking chunk count.
    """
    await delete_document(session, document_id)


async def append_chunks(
    session: AsyncSession,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    rows: Sequence[tuple[uuid.UUID, Sequence[float]]],
    *,
    dimensions: int | None = None,
) -> None:
    """Insert vectors. Does **not** clear first — see `begin_document`."""
    if not rows:
        return
    width = _checked(dimensions)
    table = table_for(width)
    await session.execute(
        text(
            f"INSERT INTO {table} (chunk_id, owner_id, document_id, embedding) "
            "VALUES (:chunk_id, :owner_id, :document_id, :embedding)"
        ),
        [
            {
                "chunk_id": str(chunk_id),
                "owner_id": str(owner_id),
                "document_id": str(document_id),
                "embedding": pack(vector, width),
            }
            for chunk_id, vector in rows
        ],
    )


async def upsert_chunks(
    session: AsyncSession,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    rows: Sequence[tuple[uuid.UUID, Sequence[float]]],
    *,
    dimensions: int | None = None,
) -> None:
    """Replace all vectors for one document, in one call.

    vec0 enforces the primary key, so a re-ingestion of the same document would
    fail on duplicate chunk_id. Delete-then-insert keeps re-processing
    idempotent. Correct **only** when called once per document.
    """
    await begin_document(session, document_id)
    await append_chunks(
        session, owner_id, document_id, rows, dimensions=dimensions
    )


# ──────────────────────────── Reading ────────────────────────────

async def search(
    session: AsyncSession,
    owner_id: uuid.UUID,
    query_vector: Sequence[float],
    top_k: int,
    document_ids: Sequence[uuid.UUID] | None = None,
    *,
    dimensions: int | None = None,
) -> list[VectorHit]:
    """K-nearest-neighbour search, always scoped to one owner.

    `owner_id` is positional and required — do not add an overload that makes it
    optional, or the cross-tenant leak this module exists to prevent comes back.

    One table, never a union across widths: distances from different embedding
    models are not on a common scale, so merging them produces a ranking that
    looks fine and means nothing.
    """
    width = _checked(dimensions)
    table = table_for(width)
    params: dict[str, object] = {
        "query": pack(query_vector, width),
        "k": top_k,
        "owner_id": str(owner_id),
    }
    sql = (
        f"SELECT chunk_id, distance FROM {table} "
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
    """Remove every vector belonging to a document, at every width.

    SQLite foreign keys do not cascade into a virtual table, so deleting a
    Document row does not clean this up — callers must.

    All widths, not just the active one: a document indexed under a previous
    embedding model still has rows in that model's table, and leaving them
    behind would resurrect it the moment the provider was switched back.
    """
    for table in await vector_tables(session):
        await session.execute(
            text(f"DELETE FROM {table} WHERE document_id = :document_id"),
            {"document_id": str(document_id)},
        )


# ──────────────────── The learning index ────────────────────
#
# Everything below is `vec_learning`. It mirrors the shape above deliberately —
# per-width tables, owner scoped inside the index, `d` in the suffix — because
# the reasoning is identical and a reader who understands one understands both.
# What it does *not* share is a query: nothing here reads `vec_chunks` and
# nothing above reads this.


def learning_table_for(dimensions: int | None = None) -> str:
    """The learning index holding vectors of this width."""
    width = _checked(dimensions)
    return LEARNING_TABLE if width == BASE_DIMENSIONS else f"{LEARNING_TABLE}_d{width}"


async def create_learning_table(
    conn: AsyncConnection, dimensions: int | None = None
) -> str:
    """Create the vec0 index for learning events at one width. Idempotent.

    `session_id` is a metadata column beside `owner_id` so a search can be
    narrowed to one stretch of learning without a join — "what in this lesson is
    like this piece" is the question the live pipeline asks, and it is asked
    while the lesson is still being written.
    """
    width = _checked(dimensions)
    table = learning_table_for(width)
    await conn.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
            "  event_id TEXT PRIMARY KEY,"
            "  owner_id TEXT,"
            "  session_id TEXT,"
            f"  embedding float[{width}]"
            ")"
        )
    )
    return table


async def learning_tables(session: AsyncSession) -> list[str]:
    """Every learning vec0 index that exists, active or not.

    Same two filters as `vector_tables`, and for the same reason: vec0's shadow
    tables share the prefix, so the name alone would return tables that are not
    indexes.
    """
    result = await session.execute(
        text(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND sql LIKE '%USING vec0%' AND (name = :base OR name LIKE :pattern)"
        ),
        {"base": LEARNING_TABLE, "pattern": f"{LEARNING_TABLE}_d%"},
    )
    names = [str(row[0]) for row in result.all()]
    return [n for n in names if n == LEARNING_TABLE or _LEARNING_SUFFIXED.match(n)]


async def append_learning(
    session: AsyncSession,
    owner_id: uuid.UUID,
    session_id: uuid.UUID,
    rows: Sequence[tuple[uuid.UUID, Sequence[float]]],
    *,
    dimensions: int | None = None,
) -> None:
    """Insert vectors for learning events.

    Append only, and there is deliberately no `begin_*` counterpart. A document
    is re-ingested whole, so its vectors are cleared first; a stretch of learning
    only ever grows, and a piece that was already stored is skipped upstream by
    the `(owner_id, session_id, seq)` constraint rather than overwritten here.
    """
    if not rows:
        return
    width = _checked(dimensions)
    table = learning_table_for(width)
    await session.execute(
        text(
            f"INSERT OR IGNORE INTO {table} "
            "(event_id, owner_id, session_id, embedding) "
            "VALUES (:event_id, :owner_id, :session_id, :embedding)"
        ),
        [
            {
                "event_id": str(event_id),
                "owner_id": str(owner_id),
                "session_id": str(session_id),
                "embedding": pack(vector, width),
            }
            for event_id, vector in rows
        ],
    )


async def search_learning(
    session: AsyncSession,
    owner_id: uuid.UUID,
    query_vector: Sequence[float],
    top_k: int,
    *,
    session_id: uuid.UUID | None = None,
    dimensions: int | None = None,
) -> list[LearningHit]:
    """Nearest pieces of learning, always scoped to one owner.

    `owner_id` is positional and required, exactly as in `search`. The rule is
    not about which table it is — it is that no call shape may omit the tenant.

    One table, never a union across widths, and never a union with `vec_chunks`.
    """
    width = _checked(dimensions)
    table = learning_table_for(width)
    if table not in await learning_tables(session):
        return []

    params: dict[str, object] = {
        "query": pack(query_vector, width),
        "k": top_k,
        "owner_id": str(owner_id),
    }
    sql = (
        f"SELECT event_id, session_id, distance FROM {table} "
        "WHERE embedding MATCH :query AND k = :k AND owner_id = :owner_id"
    )
    if session_id is not None:
        params["session_id"] = str(session_id)
        sql += " AND session_id = :session_id"

    result = await session.execute(text(sql), params)
    rows: Sequence[Row[tuple[str, str, float]]] = result.all()
    return [
        LearningHit(uuid.UUID(r[0]), uuid.UUID(r[1]), float(r[2])) for r in rows
    ]


async def delete_learning_for_owner(
    session: AsyncSession, owner_id: uuid.UUID
) -> None:
    """Remove every learning vector belonging to one owner, at every width.

    SQLite foreign keys do not cascade into a virtual table, so deleting a User
    row leaves these behind — and unlike a stale document vector, which is
    merely unreachable, these are one person's study material. Called when a
    user is deleted.
    """
    for table in await learning_tables(session):
        await session.execute(
            text(f"DELETE FROM {table} WHERE owner_id = :owner_id"),
            {"owner_id": str(owner_id)},
        )


async def count_learning_for_owner(
    session: AsyncSession, owner_id: uuid.UUID, *, dimensions: int | None = None
) -> int:
    """How many learning vectors this owner has in the **active** index."""
    table = learning_table_for(_checked(dimensions))
    if table not in await learning_tables(session):
        return 0
    result = await session.execute(
        text(f"SELECT count(*) FROM {table} WHERE owner_id = :owner_id"),
        {"owner_id": str(owner_id)},
    )
    return int(result.scalar_one())


async def delete_for_owner(session: AsyncSession, owner_id: uuid.UUID) -> None:
    """Remove every chunk vector belonging to one owner, at every width.

    The counterpart to `delete_document`, for the case where the documents go
    away without anyone deleting them one by one: a User row is deleted, SQLite
    cascades to Document and DocumentChunk, and **nothing cascades into a vec0
    virtual table**. Without this the vectors outlive the rows they describe —
    orphaned, unreachable, and counted by nothing that would notice.
    """
    for table in await vector_tables(session):
        await session.execute(
            text(f"DELETE FROM {table} WHERE owner_id = :owner_id"),
            {"owner_id": str(owner_id)},
        )


async def count_for_owner(
    session: AsyncSession, owner_id: uuid.UUID, *, dimensions: int | None = None
) -> int:
    """How many vectors this owner has in the **active** index.

    Scoped to one width on purpose: this feeds `GET /tutor/stats`, which
    reports what the learner's model can currently answer from. Counting
    unsearchable vectors there would overstate it.
    """
    table = table_for(_checked(dimensions))
    if table not in await vector_tables(session):
        return 0
    result = await session.execute(
        text(f"SELECT count(*) FROM {table} WHERE owner_id = :owner_id"),
        {"owner_id": str(owner_id)},
    )
    return int(result.scalar_one())
