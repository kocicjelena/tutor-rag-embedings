"""The tools themselves.

Deliberately free of any MCP import. These are ordinary async functions over
the same services the HTTP routes use, which means:

  * they can be tested without a protocol session;
  * MCP is a *transport* over existing behaviour, not a parallel implementation
    that can drift from it;
  * a second transport later costs nothing here.

Two rules hold for every function below.

**No tool takes an owner.** The caller comes from `app.mcp.context`, which only
an authenticated route can set. See that module for why a parameter would be
unsafe.

**No tool generates text.** Retrieval only. An agent already has a model — the
one deciding to call the tool — so a tool that made its own LLM call would
nest a second, unattributable generation inside the first, hide its cost, and
make the tool-trace panel a lie about what happened. `POST /tutor/recall` is
`search_documents` plus generation, and that composition belongs to the caller.
"""

import uuid
from typing import Any

from app import crud
from app.mcp import context as mcp_context
from app.services import rag, tutor_model

# The model chooses `top_k`. Clamped, because "top_k": 100000 is one token of
# prompt injection away and would drag the whole corpus into the reply.
MIN_TOP_K = 1
MAX_TOP_K = 20
DEFAULT_TOP_K = 5

# Ceiling on `list_documents`, for the same reason.
MAX_DOCUMENTS = 100

# Ceiling on how much of one document `get_document` will return.
MAX_DOCUMENT_CHARS = 8_000


class ToolInputError(ValueError):
    """The model passed something unusable. Reported back to it, not raised at the user."""


