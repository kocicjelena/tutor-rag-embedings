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
from sqlmodel import col, func, select

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


# How many lesson documents a lessons-only search will consider.
#
# A ceiling rather than a page: the ids become named placeholders in the
# index's `document_id IN (...)` clause, and SQLite has a parameter limit.
# Exceeding it silently would be the bad failure — a search that quietly stopped
# considering the oldest lessons — so `lesson_ids` reports when it truncates and
# the tool says so in its answer.
MAX_LESSON_FILTER = 400


async def lesson_ids(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> tuple[list[uuid.UUID], bool]:
    """Which documents in this learner's corpus are *lessons*, newest first.

    Returns the ids and whether the list was truncated.

    This is what makes a lessons-only tool exact rather than approximate. The
    alternative — search everything, then drop the uploads — is cheaper and
    wrong in a way that hides: if the nearest five passages are all from an
    uploaded PDF, the filter returns nothing and the tool reports "you have not
    been taught this", which is a different and false claim.
    """
    result = await session.execute(
        select(Document.id)
        .where(Document.owner_id == owner_id)
        .where(Document.file_type == TUTOR_FILE_TYPE)
        .order_by(col(Document.created_at).desc())
        .limit(MAX_LESSON_FILTER + 1)
    )
    ids = list(result.scalars().all())
    return ids[:MAX_LESSON_FILTER], len(ids) > MAX_LESSON_FILTER


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


# ──────────────────────── tier 2: the runnable Modelfile ────────────────────

# How many exchanges become MESSAGE pairs.
#
# A ceiling, not a page. Every pair is primed into the base model's context on
# every turn, so a Modelfile carrying three hundred lessons produces a model
# that is slow, expensive in context, and worse at answering than one carrying
# forty. Newest first, because recent study is what a learner is most likely to
# be asking about.
MAX_MODELFILE_PAIRS = 40

# Answers are prose and can be long. A base model's context is finite and
# shared with everything else in the file.
MAX_ANSWER_CHARS = 1200


def _quote_block(text: str) -> str:
    """Wrap text for a Modelfile triple-quoted argument.

    The one thing that can break the file is a literal `\"\"\"` inside the
    content, which would close the block early and turn the rest of a lesson
    into Modelfile syntax. Ollama's parser has no escape for it, so the
    sequence is rewritten rather than escaped — three double quotes become
    three single ones, which reads the same to a person and cannot terminate
    the block.
    """
    return '"""' + text.replace('"""', "'''") + '"""'


def build_modelfile(
    *,
    export: TutorModelExport,
    base_model: str,
    max_pairs: int = MAX_MODELFILE_PAIRS,
) -> str:
    """Render the learner's corpus as an Ollama Modelfile.

    Tier 2 of `.claude/rules/PLAN.md` §7, and the honest half of "download your
    model": tier 1 is a JSON file the learner cannot *do* anything with, and
    this is two commands away from a model that answers in their own material.

        ollama create my-model -f Modelfile
        ollama run my-model

    **It is a prompted model, not a fine-tuned one**, and the file says so in
    its own header rather than leaving the learner to discover it. The lessons
    ride in the context as SYSTEM text and MESSAGE pairs; no weights change,
    nothing is trained, and it works on a laptop with no GPU in seconds. That
    honesty is worth more here than a button that overclaims — a real
    fine-tune is tier 3, needs a GPU this project does not have, and produces
    a *different object*.

    The base model is the learner's choice and is not downloaded by this app:
    the file names it, and `ollama create` resolves it on their machine.
    """
    lessons = [
        lesson
        for lesson in export.lessons
        if lesson.question.strip() and lesson.answer.strip()
    ]
    # Newest first — `build_export` orders oldest-first for a readable archive,
    # which is the wrong end to truncate from when the cap bites.
    lessons = list(reversed(lessons))
    included = lessons[:max_pairs]
    dropped = len(lessons) - len(included)

    topics = export.topics or ["(none recorded)"]
    topic_line = ", ".join(topics[:30])
    if len(topics) > 30:
        topic_line += f", and {len(topics) - 30} more"

    system = (
        "You are a learner's own model. Everything you know here was taught to "
        "this person, one lesson at a time, and recorded as it was taught.\n\n"
        f"Topics studied: {topic_line}.\n\n"
        "Answer from the lessons you carry. When you are asked about something "
        "outside them, say plainly that it was not part of what this learner "
        "studied, and name what was — that is more useful to someone studying "
        "than a confident guess."
    )

    header = [
        "# The learner's model — tier 2, a runnable Ollama model.",
        "#",
        "#     ollama create my-model -f Modelfile",
        "#     ollama run my-model",
        "#",
        "# What this is, said plainly: a PROMPTED model, not a fine-tuned one.",
        "# The lessons below travel in the context window of the base model named",
        "# on the FROM line. No weights were changed and nothing was trained — so",
        "# it takes seconds, needs no GPU, and the base model's own knowledge is",
        "# still in there underneath. Fine-tuning teaches style; retrieval and",
        "# prompting teach knowledge. This is the second kind.",
        "#",
        f"# Exported:      {export.exported_at.isoformat()}",
        f"# Lessons held:  {len(included)} of {export.lesson_count}",
    ]
    if dropped:
        header += [
            f"# Left out:      {dropped} older lessons — every pair is primed on",
            "#                every turn, so the file is capped at the most recent."
            f" Full record: tutor-model.json ({export.lesson_count} lessons).",
        ]
    header += [
        f"# Embedded with: {export.indexed_with.embedding_model}"
        f" ({export.indexed_with.embedding_dimensions}d) — for reference only;"
        " this file carries no vectors.",
        "",
    ]

    lines = header + [
        f"FROM {base_model}",
        "",
        f"SYSTEM {_quote_block(system)}",
        "",
    ]

    for lesson in included:
        answer = lesson.answer.strip()
        if len(answer) > MAX_ANSWER_CHARS:
            answer = answer[:MAX_ANSWER_CHARS].rstrip() + " […]"
        if lesson.term:
            lines.append(f"# {lesson.term}")
        lines.append(f"MESSAGE user {_quote_block(lesson.question.strip())}")
        lines.append(f"MESSAGE assistant {_quote_block(answer)}")
        lines.append("")

    return "\n".join(lines)
