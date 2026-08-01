"""The channel: learning arrives in pieces, is embedded as it arrives, and lands in SQLite.

Jelena's design, 2026-07-31, and the distinction that makes it make sense:

> **Embedding is how learning becomes the material of a model.** Making text
> findable is a different purpose, it already works, and nothing here touches
> it. `vec_chunks` still holds documents and finished lessons; the live
> pipeline only *reads* it, to ask how new each piece is.

## The gap this closes

Until now the browser held an entire answer and posted it back when it was
finished. The front end was a buffer and the round trip sat in the middle of
the one process that matters. Now the browser sends pieces as they appear, each
one is embedded on arrival, and what comes back is the state of the model —
which the context mirrors. Nothing waits for the end.

## Why a coroutine, and not just a function

The test Jelena set is the right one: if the unit were one finished lesson,
a plain call would do the same work and this would be decoration. It is not.
The input is continuous and open-ended — pieces keep coming while a person is
being taught — and the consumer has to control the rate at which it takes them,
because embedding is the slow step. A generator alone cannot `await`; a callback
cannot push back. `PEP 525` async generators are the construct that does both,
so `learning_sink` is one:

    sink = learning_sink(session, owner_id, session_id)
    await anext(sink)                       # prime
    for piece in pieces:
        count = await sink.asend(piece)     # buffers, embeds when full
    await sink.aclose()                     # flush the tail and commit

**Nothing is buffered waiting for a boundary.** That was my earlier mistake and
Jelena named it: a generator that waits until a chunk boundary is final is a
batch in disguise, at which point the coroutine has nothing to do. Boundaries
have to be canonical only for *index* chunks, because a search must not depend
on how the text arrived. Model material has no canonical boundary to preserve,
so a piece is embedded exactly as the learner received it.

The one thing that *is* batched is the round trip to Ollama, because `embed()`
is natively batched and one call for four pieces costs what one call for one
piece costs. That is a transport economy, not a wait for meaning.

## Retries are free

The channel is many small requests, and any of them can arrive twice — a
retried fetch, a reconnect, a user reloading. `(owner_id, session_id, seq)` is
unique, so a piece already stored is *skipped* rather than duplicated, and the
caller is told which ones were skipped.

## What is persisted — the row *and* the vector

Both. An earlier version kept only the row, using the vector to compute
`novelty` and then dropping it. Jelena overruled that, 2026-07-31:

> *"Keep it. Without that it is not worth having embeddings. Finding similarity
> in the corpus, and making embeddings in a new model built from a base model
> for embedding in the app, is where embedding algorithms shine. Copy-paste but
> using streaming, and having coroutines as syntactic sugar that gives no value
> to the technical flow, is not enough reason to build the app."*

She was right, and the reasoning that dropped it was too narrow: it judged the
vector by whether anything searched it *today*. Kept, it makes piece-to-piece
similarity possible without re-embedding, and it is the raw material for
training an embedding model of the learner's own.

The vector goes to **`vec_learning`**, a separate `vec0` index at the active
width — never to `vec_chunks`. The search index is still not written to by this
pipeline, and a test asserts it: a half-finished sentence must not become
something a citation can point at.
"""

import logging
import uuid
from collections.abc import AsyncGenerator, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.models import (
    LearningEvent,
    LearningEventPublic,
    LearningModelState,
    LearningNeighbour,
    LearningNeighboursPublic,
    LearningPiece,
)
from app.services import vectors
from app.services.providers import get_embedding_provider
from app.services.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# How many pieces are embedded per round trip.
#
# Small on purpose, and much smaller than ingestion's 64: this is a live
# pipeline, and a piece that waits for 63 companions is a piece the learner is
# no longer looking at. Four keeps the round trips economical without making
# the model lag behind the lesson.
BATCH_SIZE = 4