async def search_documents(query: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """Semantic search over everything the current user owns.

    This is the retrieval half of `POST /tutor/recall`, reached by a different
    transport — the same embed-then-KNN path, owner-scoped inside the index.
    """
    ctx = mcp_context.require()
    if not query.strip():
        raise ToolInputError("query must not be empty")

    retrieval = await rag.retrieve(
        session=ctx.session,
        owner_id=ctx.owner_id,
        question=query,
        top_k=max(MIN_TOP_K, min(top_k, MAX_TOP_K)),
    )

    return {
        "query": query,
        "match_count": len(retrieval.sources),
        "matches": [
            {
                "chunk_id": str(source.chunk_id),
                "document_id": str(source.document_id),
                "document_title": source.document_title,
                # Similarity, not distance: 1.0 is identical, and it is the same
                # number the source panel shows, so a trace and the UI agree.
                "score": source.score,
                "content": source.content,
            }
            for source in retrieval.sources
        ],
    }


async def list_documents() -> dict[str, Any]:
    """Everything the current user owns — uploads and recorded lessons alike."""
    ctx = mcp_context.require()
    documents, total = await crud.get_documents(
        session=ctx.session, owner_id=ctx.owner_id, limit=MAX_DOCUMENTS
    )

    return {
        "total": total,
        "returned": len(documents),
        "documents": [
            {
                "document_id": str(document.id),
                "title": document.title,
                "topic": document.description,
                # "tutor/interaction" marks a recorded lesson; anything else is
                # an uploaded file. Worth exposing — an agent asked "what have I
                # been taught?" should not count the user's PDFs as lessons.
                "kind": (
                    "lesson"
                    if document.file_type == tutor_model.TUTOR_FILE_TYPE
                    else "upload"
                ),
                "status": document.status,
                "chunk_count": document.chunk_count,
                "created_at": document.created_at.isoformat(),
            }
            for document in documents
        ],
    }


async def get_document(document_id: str) -> dict[str, Any]:
    """One document the current user owns, with its indexed chunks."""
    ctx = mcp_context.require()

    try:
        parsed_id = uuid.UUID(document_id)
    except ValueError:
        raise ToolInputError(
            f"{document_id!r} is not a document id. Call list_documents first."
        ) from None

    document = await crud.get_document(session=ctx.session, doc_id=parsed_id)
    # One message for "no such document" and for "not yours". Distinguishing
    # them would turn this tool into an existence oracle for other users' ids —
    # the same reasoning as the 401-not-404 in `deps.get_current_user`.
    if document is None or document.owner_id != ctx.owner_id:
        raise ToolInputError(f"No document {document_id} is available to you.")

    chunks = await crud.get_chunks_for_document(
        session=ctx.session, document_id=parsed_id
    )

    # Chunks overlap, so they are returned as a list rather than joined into
    # something that would read as the original text but isn't.
    budget = MAX_DOCUMENT_CHARS
    included: list[dict[str, Any]] = []
    for chunk in chunks:
        if budget <= 0:
            break
        included.append({"index": chunk.chunk_index, "content": chunk.content[:budget]})
        budget -= len(chunk.content)

    return {
        "document_id": str(document.id),
        "title": document.title,
        "topic": document.description,
        "kind": (
            "lesson"
            if document.file_type == tutor_model.TUTOR_FILE_TYPE
            else "upload"
        ),
        "status": document.status,
        "chunk_count": document.chunk_count,
        "created_at": document.created_at.isoformat(),
        "chunks": included,
        "truncated": len(included) < len(chunks),
    }


async def recall_lessons(question: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """Ask this learner's own model: what have *they* been taught about something.

    ## Why this is not `search_documents` with a filter

    It is, mechanically. The difference is the contract, and that difference is
    the reason this tool exists — Jelena's instruction, recorded in
    `.claude/rules/PLAN.md`: the learner's material should be *integrated as a
    tool*, not merely stored where a tool can look.

    `search_documents` is a document store. From the model's side it cannot tell
    a lesson from a PDF, and it has no notion of what this person has been
    taught. This one's contract is the corpus: it answers from lessons only, and
    it can say *"never taught"* — a claim `search_documents` is not entitled to
    make, because a miss there might simply mean the answer was in an upload.

    That distinction is what makes the answer worth something. "You have not
    been taught this" is useful to someone studying; "no document matched" is
    not the same sentence.

    ## Retrieval only

    No generation, like every other tool here. The calling model already has a
    model; a tool that made its own LLM call would nest an unattributable
    generation inside the first and make the trace panel a lie.
    `POST /tutor/recall` is this plus generation, and that composition belongs
    to the caller.
    """
    ctx = mcp_context.require()
    if not question.strip():
        raise ToolInputError("question must not be empty")

    lessons, truncated = await tutor_model.lesson_ids(
        session=ctx.session, owner_id=ctx.owner_id
    )
    if not lessons:
        # An empty corpus is a *result*, and a definite one. Saying so beats
        # returning zero matches, which the model would have to guess about.
        return {
            "question": question,
            "taught": False,
            "match_count": 0,
            "matches": [],
            "note": (
                "This learner has never been taught anything by the tutor. "
                "Say so — do not answer from your own knowledge, and do not "
                "search again."
            ),
        }

    retrieval = await rag.retrieve(
        session=ctx.session,
        owner_id=ctx.owner_id,
        question=question,
        top_k=max(MIN_TOP_K, min(top_k, MAX_TOP_K)),
        document_ids=lessons,
    )

    return {
        "question": question,
        "taught": True,
        "lessons_searched": len(lessons),
        # Reported, never hidden. A silent truncation would turn "the oldest
        # lessons were not considered" into "you were never taught that".
        "truncated": truncated,
        "match_count": len(retrieval.sources),
        "matches": [
            {
                "lesson_id": str(source.document_id),
                "topic": source.document_title,
                "score": source.score,
                "content": source.content,
            }
            for source in retrieval.sources
        ],
        "note": (
            "These are the learner's own lessons and nothing else. If the "
            "scores are low, they have probably not covered this — say so and "
            "name what they have covered instead."
        ),
    }


async def tutor_stats() -> dict[str, Any]:
    """What the current user's model contains: lesson count, topics, chunks."""
    ctx = mcp_context.require()
    stats = await tutor_model.corpus_stats(
        session=ctx.session, owner_id=ctx.owner_id
    )
    return stats.model_dump()
