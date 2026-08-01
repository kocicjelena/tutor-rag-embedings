"""Embedding as something the user can run, look at, and pin.

Jelena's ask, `.claude/rules/TODO.md`:

> *"More than just embedding, ollama python has `ollama.embed(model='gemma3',
> input=['The sky is blue because of rayleigh scattering', 'Grass is green
> because of chlorophyll'])`. Please try to make a user accessible route that
> allows running the command."*

and, beside it, a sketch for building a model of her own:

> `ollama.create(model='my_nomic', from_='nomic-embed-text:v1.5',
>  system="You are professor for machine learning and AI development.")`

Both are here. The second is here in a **different form from the sketch**, for a
reason that was measured rather than guessed, and that measurement is the most
useful thing in this module.

## What was measured, 2026-08-01, against the live Ollama on this machine

Created `probe_nomic` from `nomic-embed-text` with exactly that system prompt,
then embedded one sentence with each:

    dims:                768, 768
    identical vectors:   True
    max abs diff:        0.0
    capabilities:        ['embedding']
    modelfile has SYSTEM: True

**The system prompt is stored and has no effect whatsoever.** Not "a small
effect" — the vectors are byte-identical. That is not a bug in Ollama: an
embedding model has no chat template and no prompt assembly step. Text goes
straight into the encoder. `SYSTEM` is a field on a Modelfile that only the
generation path ever reads, and `capabilities: ['embedding']` says this model
has no generation path at all.

So `my_nomic` built that way is `nomic-embed-text` under a second name, with a
sentence attached that nothing will ever read. Believing otherwise would be
expensive later: the app would show a "custom embedding model" that produced the
same numbers as the stock one, and a real difference would be looked for in the
wrong place for a long time.

## Why the derive route exists anyway — it pins, it does not personalise

There is a genuinely good reason to run `ollama.create` over an embedding model,
and it is better than the one in the sketch.

**A derived model is a name you own.** `nomic-embed-text` is a moving tag: pull
it again in six months and the weights may differ. Vectors from two models are
not comparable (hard rule #5), so that is not a cosmetic risk — it is the
`vec_chunks` index quietly ceasing to mean one thing, with no error and a
ranking that still looks plausible. Point `EMBEDDING_MODEL` at `my_nomic`
instead and the app is pinned to the bytes that were there when the corpus was
built, whatever upstream does.

That is a real property, it is worth a route, and it is honest about itself. The
`system` text is still accepted and still stored, because it is a fine place to
record *what this pin is for* — it just does not change a single number, and the
API says so in the reply rather than letting the UI imply otherwise.

## What is deliberately not here

**No copy into `web/public/`.** The sketch ends with
`ollama.copy('my_nomic', '../web/public/my_nomic')` and a `<Link download>`.
`ollama.copy` does not write a file — it is `POST /api/copy` and both arguments
are *model names*, so that call would create a model whose name is the literal
string `../web/public/my_nomic` inside Ollama's own store, and `web/public/`
would stay empty. The file it is reaching for is a GGUF blob in
`~/.ollama/models/blobs/`, 274 MB, and `web/public/` is copied into the git
repository and into the Docker image — so that is 274 MB in both, forever.

The download that *is* worth having is the **Modelfile**: a few hundred bytes of
text that names the base model, the pin, and the note, and which any Ollama
anywhere turns back into the real thing with `ollama create -f`. That is tier 2
of `.claude/rules/PLAN.md` §7 arriving early, and it is `build_modelfile` below.
"""

import logging
import re
from collections.abc import Sequence

import httpx
from ollama import ResponseError as OllamaResponseError

from app.core.config import settings
from app.models import (
    DerivedModelResult,
    EmbedResult,
    EmbeddingModelInfo,
    EmbeddingVector,
)
from app.services.providers.base import ProviderUnavailableError
from app.services.providers.ollama_provider import NAME, forget_model, get_client

logger = logging.getLogger(__name__)

# How many texts one call may embed, and how long each may be.
#
# Ollama's `embed` is natively batched, so the cost of a long list is real work
# rather than round trips — which is exactly why it needs a ceiling on a route a
# user can reach. Neither limit is about safety from the user; both are about
# one request not occupying the single-writer app for a minute.
MAX_INPUTS = 64
MAX_INPUT_CHARS = 8_000

# What a model name may contain. Ollama accepts `namespace/name:tag`, and this
# is the boundary that keeps a path out of one — the sketch this module replaces
# tried to pass `../web/public/my_nomic` as a model name.
MODEL_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*(/[a-zA-Z0-9._-]+)?(:[a-zA-Z0-9._-]+)?$")

