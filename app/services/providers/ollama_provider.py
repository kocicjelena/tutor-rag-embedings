"""Ollama provider — local embeddings and local generation.

API notes that cost real time if missed (verified against
`related/ollama-python`):

* `AsyncClient` defaults to **no timeout**. Always pass one.
* `embed()` is natively batched — `input` takes a list, one round trip.
* Streaming needs `await` *before* the `async for`:
      `async for part in await client.chat(..., stream=True)`
  because `chat()` returns a coroutine that resolves to the async iterator.
"""

import logging
from collections.abc import AsyncIterator, Sequence

import httpx
from ollama import AsyncClient
from ollama import ResponseError as OllamaResponseError

from app.core.config import settings
from app.models import ModelInfo
from app.services.providers.base import ProviderUnavailableError

logger = logging.getLogger(__name__)

NAME = "ollama"

_client: AsyncClient | None = None


def get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = AsyncClient(
            host=settings.OLLAMA_HOST, timeout=settings.OLLAMA_TIMEOUT_SECONDS
        )
    return _client


def _unavailable(exc: Exception) -> ProviderUnavailableError:
    if isinstance(exc, httpx.ConnectError):
        return ProviderUnavailableError(
            NAME,
            f"cannot reach the Ollama server at {settings.OLLAMA_HOST}. "
            "Is `ollama serve` running?",
        )
    if isinstance(exc, httpx.TimeoutException):
        return ProviderUnavailableError(
            NAME, f"timed out after {settings.OLLAMA_TIMEOUT_SECONDS}s"
        )
    return ProviderUnavailableError(NAME, str(exc))


async def _list_model_names() -> list[str]:
    response = await get_client().list()
    return [m.model for m in response.models if m.model]


# ──────────────────────────── Embeddings ────────────────────────────

class OllamaEmbeddingProvider:
    name = NAME

    def __init__(self) -> None:
        self.model = settings.EMBEDDING_MODEL
        self.dimensions = settings.EMBEDDING_DIMENSIONS

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = await get_client().embed(model=self.model, input=list(texts))
        except OllamaResponseError as exc:
            if "not found" in str(exc).lower():
                raise ProviderUnavailableError(
                    NAME,
                    f"embedding model {self.model!r} is not installed. "
                    f"Run:  ollama pull {self.model}",
                ) from exc
            raise _unavailable(exc) from exc
        except Exception as exc:
            raise _unavailable(exc) from exc

        vectors = [list(v) for v in response.embeddings]
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ProviderUnavailableError(
                    NAME,
                    f"model {self.model!r} returned {len(vector)}-dim vectors but "
                    f"EMBEDDING_DIMENSIONS is {self.dimensions}. The stored index "
                    "cannot mix dimensions — re-embed after changing the model.",
                )
        return vectors

    async def health(self) -> None:
        try:
            names = await _list_model_names()
        except Exception as exc:
            raise _unavailable(exc) from exc
        # Ollama reports models with an implicit ":latest" tag.
        installed = {n.split(":")[0] for n in names} | set(names)
        if self.model.split(":")[0] not in installed:
            raise ProviderUnavailableError(
                NAME,
                f"embedding model {self.model!r} is not installed. "
                f"Run:  ollama pull {self.model}",
            )


# ──────────────────────────── Chat ────────────────────────────

class OllamaChatProvider:
    name = NAME

    def __init__(self) -> None:
        self.default_model = settings.OLLAMA_CHAT_MODEL

    @property
    def available(self) -> bool:
        # Reachability is checked per call; nothing to configure up front.
        return True

    async def list_models(self) -> list[ModelInfo]:
        try:
            response = await get_client().list()
        except Exception as exc:
            raise _unavailable(exc) from exc
        models: list[ModelInfo] = []
        for m in response.models:
            if not m.model:
                continue
            # Embedding models cannot answer chat prompts — don't offer them.
            if "embed" in m.model.lower():
                continue
            models.append(
                ModelInfo(
                    name=m.model,
                    size=int(m.size) if m.size is not None else None,
                    family=m.details.family if m.details else None,
                )
            )
        return sorted(models, key=lambda x: x.name)

    async def complete(
        self, *, system: str, user: str, model: str | None = None
    ) -> str:
        try:
            response = await get_client().chat(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:
            raise _unavailable(exc) from exc
        return response.message.content or ""

    async def stream(
        self, *, system: str, user: str, model: str | None = None
    ) -> AsyncIterator[str]:
        try:
            # `await` first, THEN `async for` — chat() returns a coroutine
            # resolving to the iterator, not the iterator itself.
            iterator = await get_client().chat(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                stream=True,
            )
            async for part in iterator:
                fragment = part.message.content
                if fragment:
                    yield fragment
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise _unavailable(exc) from exc
