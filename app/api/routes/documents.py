"""Document upload, listing, and deletion."""

import io
import logging
import uuid

import pypdf
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Document, DocumentPublic, DocumentsPublic, Message
from app.services import ingest_stream
from app.services.providers import ProviderUnavailableError, get_embedding_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/pdf",
    "application/octet-stream",  # curl sends this for unknown extensions
}


async def _process_document(
    document_id: uuid.UUID, owner_id: uuid.UUID, text: str
) -> None:
    """Background: chunk, embed, store. Owns its own session.

    Failures record `error_message` on the document. The inherited version used
    a bare `except` that set status="error" with nothing else, so ingestion
    failures were undiagnosable.
    """
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        doc.status = "processing"
        session.add(doc)
        await session.commit()

        try:
            # The streaming path: chunks are embedded and written in batches,
            # so peak memory is one batch rather than the whole document. The
            # tutor still uses `rag.ingest_document` — one short lesson, where
            # streaming buys nothing. See `docs/VECTORS.md`.
            count = await ingest_stream.ingest_streaming(
                session=session,
                owner_id=owner_id,
                document_id=document_id,
                text=text,
            )
            doc.chunk_count = count
            doc.char_count = len(text)
            doc.status = "ready"
            doc.error_message = None
        except ProviderUnavailableError as exc:
            logger.error("ingest %s failed: %s", document_id, exc.detail)
            doc.status = "error"
            doc.error_message = exc.detail
        except Exception as exc:
            logger.exception("ingest %s failed", document_id)
            doc.status = "error"
            doc.error_message = f"{type(exc).__name__}: {exc}"
        finally:
            session.add(doc)
            await session.commit()


def _extract_text(content_type: str | None, raw: bytes) -> str:
    if content_type == "application/pdf" or raw[:5] == b"%PDF-":
        try:
            reader = pypdf.PdfReader(io.BytesIO(raw))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise HTTPException(422, f"Could not parse PDF: {exc}") from exc
    return raw.decode("utf-8", errors="replace")


async def _public(
    session: SessionDep, docs: list[Document]
) -> list[DocumentPublic]:
    """Add `indexed_with` / `searchable` — one query for the whole page.

    A document indexed by a different embedding model is invisible to search,
    because vectors from two models are not comparable and each width has its
    own index. Reporting that is cheap and honest; merging the two indexes
    would produce a ranking that looked fine and meant nothing.
    """
    active = get_embedding_provider().model
    models = await crud.get_embedding_models(
        session=session, doc_ids=[d.id for d in docs]
    )
    result: list[DocumentPublic] = []
    for doc in docs:
        public = DocumentPublic.model_validate(doc, from_attributes=True)
        public.indexed_with = models.get(doc.id)
        # Nothing indexed yet (pending, empty, or failed) is not "unsearchable"
        # — there is simply nothing to say about it.
        public.searchable = public.indexed_with in (None, active)
        result.append(public)
    return result


@router.get("/", response_model=DocumentsPublic)
async def list_documents(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
) -> DocumentsPublic:
    docs, count = await crud.get_documents(
        session=session, owner_id=current_user.id, skip=skip, limit=min(limit, 200)
    )
    return DocumentsPublic(data=await _public(session, list(docs)), count=count)


@router.post("/upload", response_model=DocumentPublic, status_code=201)
async def upload_document(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    title: str | None = None,
    description: str | None = None,
) -> DocumentPublic:
    """Upload text, markdown, CSV, or PDF. Embedding runs in the background."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            415,
            f"Unsupported file type: {file.content_type}. "
            f"Allowed: {', '.join(sorted(ALLOWED_TYPES))}",
        )

    # Bounded read — the inherited code read the whole upload with no limit.
    raw = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(raw) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"File exceeds the {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.",
        )
    if not raw:
        raise HTTPException(422, "File is empty.")

    text = _extract_text(file.content_type, raw)
    if not text.strip():
        raise HTTPException(422, "No extractable text found in the file.")

    doc = await crud.create_document(
        session=session,
        owner_id=current_user.id,
        title=title or file.filename or "Untitled",
        description=description,
        file_type=file.content_type,
    )
    background_tasks.add_task(_process_document, doc.id, current_user.id, text)
    return DocumentPublic.model_validate(doc, from_attributes=True)


async def _get_owned(
    session: SessionDep, current_user: CurrentUser, document_id: uuid.UUID
) -> Document:
    doc = await crud.get_document(session=session, doc_id=document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    if doc.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(403, "Not enough permissions")
    return doc


@router.get("/{document_id}", response_model=DocumentPublic)
async def get_document(
    document_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> DocumentPublic:
    doc = await _get_owned(session, current_user, document_id)
    return (await _public(session, [doc]))[0]


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Message:
    doc = await _get_owned(session, current_user, document_id)
    await crud.delete_document(session=session, db_doc=doc)
    return Message(message="Document deleted successfully")