# How many components of a vector come back by default. A 768-float array per
# input is not something a browser panel can display, and shipping it by default
# would make every response ~15 KB of numbers nobody reads.
PREVIEW_COMPONENTS = 8


class EmbeddingRequestError(ValueError):
    """The caller asked for something unusable. A 422, not a 503."""


def _check_model_name(name: str) -> str:
    cleaned = name.strip()
    if not MODEL_NAME.match(cleaned):
        raise EmbeddingRequestError(
            f"{name!r} is not a model name. Use letters, digits, '.', '_', '-', "
            "an optional 'namespace/' and an optional ':tag'. It is a name in "
            "Ollama's own store, not a file path — nothing is written to disk."
        )
    return cleaned


async def list_embedding_models() -> list[EmbeddingModelInfo]:
    """Every locally installed model that can actually embed.

    Asked, not guessed. The earlier heuristic elsewhere in this app is "does the
    name contain 'embed'", which is fine for hiding them from a *chat* picker
    and wrong here: a model derived as `my_nomic` embeds and does not say so in
    its name, and a chat model called `embedder-9b` would say so and could not.
    `show()` reports capabilities, so that is what is read.
    """
    client = get_client()
    try:
        listed = await client.list()
    except Exception as exc:
        raise _unavailable(exc) from exc

    out: list[EmbeddingModelInfo] = []
    for entry in listed.models:
        if not entry.model:
            continue
        try:
            shown = await client.show(entry.model)
        except Exception:
            # One unreadable model must not empty the whole list.
            logger.info("could not read capabilities for %s", entry.model)
            continue
        if "embedding" not in (shown.capabilities or ()):
            continue
        out.append(
            EmbeddingModelInfo(
                name=entry.model,
                size=int(entry.size) if entry.size is not None else None,
                family=entry.details.family if entry.details else None,
                weights=_weights_digest(shown.modelfile),
            )
        )
    return sorted(out, key=lambda m: m.name)


_BLOB = re.compile(r"sha256[-:]([0-9a-f]{12,64})")


def _weights_digest(modelfile: str | None) -> str | None:
    """The short digest of the weights a model actually points at.

    This replaced a `derived` flag that could not work, and the reason it could
    not is worth keeping — it is the strongest evidence for what `derive_model`
    claims.

    A model's `FROM` line, as `show()` reports it, is always a **blob path**,
    never a model name. So "was this derived from another local model" is simply
    not answerable from here. Measured 2026-08-01: a model created with
    `from_='nomic-embed-text'` reports

        FROM /usr/share/ollama/.ollama/models/blobs/sha256-970aa74c...

    which is *byte for byte the path `nomic-embed-text` itself reports*. That is
    not a limitation of the API — it is Ollama telling us the two names share
    one set of weights, which is exactly why their vectors came back identical.

    So the digest is reported instead of a flag. Two models showing the same one
    are the same weights, which is the honest version of what a "custom model"
    badge would have implied and the opposite of what it would have said.
    """
    if not modelfile:
        return None
    match = _BLOB.search(modelfile)
    return match.group(1)[:12] if match else None


async def embed_texts(
    *, model: str, texts: Sequence[str], full: bool = False
) -> EmbedResult:
    """Run `ollama.embed(model=..., input=[...])` and report what came back.

    This is the ask, directly: one call, a list in, vectors out. Batched by
    Ollama itself, so two inputs cost one round trip rather than two.

    By default the vectors come back **truncated to a preview** plus their
    magnitude and dimension. That is not squeamishness about size — it is that a
    768-float array is not a thing anyone reads, and a route whose normal
    response is 15 KB of numbers teaches its caller to ignore the response.
    `full=True` returns everything, for a caller that means it.
    """
    checked = _check_model_name(model)
    cleaned = [t for t in texts if t.strip()]
    if not cleaned:
        raise EmbeddingRequestError("give at least one non-empty text to embed")
    if len(cleaned) > MAX_INPUTS:
        raise EmbeddingRequestError(
            f"{len(cleaned)} inputs is more than the limit of {MAX_INPUTS} per call"
        )
    for text in cleaned:
        if len(text) > MAX_INPUT_CHARS:
            raise EmbeddingRequestError(
                f"one input is {len(text)} characters, over the {MAX_INPUT_CHARS} limit"
            )

    try:
        response = await get_client().embed(model=checked, input=cleaned)
    except OllamaResponseError as exc:
        if "not found" in str(exc).lower():
            raise ProviderUnavailableError(
                NAME,
                f"model {checked!r} is not installed. Run:  ollama pull {checked}",
            ) from exc
        raise _unavailable(exc) from exc
    except Exception as exc:
        raise _unavailable(exc) from exc

    vectors = [list(v) for v in response.embeddings]
    if not vectors:
        raise ProviderUnavailableError(
            NAME, f"model {checked!r} returned no vectors — can it embed?"
        )

    return EmbedResult(
        model=checked,
        count=len(vectors),
        dimensions=len(vectors[0]),
        vectors=[
            EmbeddingVector(
                text=text,
                # Truncated for a human, or whole for a caller that asked.
                preview=vector if full else vector[:PREVIEW_COMPONENTS],
                truncated=not full and len(vector) > PREVIEW_COMPONENTS,
                magnitude=sum(component * component for component in vector) ** 0.5,
            )
            for text, vector in zip(cleaned, vectors, strict=True)
        ],
    )


