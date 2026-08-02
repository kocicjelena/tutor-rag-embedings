"""The learning tutor.

Three moves, matching the tutor UI's two "model sources":

  teach   → generate a fresh explanation (no retrieval). The tutor teaching.
  record  → index that exchange into the learner's own corpus.
  recall  → answer from what the learner has already been taught (retrieval).

`recall` is the part that replaces the ported app's `answerWithTrainedModel()`,
which compared raw strings by shared-word count over browser storage and replayed
the closest past answer verbatim. Semantic retrieval means "what are vector
representations" now finds the lesson on embeddings; synthesis over the top-k
means the answer is composed rather than replayed; and because the corpus is
server-side and owner-scoped, it survives the browser and keeps improving.
"""

import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.api.deps import CallerAnthropicKey, CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    TUTOR_MODEL_FORMAT,
    TUTOR_MODEL_VERSION,
    ChunkResult,
    LearnRequest,
    LearnResponse,
    LearningModelState,
    LearningNeighboursPublic,
    LearningSimilarRequest,
    TutorInteractionCreate,
    TutorInteractionPublic,
    TutorModelExport,
    TutorModelImport,
    TutorModelImportResult,
    TutorRecallRequest,
    TutorRecallResponse,
    TutorStats,
    TutorTeachRequest,
)
from app.schemas.events import (
    SSE_MEDIA_TYPE,
    DoneEvent,
    ErrorEvent,
    ProviderEvent,
    TokenEvent,
)
from app.services import learning_stream, quota, rag, tutor_model
from app.services.providers import (
    ProviderUnavailableError,
    get_chat_provider,
    resolve_model,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tutor", tags=["tutor"])

NOT_LEARNED_YET = (
    "I haven't been taught that yet. Switch to the tutor and ask — once we've "
    "covered it, I'll be able to answer from your own lessons."
)


def _teach_prompt(term: str, mode: str, goals: list[str]) -> str:
    base = (
        f"You are an AI/ML tutor helping a learner understand {term}.\n"
        "Explain clearly, with a concrete example. Prefer plain language over "
        "jargon, and define any term you must introduce.\n"
    )
    if mode == "structured":
        base += (
            "Structure the explanation, and end with one short question that "
            "checks whether the learner followed it.\n"
        )
    else:
        base += "Keep it conversational.\n"
    if goals:
        base += f"\nThe learner's stated goals: {', '.join(goals)}."
    return base


def _recall_prompt(context: str) -> str:
    return (
        "You are the learner's own model, answering only from lessons they have "
        "already been taught. The numbered lessons below are that history.\n\n"
        "Answer using ONLY those lessons. Cite them as [1], [2]. If they do not "
        "cover the question, say so plainly and name what they do cover — do not "
        "answer from outside knowledge, and do not guess. Being honest about a "
        "gap is more useful to a learner than a confident wrong answer.\n\n"
        f"LESSONS:\n{context}"
    )


# ──────────────────────────── teach ────────────────────────────

@router.post("/teach")
async def teach(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    anthropic_key: CallerAnthropicKey,
    body: TutorTeachRequest,
) -> StreamingResponse:
    """Stream a fresh explanation. No retrieval — this is the tutor teaching.

    The client records the completed exchange via POST /tutor/interactions.
    """
    # Checked here as well as at the recording step, and this is the kinder of
    # the two places: a learner who is out of lessons should be told before an
    # answer streams in front of them, not after they have read it and tried to
    # keep it. `session` exists on this route for no other reason.
    await quota.require_lesson_allowance(session, current_user)

    provider = get_chat_provider(body.provider, api_key=anthropic_key)
    model = resolve_model(provider, body.model)
    system = _teach_prompt(body.term, body.mode, body.goals)

    async def event_stream() -> AsyncIterator[str]:
        try:
            yield ProviderEvent(provider=provider.name, model=model).to_sse()
            async for fragment in provider.stream(
                system=system, user=body.question, model=model
            ):
                yield TokenEvent(text=fragment).to_sse()
            yield DoneEvent().to_sse()
        except ProviderUnavailableError as exc:
            logger.warning("teach aborted: %s", exc.detail)
            yield ErrorEvent(message=exc.detail, code="provider_unavailable").to_sse()
        except Exception as exc:
            logger.exception("teach failed")
            yield ErrorEvent(
                message=f"{type(exc).__name__}: {exc}", code="internal"
            ).to_sse()

    return StreamingResponse(
        event_stream(),
        media_type=SSE_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────── record ────────────────────────────

@router.post("/learn", response_model=LearnResponse)
async def learn(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: LearnRequest,
) -> LearnResponse:
    """Push pieces of learning up the channel, as they happen.

    The other end of `POST /tutor/interactions`, and not a replacement for it:
    that route records a *finished* exchange into the searchable corpus, this
    one builds the model **while** the learning happens. Nothing here writes to
    the search index.

    The work goes through `learning_stream.learning_sink`, an async generator
    that embeds in small batches and commits once. What comes back is the state
    of the model as SQLite now holds it — the browser mirrors that rather than
    keeping its own tally, so a client that missed a response recovers from the
    next one.

    Retries are safe: `(owner_id, session_id, seq)` is unique, and a piece that
    was already stored comes back in `skipped`.
    """
    requested = [p.seq for p in body.pieces]
    already = {
        event.seq
        for event in await learning_stream.read_events(
            session, current_user.id, body.session_id, requested
        )
    }

    sink = learning_stream.learning_sink(
        session, current_user.id, body.session_id, term=body.term
    )
    await anext(sink)
    for piece in body.pieces:
        await sink.asend(piece)
    await sink.aclose()

    accepted = [
        piece.seq
        for piece in body.pieces
        if piece.seq not in already and piece.text.strip()
    ]
    return LearnResponse(
        accepted=await learning_stream.read_events(
            session, current_user.id, body.session_id, accepted
        ),
        skipped=sorted(already),
        state=await learning_stream.read_state(
            session, current_user.id, body.session_id
        ),
    )


@router.get("/learn", response_model=LearningModelState)
async def learning_state(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
) -> LearningModelState:
    """The model for one teaching session, as SQLite holds it.

    The other half of *mirror, do not accumulate*: the push already returns the
    state, but a browser that reloaded has no state to be returned to. This is
    how the context rehydrates — and it is what lets the client resume the
    sequence from `last_seq + 1` instead of starting again at zero and
    colliding with rows that are already there.

    Unknown session ids are not an error. A session with nothing in it reads as
    a session with nothing in it.
    """
    return await learning_stream.read_state(session, current_user.id, session_id)


@router.post("/learn/similar", response_model=LearningNeighboursPublic)
async def learning_similar(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: LearningSimilarRequest,
) -> LearningNeighboursPublic:
    """What in this learner's own model resembles a passage.

    The reason the vectors are kept rather than computed and discarded, and the
    thing that makes them worth the storage: piece-to-piece similarity over the
    learner's material **without re-embedding it**. One embedding call for the
    passage, one KNN against `vec_learning`, done.

    Not a search over documents. `POST /tutor/recall` does that, against
    `vec_chunks`, over canonical chunks of finished lessons. This looks at the
    pieces as they actually arrived, so it answers a different question — *have
    I been told this before, and when* — and the two indexes are never mixed,
    because their distances are not on a common scale.

    Nothing is generated here. It returns passages the learner already has.
    """
    return await learning_stream.similar(
        session,
        current_user.id,
        body.text,
        top_k=body.top_k,
        session_id=body.session_id,
    )


@router.post("/interactions", response_model=TutorInteractionPublic, status_code=201)
async def record_interaction(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: TutorInteractionCreate,
) -> TutorInteractionPublic:
    """Index one completed exchange into the learner's corpus.

    The work lives in `tutor_model.record_lesson`, which is also what import and
    seeding call — so a lesson enters the corpus exactly one way, however it
    arrived.
    """
    # The write that actually costs an embedding, so this is the check that has
    # to hold even if a client skipped /teach or called this route directly.
    # /teach checks too, but only so the refusal arrives before the answer does.
    await quota.require_lesson_allowance(session, current_user)

    doc, count = await tutor_model.record_lesson(
        session=session,
        owner_id=current_user.id,
        term=body.term,
        question=body.question,
        answer=body.answer,
        provider=body.provider,
        model=body.model,
    )
    return TutorInteractionPublic(
        document_id=doc.id, term=body.term, chunk_count=count
    )


# ──────────────────────── the model: export / import ────────────────────────

@router.get("/model/export", response_model=TutorModelExport)
async def export_model(
    session: SessionDep, current_user: CurrentUser
) -> Response:
    """Download the learner's model as one JSON document.

    This is tier 1 in `.claude/rules/PLAN.md` §7 — the source of truth. It carries the
    lessons and their metadata, but no vectors (reproducible from the text, and
    valid for one embedding space only) and nothing identifying the learner.

    Returned as an attachment rather than a plain body: the point of this route
    is that a browser saves a file the learner can keep.
    """
    export = await tutor_model.build_export(
        session=session, owner_id=current_user.id
    )
    return Response(
        content=export.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="tutor-model.json"'
        },
    )


@router.get("/model/modelfile")
async def export_modelfile(
    session: SessionDep,
    current_user: CurrentUser,
    base_model: str | None = None,
) -> Response:
    """Download the learner's model as a **runnable** Ollama Modelfile.

    Tier 2 of `.claude/rules/PLAN.md` §7. Tier 1 hands the learner a JSON file
    they cannot do anything with; this one is two commands from a model that
    answers in their own material:

        ollama create my-model -f Modelfile
        ollama run my-model

    It is a *prompted* model, not a fine-tuned one, and the file's own header
    says so — the lessons ride in the base model's context. That takes seconds
    and no GPU. A real fine-tune is tier 3, produces a different object, and
    cannot run on this hardware.

    `base_model` is the learner's, not this app's. It defaults to the
    configured Ollama chat model, is never validated against what *this*
    machine holds, and is never downloaded here: `ollama create` resolves it on
    the learner's own machine, which is the only place it has to exist.
    """
    export = await tutor_model.build_export(
        session=session, owner_id=current_user.id
    )
    content = tutor_model.build_modelfile(
        export=export,
        base_model=(base_model or settings.OLLAMA_CHAT_MODEL).strip(),
    )
    return Response(
        content=content,
        # text/plain, not an invented type: a Modelfile is a text file, and a
        # learner who opens it instead of saving it should be able to read it.
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="Modelfile"'},
    )


@router.post("/model/import", response_model=TutorModelImportResult)
async def import_model(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: TutorModelImport,
) -> TutorModelImportResult:
    """Load a model file into the caller's corpus, re-embedding as it lands.

    **`owner_id` comes from the token, never from the file.** A file cannot
    name the learner it imports into — the same rule the MCP tools will follow,
    and the single place tenant isolation could be undone by a new feature.

    Additive, not a replacement: importing merges into whatever is already
    there. Wiping first would make a mistyped upload destructive.
    """
    if not tutor_model.is_supported(body.format, body.version):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported model file: format={body.format!r} "
                f"version={body.version}. This app reads "
                f"{TUTOR_MODEL_FORMAT!r} version {TUTOR_MODEL_VERSION}."
            ),
        )

    return await tutor_model.apply_import(
        session=session,
        owner_id=current_user.id,
        lessons=body.lessons,
    )


