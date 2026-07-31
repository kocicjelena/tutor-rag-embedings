"""RAG pipeline: chunking, ingestion, retrieval, prompt assembly.

Provider-agnostic — nothing here knows whether Ollama or Claude will answer.
"""

import logging
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.core.config import settings
from app.models import DocumentChunk
from app.schemas.events import SourceChunk
from app.services import vectors
from app.services.providers import get_embedding_provider

logger = logging.getLogger(__name__)

CONTEXT_SEPARATOR = "\n\n---\n\n"

SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions about the user's documents.\n"
    "Answer using ONLY the context below. If the answer is not in the context, "
    "say \"I don't have enough information to answer that question.\" — do not "
    "use outside knowledge and do not guess.\n"
    "Cite the source number in square brackets, e.g. [1], for each claim.\n"
    "Be concise.\n\n"
    "CONTEXT:\n{context}"
)


@dataclass(frozen=True)
class Retrieval:
    """What retrieval produced, ready to render or to prompt with."""

    sources: list[SourceChunk]
    context: str

    @property
    def empty(self) -> bool:
        return not self.sources


# ──────────────────────────── Chunking ────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[str]:
    """Every chunk, as a list. The whole-document form.

    Kept as the primary name because every existing caller and test uses it.
    `iter_chunks` is the same algorithm yielding lazily, for the streaming
    ingestion path.
    """
    return list(iter_chunks(text, chunk_size, chunk_overlap))


def iter_chunks(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> Iterator[str]:
    """Split text into overlapping chunks on natural boundaries, lazily.

    Two fixes over the inherited version:

    * Settings are read at call time. They used to be default argument values,
      evaluated once at import, so they could never change at runtime.
    * The loop is guaranteed to advance. `start = end - chunk_overlap` could move
      *backwards* whenever the boundary search landed within `chunk_overlap` of
      `start` — e.g. text with many short lines — producing duplicate chunks
      forever.
    """
    size = chunk_size if chunk_size is not None else settings.CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP
    if size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, size - 1))

    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + size, text_len)
        if end < text_len:
            for boundary in ("\n\n", "\n", ". ", "! ", "? ", " "):
                idx = text.rfind(boundary, start, end)
                if idx > start:
                    end = idx + len(boundary)
                    break

        chunk = text[start:end].strip()
        if chunk:
            yield chunk

        # Everything is consumed — stop. Without this, `start = end - overlap`
        # rewinds into already-emitted text and crawls to the end one character
        # at a time: a 286-char document produced 201 near-duplicate chunks.
        if end >= text_len:
            break

        # Guarantee forward progress regardless of where the boundary landed.
        start = max(end - overlap, start + 1)


# ──────────────────────────── Ingestion ────────────────────────────

async def ingest_document(
    *,
    session: AsyncSession,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    text: str,
) -> int:
    """Chunk, embed, and store. Returns the chunk count.

    Idempotent: both the chunk rows and the vectors are replaced wholesale, so
    re-processing a document does not duplicate or orphan anything.
    """
    raw_chunks = chunk_text(text)
    if not raw_chunks:
        await crud.replace_chunks(session=session, document_id=document_id, chunks=[])
        await vectors.delete_document(session, document_id)
        await session.commit()
        return 0

    embedder = get_embedding_provider()
    embeddings = await embedder.embed(raw_chunks)

    chunks = [
        DocumentChunk(
            document_id=document_id,
            content=content,
            chunk_index=index,
            embedding_model=embedder.model,
        )
        for index, content in enumerate(raw_chunks)
    ]
    await crud.replace_chunks(session=session, document_id=document_id, chunks=chunks)
    await vectors.upsert_chunks(
        session,
        owner_id,
        document_id,
        [(chunk.id, vector) for chunk, vector in zip(chunks, embeddings, strict=True)],
        dimensions=embedder.dimensions,
    )
    await session.commit()
    return len(chunks)


# ──────────────────────────── Retrieval ────────────────────────────

async def retrieve(
    *,
    session: AsyncSession,
    owner_id: uuid.UUID,
    question: str,
    top_k: int,
    document_ids: list[uuid.UUID] | None = None,
) -> Retrieval:
    """Embed the question and fetch the nearest chunks owned by `owner_id`."""
    embedder = get_embedding_provider()
    query_vector = (await embedder.embed([question]))[0]

    # The active provider's own width: retrieval reads exactly the index its
    # own vectors live in. Documents indexed by a different model are not in
    # it, and are reported as unsearchable rather than quietly skipped —
    # `DocumentPublic.searchable`.
    hits = await vectors.search(
        session,
        owner_id,
        query_vector,
        top_k,
        document_ids,
        dimensions=embedder.dimensions,
    )
    if not hits:
        return Retrieval(sources=[], context="")

    chunk_map = await crud.get_chunks_by_ids(
        session=session, chunk_ids=[hit.chunk_id for hit in hits]
    )
    doc_map = await crud.get_documents_by_ids(
        session=session,
        doc_ids=list({c.document_id for c in chunk_map.values()}),
    )

    sources: list[SourceChunk] = []
    for hit in hits:
        chunk = chunk_map.get(hit.chunk_id)
        if chunk is None:
            # Vector present without its row — only reachable if a delete was
            # interrupted between the two tables.
            logger.warning("orphaned vector for chunk %s", hit.chunk_id)
            continue
        doc = doc_map.get(chunk.document_id)
        sources.append(
            SourceChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=doc.title if doc else "(deleted document)",
                content=chunk.content,
                # sqlite-vec returns L2 distance; smaller is closer.
                score=round(1.0 / (1.0 + hit.distance), 4),
            )
        )

    return Retrieval(sources=sources, context=build_context(sources))


def build_context(sources: list[SourceChunk]) -> str:
    """Number the sources so the model can cite them as [1], [2], ..."""
    return CONTEXT_SEPARATOR.join(
        f"[{i}] (from {s.document_title})\n{s.content}"
        for i, s in enumerate(sources, start=1)
    )


def build_system_prompt(context: str) -> str:
    return SYSTEM_PROMPT.format(context=context)


NO_CONTEXT_ANSWER = (
    "I don't have enough information to answer that question — no documents "
    "matched. Upload a document first, or broaden the question."
)
