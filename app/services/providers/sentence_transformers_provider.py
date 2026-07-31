"""A second embedding provider — sentence-transformers, in-process.

Optional. `sentence-transformers` pulls torch (~2 GB of wheels), so it lives
behind an extra and is imported lazily:

    uv sync --extra local-embed
    EMBEDDING_PROVIDER=sentence_transformers
    EMBEDDING_MODEL=all-MiniLM-L6-v2
    EMBEDDING_DIMENSIONS=384

## What this is for, honestly

Not better retrieval. `nomic-embed-text` at 768 dimensions is the stronger
model, and 384 is not an upgrade. What a second implementation buys is the
*demonstration* that the `EmbeddingProvider` Protocol is a real seam — and it
removes the Ollama requirement for embedding, which matters on a host with no
Ollama (Hugging Face Spaces).

## Two things it must get right

**It must not block the event loop.** `model.encode()` is synchronous CPU work
that can run for seconds. Called directly from an `async def`, it stalls every
other request in the process — which on a single-worker demo means the whole
app freezes while one upload embeds. `anyio.to_thread.run_sync` moves it off.

**Loading is lazy and once.** Constructing the provider must not download a
model: the registry builds every provider at import, and a cold start would
otherwise fetch weights before the app could answer `/health`.
"""

import logging
from collections.abc import Sequence
from typing import Any

import anyio.to_thread

from app.core.config import settings
from app.services.providers.base import ProviderUnavailableError

logger = logging.getLogger(__name__)

NAME = "sentence_transformers"

INSTALL_HINT = (
    "sentence-transformers is not installed. Run:  uv sync --extra local-embed"
)


class SentenceTransformersEmbeddingProvider:
    name = NAME

    def __init__(self) -> None:
        self.model = settings.EMBEDDING_MODEL
        self.dimensions = settings.EMBEDDING_DIMENSIONS
        self._encoder: Any | None = None

    def _load(self) -> Any:
        """Import and load on first use, never at construction.

        Blocking — the caller is responsible for running it in a worker thread.
        """
        if self._encoder is None:
            try:
                # Not a declared dependency — it lives behind the
                # `local-embed` extra, so it is absent on a default install.
                from sentence_transformers import (  # pyright: ignore[reportMissingImports]
                    SentenceTransformer,
                )
            except ImportError as exc:
                raise ProviderUnavailableError(NAME, INSTALL_HINT) from exc
            logger.info("loading sentence-transformers model %s", self.model)
            self._encoder = SentenceTransformer(self.model)
        return self._encoder

    def _encode(self, texts: list[str]) -> list[list[float]]:
        encoder = self._load()
        vectors = encoder.encode(texts, convert_to_numpy=True)
        return [[float(x) for x in row] for row in vectors]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = await anyio.to_thread.run_sync(self._encode, list(texts))
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(NAME, str(exc)) from exc

        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ProviderUnavailableError(
                    NAME,
                    f"model {self.model!r} returned {len(vector)}-dim vectors but "
                    f"EMBEDDING_DIMENSIONS is {self.dimensions}. Set them to match "
                    "— the index width is fixed when its table is created.",
                )
        return vectors

    async def health(self) -> None:
        # Loading is the health check: it is where a missing package or an
        # unknown model name shows up, and it is what the first embed would do
        # anyway.
        try:
            await anyio.to_thread.run_sync(self._load)
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                NAME, f"could not load model {self.model!r}: {exc}"
            ) from exc
