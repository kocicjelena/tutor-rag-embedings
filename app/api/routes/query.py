"""RAG query — buffered and streaming.

Both endpoints resolve the provider per request, so the same question can be
answered by a local Ollama model or by Claude without any server restart.
"""

import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.models import ChunkResult, QueryRequest, QueryResponse
from app.schemas.events import (
    SSE_MEDIA_TYPE,
    DoneEvent,
    ErrorEvent,
    ProviderEvent,
    SourcesEvent,
    TokenEvent,
)
from app.services import rag
from app.services.providers import (
    ProviderUnavailableError,
    get_chat_provider,
    resolve_model,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])


async def _check_document_access(
    session: SessionDep, current_user: CurrentUser, doc_ids: list[uuid.UUID]
) -> None:
    """Verify the caller owns every named document.

    Retrieval is already owner-scoped inside the vector index, so this cannot
    leak content — it exists to return an honest 403/404 instead of silently
    empty results.
    """
    found = await crud.get_documents_by_ids(session=session, doc_ids=doc_ids)
    for doc_id in doc_ids:
        doc = found.get(doc_id)
        if doc is None:
            raise HTTPException(404, f"Document {doc_id} not found")
        if doc.owner_id != current_user.id and not current_user.is_superuser:
            raise HTTPException(403, f"Access denied for document {doc_id}")


@router.post("/", response_model=QueryResponse)
async def query_documents(
    *, session: SessionDep, current_user: CurrentUser, query_in: QueryRequest
) -> QueryResponse:
    """Ask a question; get a complete answer grounded in your documents."""
    if query_in.document_ids:
        await _check_document_access(session, current_user, query_in.document_ids)

    provider = get_chat_provider(query_in.provider)
    model = resolve_model(provider, query_in.model)

    retrieval = await rag.retrieve(
        session=session,
        owner_id=current_user.id,
        question=query_in.question,
        top_k=query_in.top_k,
        document_ids=query_in.document_ids,
    )

    if retrieval.empty:
        return QueryResponse(
            question=query_in.question,
            answer=rag.NO_CONTEXT_ANSWER,
            sources=[],
            provider=provider.name,
            model=model,
        )

    answer = await provider.complete(
        system=rag.build_system_prompt(retrieval.context),
        user=query_in.question,
        model=model,
    )

    return QueryResponse(
        question=query_in.question,
        answer=answer,
        sources=[
            ChunkResult(
                chunk_id=s.chunk_id,
                document_id=s.document_id,
                document_title=s.document_title,
                content=s.content,
                score=s.score,
            )
            for s in retrieval.sources
        ],
        provider=provider.name,
        model=model,
    )


@router.post("/stream")
async def query_documents_stream(
    *, session: SessionDep, current_user: CurrentUser, query_in: QueryRequest
) -> StreamingResponse:
    """Stream the answer as typed SSE events.

    Frame order: `provider` → `sources` → `token`* → `done`, or `error`.
    Every frame is one JSON object on one line (see app/schemas/events.py) —
    the inherited `data: {token}` form corrupted on any token containing a
    newline.
    """
    if query_in.document_ids:
        await _check_document_access(session, current_user, query_in.document_ids)

    # Resolve the provider before opening the stream so a misconfiguration is a
    # clean 503 rather than an error frame inside a 200 response.
    provider = get_chat_provider(query_in.provider)
    model = resolve_model(provider, query_in.model)

    async def event_stream() -> AsyncIterator[str]:
        try:
            yield ProviderEvent(provider=provider.name, model=model).to_sse()

            retrieval = await rag.retrieve(
                session=session,
                owner_id=current_user.id,
                question=query_in.question,
                top_k=query_in.top_k,
                document_ids=query_in.document_ids,
            )
            yield SourcesEvent(chunks=retrieval.sources).to_sse()

            if retrieval.empty:
                yield TokenEvent(text=rag.NO_CONTEXT_ANSWER).to_sse()
                yield DoneEvent().to_sse()
                return

            system = rag.build_system_prompt(retrieval.context)
            async for fragment in provider.stream(
                system=system, user=query_in.question, model=model
            ):
                yield TokenEvent(text=fragment).to_sse()

            yield DoneEvent().to_sse()

        except ProviderUnavailableError as exc:
            # Headers are already sent, so this cannot be a 503 — report it as a
            # typed error frame the client can render.
            logger.warning("stream aborted: %s", exc.detail)
            yield ErrorEvent(message=exc.detail, code="provider_unavailable").to_sse()
        except Exception as exc:
            logger.exception("stream failed")
            yield ErrorEvent(
                message=f"{type(exc).__name__}: {exc}", code="internal"
            ).to_sse()

    return StreamingResponse(
        event_stream(),
        media_type=SSE_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stop nginx buffering the stream
        },
    )