async def learning_sink(
    session: AsyncSession,
    owner_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    term: str | None = None,
    batch_size: int = BATCH_SIZE,
) -> AsyncGenerator[int, LearningPiece]:
    """Consume pieces of learning, embed and persist them, yield the running count.

    Prime with `await anext(sink)`, feed with `await sink.asend(piece)`, finish
    with `await sink.aclose()`, which flushes the tail and commits.

    Rows are written but **not committed** until close, so a failure mid-stream
    leaves the model exactly as it was rather than half-updated. The events
    themselves are readable through `read_state` afterwards.
    """
    embedder = get_embedding_provider()
    seen = await _existing_seqs(session, owner_id, session_id)

    pending: list[LearningPiece] = []
    written = 0
    closed = False

    try:
        while True:
            try:
                piece = yield written
            except GeneratorExit:
                # aclose(). Fall out and let `finally` flush what is pending —
                # dropping it would silently lose the tail of the lesson.
                closed = True
                break

            if not piece.text.strip() or piece.seq in seen:
                continue
            seen.add(piece.seq)
            pending.append(piece)

            if len(pending) >= batch_size:
                written += await _flush(session, owner_id, session_id, term, pending, embedder)
                pending.clear()
    finally:
        # Only on a clean close. Unwinding from an error means the embedder just
        # failed; flushing would retry the call that failed and committing would
        # publish half a lesson. Doing neither leaves the transaction to roll
        # back — the same reasoning as `ingest_stream.vector_sink`.
        if closed:
            if pending:
                written += await _flush(session, owner_id, session_id, term, pending, embedder)
            await session.commit()
            logger.info(
                "learning session %s: %d piece(s) embedded for owner %s",
                session_id,
                written,
                owner_id,
            )


async def _flush(
    session: AsyncSession,
    owner_id: uuid.UUID,
    session_id: uuid.UUID,
    term: str | None,
    pending: Sequence[LearningPiece],
    embedder: EmbeddingProvider,
) -> int:
    """Embed a batch, place each piece against what is already known, store row and vector."""
    vectorised = await embedder.embed([p.text for p in pending])

    rows: list[tuple[uuid.UUID, Sequence[float]]] = []
    for piece, vector in zip(pending, vectorised, strict=True):
        event = LearningEvent(
            owner_id=owner_id,
            session_id=session_id,
            seq=piece.seq,
            text=piece.text,
            term=term,
            novelty=await _novelty(session, owner_id, vector),
            embedded_with=embedder.model,
        )
        session.add(event)
        rows.append((event.id, vector))

    await session.flush()
    # The vector goes to `vec_learning`, never to `vec_chunks`. Kept on Jelena's
    # instruction and against my earlier judgement, which was too narrow — I
    # measured the vector by whether anything searched it today. Kept, it makes
    # piece-to-piece similarity possible without re-embedding, and it is the raw
    # material for an embedding model of the learner's own, which is the point
    # where this app does something an API call cannot.
    await vectors.append_learning(session, owner_id, session_id, rows)
    return len(pending)


async def _novelty(
    session: AsyncSession, owner_id: uuid.UUID, vector: Sequence[float]
) -> float | None:
    """How far this piece is from the nearest thing the learner already has.

    Read-only against the search index, and owner-scoped by `vectors.search`'s
    required positional argument — the same tenant boundary as everywhere else.

    `None` when the corpus is empty, which is honest: with nothing to compare
    against, "how new is this" has no answer. Reporting 1.0 would look like a
    measurement and be a default.
    """
    hits = await vectors.search(session, owner_id, vector, top_k=1)
    return float(hits[0].distance) if hits else None


async def _existing_seqs(
    session: AsyncSession, owner_id: uuid.UUID, session_id: uuid.UUID
) -> set[int]:
    """Which sequence numbers this session already stored, so a retry is a no-op."""
    result = await session.execute(
        select(col(LearningEvent.seq))
        .where(LearningEvent.owner_id == owner_id)
        .where(LearningEvent.session_id == session_id)
    )
    return set(result.scalars().all())


