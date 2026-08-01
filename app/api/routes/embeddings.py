"""Embedding, as something a user can run rather than only something that happens.

Jelena's ask: a route that runs `ollama.embed(model=..., input=[...])` over a
list. That is `POST /embeddings/`, and the rest of this module exists because
running it raises the two questions immediately after — *with which model*, and
*can I have a model of my own*.

Everything here is authenticated but not owner-scoped, and that is worth saying
out loud: an embedding model is a fact about the machine, not about a user. No
route here reads or writes a document, a lesson, or an index. It is the
embedding layer held up to the light — which is most of what makes this a
showcase rather than a black box.

The reasoning, including the measurement that changed what the derive route
claims, is in `app/services/embeddings.py`. Read it before editing that claim.
"""

import logging

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser
from app.core.config import settings
from app.models import (
    DeriveModelRequest,
    DerivedModelResult,
    EmbeddingModelInfo,
    EmbedRequest,
    EmbedResult,
)
from app.services import embeddings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


@router.get("/models", response_model=list[EmbeddingModelInfo])
async def list_models(current_user: CurrentUser) -> list[EmbeddingModelInfo]:
    """Every locally installed model that can actually embed.

    Note the difference from `GET /providers/`, which lists models that can
    *chat* and hides anything with "embed" in the name. This asks each model
    what it can do instead of reading its name, so a model derived as
    `my_nomic` appears here and a chat model called `embedder-9b` does not.
    """
    del current_user  # authenticated, but this is a fact about the machine
    return await embeddings.list_embedding_models()


@router.post("/", response_model=EmbedResult)
async def embed(*, current_user: CurrentUser, body: EmbedRequest) -> EmbedResult:
    """Embed a list of texts, and see what came back.

    The direct form of `ollama.embed(model=..., input=[...])`. One round trip
    for the whole list — Ollama batches natively, which is also why the app's
    own ingestion hands it every chunk at once.

    Vectors come back as a short preview plus dimension and magnitude unless
    `full` is set. That is not caution about size; it is that nobody reads 768
    floats, and a response that is normally fifteen kilobytes of numbers trains
    its caller to stop looking at responses.

    Not owner-scoped, and nothing is stored. This embeds and returns — it does
    not index, and it cannot reach anyone's corpus.
    """
    del current_user
    try:
        return await embeddings.embed_texts(
            model=body.model or settings.EMBEDDING_MODEL,
            texts=body.texts,
            full=body.full,
        )
    except embeddings.EmbeddingRequestError as exc:
        # The caller's mistake, and fixable by them — 422, with the fix in it.
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/models", response_model=DerivedModelResult)
async def derive_model(
    *, current_user: CurrentUser, body: DeriveModelRequest
) -> DerivedModelResult:
    """Create a named embedding model from a base one.

    **What this does and does not do**, because the difference is the whole
    reason the reply carries `note_affects_vectors`:

    It gives you a name you own for the exact weights a base model has today.
    Point `EMBEDDING_MODEL` at that name and re-pulling the base upstream cannot
    silently change the numbers under an index that has no way to survive the
    change (hard rule #5). That is a real and useful property.

    It does **not** make the model behave differently. A `note` is stored as a
    `SYSTEM` line and read by nothing, because an embedding model has no
    generation step. Measured on 2026-08-01 against the live Ollama: identical
    vectors, maximum absolute difference 0.0. The reply says so rather than
    letting a "custom model created" message imply otherwise.

    Superuser only. It writes to the machine's model store, which is shared by
    every user of this app — an ordinary account creating tags there is a
    surprise nobody asked for, and the tag it would most plausibly overwrite is
    the one the whole index depends on.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail=(
                "Deriving a model writes to this machine's shared Ollama store, "
                "so it is a superuser action."
            ),
        )
    try:
        return await embeddings.derive_model(
            name=body.name,
            base=body.base or settings.EMBEDDING_MODEL,
            note=body.note,
        )
    except embeddings.EmbeddingRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/models/{name}/modelfile")
async def download_modelfile(*, current_user: CurrentUser, name: str) -> Response:
    """The Modelfile for a derived model, as a download.

    This is the downloadable artifact, and it is text rather than weights on
    purpose. The alternative — copying a 274 MB GGUF blob into `web/public/` —
    puts it in git and in the Docker image and gains nothing: any Ollama
    anywhere rebuilds the real model from these few hundred bytes with

        ollama create <name> -f Modelfile

    and the file carries the *intent* of the pin, which the blob would not.
    """
    del current_user
    try:
        base = settings.EMBEDDING_MODEL
        content = embeddings.build_modelfile(name=name, base=base)
    except embeddings.EmbeddingRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="Modelfile"'},
    )