async def derive_model(
    *, name: str, base: str, note: str | None = None
) -> DerivedModelResult:
    """Create a named model from a base one — a pin, not a personality.

    See the module docstring for the measurement. In short: `note` becomes a
    `SYSTEM` line, it is stored, and it changes no vector at all, because an
    embedding model has no generation path to read it. What the derived name
    *does* buy is stability — `EMBEDDING_MODEL` can point at a tag this machine
    owns rather than one a registry may move under an index that cannot survive
    the change.

    The reply says both things plainly rather than leaving the UI to imply a
    custom model behaves differently.
    """
    checked = _check_model_name(name)
    checked_base = _check_model_name(base)

    client = get_client()
    try:
        shown = await client.show(checked_base)
    except Exception as exc:
        raise _unavailable(exc) from exc

    capabilities = list(shown.capabilities or ())
    embeds = "embedding" in capabilities

    try:
        await client.create(model=checked, from_=checked_base, system=note or None)
    except Exception as exc:
        raise _unavailable(exc) from exc

    # The capability cache in the chat provider is keyed by model name, and this
    # tag now points somewhere else.
    forget_model(checked)

    return DerivedModelResult(
        name=checked,
        base=checked_base,
        capabilities=capabilities,
        note=note,
        # The honest part, and the reason this field exists rather than a
        # cheerful success message.
        note_affects_vectors=False,
        vectors_identical_to_base=embeds,
        summary=(
            (
                f"{checked} is now a name you own for the exact weights "
                f"{checked_base} has today. Its vectors are identical to the "
                "base model's — a note is stored but an embedding model has no "
                "generation step to read it. What this buys is a pin: point "
                "EMBEDDING_MODEL at it and re-pulling the base cannot silently "
                "change the numbers under your index."
            )
            if embeds
            else (
                f"{checked} is derived from {checked_base}, which is not an "
                "embedding model. A note here does reach generation, but this "
                "app cannot embed with it."
            )
        ),
        modelfile=build_modelfile(name=checked, base=checked_base, note=note),
    )


def build_modelfile(*, name: str, base: str, note: str | None = None) -> str:
    """The downloadable artifact — a few hundred bytes that rebuild the model.

    This is what the sketch's `ollama.copy(...)` into `web/public/` was reaching
    for, in the form that works. A GGUF is 274 MB and `web/public/` goes into
    both git and the Docker image; a Modelfile is text, and any Ollama anywhere
    turns it back into the real model:

        ollama create my_nomic -f Modelfile

    It carries the pin's *intent*, which the blob would not: which base, and
    what the name was for.
    """
    lines = [
        f"# {name} — created by mcp-py",
        "#",
        "# A pinned name for a base embedding model. Rebuild with:",
        f"#     ollama create {name} -f Modelfile",
        "#",
        "# The SYSTEM line below is a note, not a behaviour: an embedding model",
        "# has no generation step, so it changes no vector. Measured, not assumed.",
        "",
        f"FROM {base}",
    ]
    if note:
        # Escaped so a note containing a quote cannot break the file it lands in.
        cleaned = note.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'SYSTEM "{cleaned}"')
    return "\n".join(lines) + "\n"


def _unavailable(exc: Exception) -> ProviderUnavailableError:
    """Turn a client failure into the 503 the rest of the app speaks.

    Deliberately not reusing the provider module's private helper: this is a
    different audience. There the message is about generation being unavailable;
    here it is about a route the user pressed a button on.
    """
    if isinstance(exc, ProviderUnavailableError):
        return exc
    if isinstance(exc, httpx.ConnectError):
        return ProviderUnavailableError(
            NAME,
            f"cannot reach the Ollama server at {settings.OLLAMA_HOST}. "
            "Is `ollama serve` running?",
        )
    if isinstance(exc, httpx.TimeoutException):
        return ProviderUnavailableError(
            NAME, f"Ollama timed out after {settings.OLLAMA_TIMEOUT_SECONDS}s"
        )
    return ProviderUnavailableError(NAME, str(exc))
