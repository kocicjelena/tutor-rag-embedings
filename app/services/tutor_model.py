"""The learner's model: recording, exporting, importing.

"The model" in this app is the learner's corpus — the lessons they were taught,
plus metadata. See `.claude/rules/PLAN.md` §7 for why that is a corpus rather than a set
of weights, and how the other two export tiers derive from this one.

The point of this module is that **record, import and seed are one code path**.
`record_lesson` is the only way a lesson enters the corpus, whichever direction
it arrives from:

    POST /tutor/interactions  ─┐
    POST /tutor/model/import  ─┼─→ record_lesson ─→ Document + chunks + vectors
    seed fixtures on startup  ─┘                     + TutorLesson (verbatim)

`build_export` is that same shape read back out. Keeping the two symmetrical is
what makes a downloaded `model.json` genuinely reloadable, rather than a
plausible-looking file nobody ever tries to import.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app import crud
from app.core.config import settings
from app.models import (
    TUTOR_MODEL_FORMAT,
    TUTOR_MODEL_VERSION,
    Document,
    DocumentChunk,
    TutorLesson,
    TutorLessonExport,
    TutorModelExport,
    TutorModelImportResult,
    TutorModelMeta,
    TutorStats,
)
from app.services import rag
from app.services.providers import ProviderUnavailableError, get_embedding_provider

logger = logging.getLogger(__name__)

# Marks a document as a recorded lesson rather than an uploaded file.
TUTOR_FILE_TYPE = "tutor/interaction"


def compose_lesson_text(term: str, question: str, answer: str) -> str:
    """The text that gets chunked and embedded.

    Both sides of the exchange go in together, so a later question matches on
    how the learner phrased it *and* on what the tutor explained.
    """
    return f"Topic: {term}\n\nQuestion: {question}\n\nAnswer: {answer}"


async def record_lesson(
    *,
    session: AsyncSession,
    owner_id: uuid.UUID,
    term: str,
    question: str,
    answer: str,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[Document, int]:
    """Index one exchange and keep it verbatim. Returns (document, chunk_count).

    Indexed synchronously, unlike file upload: it is one short text and one
    embedding call, and the learner may switch to recall immediately afterwards.
    Waiting on a background task here would make the model look forgetful.
    """
    text = compose_lesson_text(term, question, answer)

    doc = await crud.create_document(
        session=session,
        owner_id=owner_id,
        # The title becomes the citation label in the source panel, so make it
        # read like a lesson.
        title=f"{term} — {question[:60]}",
        description=term,
        file_type=TUTOR_FILE_TYPE,
    )

    try:
        count = await rag.ingest_document(
            session=session,
            owner_id=owner_id,
            document_id=doc.id,
            text=text,
        )
    except ProviderUnavailableError:
        doc.status = "error"
        doc.error_message = "embedding provider unavailable"
        session.add(doc)
        await session.commit()
        raise

    doc.status = "ready"
    doc.chunk_count = count
    doc.char_count = len(text)
    session.add(doc)
    session.add(
        TutorLesson(
            owner_id=owner_id,
            document_id=doc.id,
            term=term,
            question=question,
            answer=answer,
            taught_by_provider=provider,
            taught_by_model=model,
        )
    )
    await session.commit()

    return doc, count


async def build_export(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> TutorModelExport:
    """Read the learner's model out as one self-contained document.

    Owner-scoped, like everything else. Carries no vectors (reproducible, and
    valid for one embedding space only) and nothing identifying the learner —
    this file exists to be downloaded, shared, and used as a seed fixture.
    """
    result = await session.execute(
        select(TutorLesson)
        .where(TutorLesson.owner_id == owner_id)
        .order_by(TutorLesson.created_at)  # pyright: ignore[reportArgumentType]
    )
    lessons = list(result.scalars().all())

    embedder = get_embedding_provider()

    return TutorModelExport(
        indexed_with=TutorModelMeta(
            embedding_model=embedder.model,
            embedding_dimensions=settings.EMBEDDING_DIMENSIONS,
        ),
        topics=sorted({lesson.term for lesson in lessons if lesson.term}),
        lesson_count=len(lessons),
        lessons=[
            TutorLessonExport(
                term=lesson.term,
                question=lesson.question,
                answer=lesson.answer,
                taught_by_provider=lesson.taught_by_provider,
                taught_by_model=lesson.taught_by_model,
                learned_at=lesson.created_at,
            )
            for lesson in lessons
        ],
    )


async def topics_for(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> list[str]:
    """Distinct lesson topics in this learner's corpus, alphabetically."""
    result = await session.execute(
        select(Document.description)
        .where(Document.owner_id == owner_id)
        .where(Document.file_type == TUTOR_FILE_TYPE)
        .distinct()
    )
    return sorted({row for row in result.scalars().all() if row})


async def corpus_stats(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> TutorStats:
    """Progress read from the index, not from a client-side tally.

    Lives here rather than in the route because two callers need it: `GET
    /tutor/stats` and the `tutor_stats` MCP tool. One implementation means the
    number an agent reports can never drift from the number on the page.
    """
    interactions = (
        await session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.owner_id == owner_id)
            .where(Document.file_type == TUTOR_FILE_TYPE)
        )
    ).scalar_one()

    chunks = (
        await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)  # pyright: ignore[reportArgumentType]
            .where(Document.owner_id == owner_id)
        )
    ).scalar_one()

    return TutorStats(
        interactions=int(interactions),
        topics=await topics_for(session=session, owner_id=owner_id),
        indexed_chunks=int(chunks),
        embedding_model=get_embedding_provider().model,
    )


def is_supported(format_: str, version: int) -> bool:
    return format_ == TUTOR_MODEL_FORMAT and version == TUTOR_MODEL_VERSION


async def apply_import(
    *,
    session: AsyncSession,
    owner_id: uuid.UUID,
    lessons: list[TutorLessonExport],
) -> TutorModelImportResult:
    """Load lessons into `owner_id`'s corpus, re-embedding as they arrive.

    `owner_id` comes from the caller's token and is never read from the file —
    the same rule the MCP tools will follow. A file naming someone else's
    learner cannot import into their corpus, because the file has no say.

    Re-embedding rather than trusting stored vectors is what makes a model
    exported under one embedding model loadable under another.
    """
    imported = 0
    skipped = 0
    chunks = 0

    for lesson in lessons:
        # Empty fields would produce a document with no retrievable content and
        # a citation label of "— ". Skip rather than poison the corpus.
        if not (lesson.term.strip() and lesson.question.strip() and lesson.answer.strip()):
            skipped += 1
            continue

        _, count = await record_lesson(
            session=session,
            owner_id=owner_id,
            term=lesson.term,
            question=lesson.question,
            answer=lesson.answer,
            provider=lesson.taught_by_provider,
            model=lesson.taught_by_model,
        )
        imported += 1
        chunks += count

    if skipped:
        logger.info("import skipped %d incomplete lesson(s)", skipped)

    return TutorModelImportResult(
        imported=imported,
        skipped=skipped,
        indexed_chunks=chunks,
        embedding_model=get_embedding_provider().model,
    )