async def read_state(
    session: AsyncSession, owner_id: uuid.UUID, session_id: uuid.UUID
) -> LearningModelState:
    """The model as SQLite holds it — the shape the browser's context mirrors.

    Read back rather than accumulated in memory, because the database is the
    thing that is true. A client that missed a response recovers from the next
    one instead of replaying anything.
    """
    embedder = get_embedding_provider()
    result = await session.execute(
        select(
            func.count(),
            func.avg(col(LearningEvent.novelty)),
            func.max(col(LearningEvent.seq)),
        )
        .select_from(LearningEvent)
        .where(LearningEvent.owner_id == owner_id)
        .where(LearningEvent.session_id == session_id)
    )
    count, mean_novelty, last_seq = result.one()

    terms = await session.execute(
        select(col(LearningEvent.term))
        .where(LearningEvent.owner_id == owner_id)
        .where(LearningEvent.session_id == session_id)
        .where(col(LearningEvent.term).is_not(None))
        .distinct()
    )

    return LearningModelState(
        session_id=session_id,
        events=int(count or 0),
        terms=[t for t in terms.scalars().all() if t],
        mean_novelty=float(mean_novelty) if mean_novelty is not None else None,
        last_seq=int(last_seq) if last_seq is not None else None,
        embedded_with=embedder.model,
        # Across every session, not just this one: the model is the whole of
        # what this learner has accumulated, and a per-session count would fall
        # back to zero each time they started a new lesson.
        vectors=await vectors.count_learning_for_owner(session, owner_id),
    )


async def similar(
    session: AsyncSession,
    owner_id: uuid.UUID,
    text: str,
    *,
    top_k: int = 5,
    session_id: uuid.UUID | None = None,
) -> LearningNeighboursPublic:
    """What in this learner's own model resembles a passage.

    This is what keeping the vector bought, and the reason Jelena overruled
    dropping it: piece-to-piece similarity **without re-embedding the corpus**.
    The comparison runs against `vec_learning`, so it answers "have I been told
    this before, and where" over the material as it was actually taught — not
    over the canonical chunks a search would return.

    One embedding call for the query, one KNN, one read. It never touches
    `vec_chunks`; the two indexes are not on a common scale and merging them
    would rank plausibly and mean nothing (hard rule #5).
    """
    if not text.strip():
        return LearningNeighboursPublic(query=text, matches=[], searched=0)

    embedder = get_embedding_provider()
    searched = await vectors.count_learning_for_owner(session, owner_id)
    if not searched:
        # Nothing to compare against. An empty list with the count beside it
        # says "your model is empty", which reads differently from "nothing
        # matched" and is the honest answer.
        return LearningNeighboursPublic(query=text, matches=[], searched=0)

    vectorised = await embedder.embed([text])
    hits = await vectors.search_learning(
        session, owner_id, vectorised[0], top_k, session_id=session_id
    )
    if not hits:
        return LearningNeighboursPublic(query=text, matches=[], searched=searched)

    distances = {hit.event_id: hit.distance for hit in hits}
    result = await session.execute(
        select(LearningEvent).where(col(LearningEvent.id).in_(list(distances)))
    )
    # Re-sorted by distance: the `IN` clause returns rows in whatever order the
    # database likes, and the ranking is the whole answer.
    rows = sorted(result.scalars().all(), key=lambda r: distances[r.id])

    return LearningNeighboursPublic(
        query=text,
        searched=searched,
        matches=[
            LearningNeighbour(
                seq=row.seq,
                text=row.text,
                term=row.term,
                session_id=row.session_id,
                distance=distances[row.id],
            )
            for row in rows
        ],
    )


async def read_events(
    session: AsyncSession,
    owner_id: uuid.UUID,
    session_id: uuid.UUID,
    seqs: Sequence[int],
) -> list[LearningEventPublic]:
    """The rows for these sequence numbers, in order."""
    if not seqs:
        return []
    result = await session.execute(
        select(LearningEvent)
        .where(LearningEvent.owner_id == owner_id)
        .where(LearningEvent.session_id == session_id)
        .where(col(LearningEvent.seq).in_(seqs))
        .order_by(col(LearningEvent.seq))
    )
    return [
        LearningEventPublic(
            seq=row.seq,
            text=row.text,
            term=row.term,
            novelty=row.novelty,
            created_at=row.created_at,
        )
        for row in result.scalars().all()
    ]