# ──────────────────────────── recall ────────────────────────────

@router.post("/recall", response_model=TutorRecallResponse)
async def recall(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    anthropic_key: CallerAnthropicKey,
    body: TutorRecallRequest,
) -> TutorRecallResponse:
    """Answer from the learner's own history.

    Searches everything this learner owns — recorded lessons and any documents
    they uploaded. That is deliberate: both are things they have been exposed to,
    and the source panel names each one, so provenance stays visible.
    """
    provider = get_chat_provider(body.provider, api_key=anthropic_key)
    model = resolve_model(provider, body.model)

    retrieval = await rag.retrieve(
        session=session,
        owner_id=current_user.id,
        question=body.question,
        top_k=body.top_k,
    )

    if retrieval.empty:
        topics = await tutor_model.topics_for(
            session=session, owner_id=current_user.id
        )
        covered = (
            f" So far we've covered: {', '.join(topics)}." if topics else ""
        )
        return TutorRecallResponse(
            question=body.question,
            answer=NOT_LEARNED_YET + covered,
            sources=[],
            provider=provider.name,
            model=model,
            grounded=False,
        )

    answer = await provider.complete(
        system=_recall_prompt(retrieval.context),
        user=body.question,
        model=model,
    )

    return TutorRecallResponse(
        question=body.question,
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
        grounded=True,
    )


# ──────────────────────────── stats ────────────────────────────

@router.get("/stats", response_model=TutorStats)
async def stats(session: SessionDep, current_user: CurrentUser) -> TutorStats:
    """Corpus-derived progress.

    These are counts from the index, not a client-side tally — so the progress
    cards report what the learner's model actually contains. The same function
    backs the `tutor_stats` MCP tool, so the page and an agent cannot disagree.
    """
    return await tutor_model.corpus_stats(
        session=session, owner_id=current_user.id
    )
