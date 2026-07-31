"""Re-embed documents that the active embedding model cannot search.

    uv run python -m app.scripts.reembed --dry-run
    uv run python -m app.scripts.reembed

Vectors from two embedding models are not comparable, and each width gets its
own `vec0` index (`app/services/vectors.py`), so changing `EMBEDDING_MODEL`
does not corrupt anything — it makes everything indexed under the old model
**unsearchable**. The app reports that per document (`searchable: false` on
`GET /documents/`, and a marker in the UI); this command is how it is fixed.

Chunk *text* is re-used, not re-chunked. `DocumentChunk.content` holds the
exact passages already indexed, so re-embedding is a pure vector operation:
same chunk ids, same boundaries, new vectors. That also means it works for
uploads whose original file is long gone — the demo keeps no file storage.

The old vectors are deleted. One document, one index of record: switching back
to the previous model means running this again, which is symmetric and
inspectable, rather than leaving stale vectors in tables nobody reads.
"""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app import crud
from app.core.db import SessionLocal, engine
from app.models import Document, DocumentChunk
from app.services import vectors
from app.services.ingest_stream import BATCH_SIZE
from app.services.providers import ProviderUnavailableError, get_embedding_provider


async def _stale(session: AsyncSession, active_model: str) -> list[Document]:
    """Documents whose chunks were embedded by some other model."""
    result = await session.execute(select(Document))
    docs = list(result.scalars().all())
    models = await crud.get_embedding_models(
        session=session, doc_ids=[d.id for d in docs]
    )
    return [d for d in docs if models.get(d.id) not in (None, active_model)]


async def _reembed_one(session: AsyncSession, doc: Document) -> int:
    """Re-embed one document in batches. Commits once, at the end."""
    embedder = get_embedding_provider()
    chunks = await crud.get_chunks_for_document(session=session, document_id=doc.id)
    if not chunks:
        return 0

    # Every width, so the document leaves its old index as it enters the new
    # one and cannot be found twice.
    await vectors.begin_document(session, doc.id)

    written = 0
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        embeddings = await embedder.embed([c.content for c in batch])
        for chunk in batch:
            chunk.embedding_model = embedder.model
            session.add(chunk)
        await vectors.append_chunks(
            session,
            doc.owner_id,
            doc.id,
            [(c.id, v) for c, v in zip(batch, embeddings, strict=True)],
            dimensions=embedder.dimensions,
        )
        written += len(batch)

    doc.chunk_count = written
    session.add(doc)
    await session.commit()
    return written


async def main(*, dry_run: bool, only: uuid.UUID | None) -> int:
    embedder = get_embedding_provider()
    print(f"Active embedding model: {embedder.model} ({embedder.dimensions}-dim)")
    print(f"Active index:           {vectors.table_for(embedder.dimensions)}\n")

    # The active width may never have been used on this database.
    async with engine.begin() as conn:
        await vectors.create_vector_table(conn, embedder.dimensions)

    async with SessionLocal() as session:
        stale = await _stale(session, embedder.model)
        if only is not None:
            stale = [d for d in stale if d.id == only]

        if not stale:
            print("Nothing to do — every document is searchable with this model.")
            return 0

        total_chunks = 0
        for doc in stale:
            count = await session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
            )
            n = len(list(count.scalars().all()))
            total_chunks += n
            print(f"  {doc.id}  {n:>5} chunks  {doc.title[:50]}")

        print(f"\n{len(stale)} document(s), {total_chunks} chunk(s) to re-embed.")
        if dry_run:
            print("Dry run — nothing written. Re-run without --dry-run to do it.")
            return 0

        print()
        for doc in stale:
            try:
                written = await _reembed_one(session, doc)
            except ProviderUnavailableError as exc:
                # Stop rather than continue: if the embedder is down, every
                # remaining document fails the same way, and a half-finished
                # run is harder to reason about than one that stopped.
                print(f"FAILED {doc.id}: {exc.detail}")
                await session.rollback()
                return 1
            print(f"  re-embedded {written:>5} chunks  {doc.title[:50]}")

        print(f"\nDone. {len(stale)} document(s) are searchable again.")
    return 0


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be re-embedded and exit",
    )
    parser.add_argument(
        "--document",
        type=uuid.UUID,
        default=None,
        help="re-embed one document by id instead of all stale ones",
    )
    args = parser.parse_args()
    return asyncio.run(main(dry_run=args.dry_run, only=args.document))


if __name__ == "__main__":
    sys.exit(_cli())
