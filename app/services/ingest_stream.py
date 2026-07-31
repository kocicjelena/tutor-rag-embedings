"""Streaming ingestion — an async generator that consumes chunks and writes them.

The second ingestion path, for uploaded files. `rag.ingest_document` is
untouched and still serves the tutor, where a lesson is one short text indexed
synchronously and streaming would buy nothing.

## Why a coroutine at all

`rag.ingest_document` holds the whole document in memory three times over:
every chunk, every vector, every row, all resident before the first write. At
`MAX_UPLOAD_BYTES` (10 MiB) with the default chunk size that is roughly 13 000
chunks and ~40 MB of float32 vectors alone. It works; it is the shape that
stops working first.

Here, peak memory is one batch. The producer yields chunks lazily
(`rag.iter_chunks`), the consumer embeds and writes them in batches of
`BATCH_SIZE`, and neither ever holds the document.

## The pattern, and one correction to it

Jelena's description was `send()` / `close()` — PEP 342, the synchronous
generator idiom. It cannot work here for a structural reason rather than a
stylistic one: a sync generator body cannot `await`, and this consumer has to
await both the embedding call and the database write.

**PEP 525 async generators** are the same shape that can: `asend()` and
`aclose()` in place of `send()` and `close()`, primed the same way, flushed at
the end the same way. That is what `vector_sink` is.

    sink = vector_sink(session, owner_id, document_id)
    await anext(sink)               # prime — `asend(None)`, spelled to type-check
    for chunk in rag.iter_chunks(text):
        written = await sink.asend(chunk)
    await sink.aclose()             # flush the partial batch and commit

## The trap this exists to avoid

`vectors.upsert_chunks` **begins with a delete**, which is correct when it is
called once per document and makes re-ingestion idempotent. Called once per
batch it would erase the previous batch every time, leaving only the last one
indexed — no error, and a chunk count that looks plausible. So the delete is
hoisted: `vectors.begin_document()` once, here, then `append_chunks()` per
batch.

## Atomicity is kept

One commit at the end, not one per batch. Python memory stays bounded — the
point of the exercise — and SQLite buffers the transaction, so a document is
still wholly indexed or not at all. Committing per batch would trade a
guarantee that currently holds for free against memory this design has already
bounded.

The failure path follows from that: an error mid-document commits nothing, so
the transaction rolls back — including the delete at the top — and the previous
index survives intact. `aclose()` distinguishes the two cases with a flag,
because a `finally` that flushed unconditionally would retry the very call that
had just failed.
"""

import logging
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.models import DocumentChunk
from app.services import rag, vectors
from app.services.providers import get_embedding_provider
from app.services.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# How many chunks are embedded per Ollama round trip.
#
# `embed()` is natively batched, and the current whole-document path hands it
# *every* chunk in one call — one enormous request for a large upload. 64 is
# small enough to bound memory and large enough that the per-request overhead
# stays negligible next to the embedding itself.
BATCH_SIZE = 64


async def vector_sink(
    session: AsyncSession,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    batch_size: int = BATCH_SIZE,
) -> AsyncGenerator[int, str]:
    """Consume chunk text, embed and store in batches, yield the running count.

    Prime with `await sink.asend(None)`, feed with `await sink.asend(text)`,
    finish with `await sink.aclose()` — which flushes whatever is pending and
    commits.

    The yielded value is how many chunks are written *so far*, so a caller can
    report progress without counting anything itself.
    """
    embedder = get_embedding_provider()

    # Once, not per batch. See the module docstring.
    await vectors.begin_document(session, document_id)
    await crud.clear_chunks(session=session, document_id=document_id)

    pending: list[str] = []
    written = 0
    closed = False

    try:
        while True:
            try:
                chunk = yield written
            except GeneratorExit:
                # aclose(). Fall out and let `finally` flush the partial batch:
                # dropping it would silently lose the document's tail.
                closed = True
                break
            pending.append(chunk)
            if len(pending) >= batch_size:
                written += await _flush(
                    session, owner_id, document_id, pending, written, embedder
                )
                pending.clear()
    finally:
        # Only on a clean close. If we are unwinding from an error — the
        # embedder went down mid-document — flushing would just retry the call
        # that failed, and committing would publish half a document. Doing
        # neither leaves the transaction to roll back, which restores the
        # *previous* index: the delete at the top was never committed either.
        if closed:
            if pending:
                written += await _flush(
                    session, owner_id, document_id, pending, written, embedder
                )
            # One commit for the whole document — see "Atomicity is kept".
            await session.commit()
            logger.info("indexed %d chunks for document %s", written, document_id)


async def _flush(
    session: AsyncSession,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    batch: list[str],
    start_index: int,
    embedder: EmbeddingProvider,
) -> int:
    """Embed and write one batch. Returns how many chunks it added."""
    embeddings = await embedder.embed(batch)
    rows = [
        DocumentChunk(
            document_id=document_id,
            content=content,
            chunk_index=start_index + offset,
            embedding_model=embedder.model,
        )
        for offset, content in enumerate(batch)
    ]
    for row in rows:
        session.add(row)
    # Flush, not commit: the rows must exist for the vector insert to reference
    # them, but the transaction stays open until the sink closes.
    await session.flush()

    await vectors.append_chunks(
        session,
        owner_id,
        document_id,
        [(row.id, vector) for row, vector in zip(rows, embeddings, strict=True)],
        dimensions=embedder.dimensions,
    )
    return len(rows)


async def ingest_streaming(
    *,
    session: AsyncSession,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    text: str,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Chunk, embed and store one document without ever holding all of it.

    The driver for `vector_sink`, and what the upload route calls. Same
    contract as `rag.ingest_document` — returns the chunk count, idempotent
    across re-processing — with bounded memory.
    """
    sink = vector_sink(session, owner_id, document_id, batch_size=batch_size)
    fed = 0
    try:
        # `anext(sink)` is `asend(None)` — the same priming step, spelled the
        # way that type-checks, since the generator's send type is `str`.
        await anext(sink)
        for chunk in rag.iter_chunks(text):
            await sink.asend(chunk)
            # Counted here rather than read from the sink's yield: the final
            # partial batch is written during `aclose()`, after the last yield
            # has already happened. Every chunk fed is a chunk written, so this
            # is the exact count and the yielded one is progress only.
            fed += 1
    finally:
        # Always closed, so the flush-and-commit step runs exactly once on the
        # happy path. On failure the sink skips it and the open transaction
        # rolls back, leaving whatever was indexed before untouched.
        await sink.aclose()
    return fed
