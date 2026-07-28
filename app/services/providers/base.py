"""Provider protocols.

Two protocols, not one — and that asymmetry is deliberate.

**Anthropic exposes no embeddings endpoint.** So "the user picks the provider"
can only ever apply to *generation*. Embedding must be local and fixed: vectors
from different models are not comparable, so making the embedder switchable
per-request would silently corrupt the index rather than offer a choice.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from app.models import ModelInfo


class ProviderUnavailableError(RuntimeError):
    """Provider is not usable — missing credentials, or the server is down.

    Surfaced as HTTP 503, never as a stack trace.
    """

    def __init__(self, provider: str, detail: str) -> None:
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider} unavailable: {detail}")


class ChatMessage(Protocol):
    role: str
    content: str


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into vectors. Ollama only — see the module docstring."""

    name: str
    model: str
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch. Order of the result matches the order of `texts`."""
        ...

    async def health(self) -> None:
        """Raise ProviderUnavailableError if the provider cannot serve requests."""
        ...


@runtime_checkable
class ChatProvider(Protocol):
    """Generates answers. Selectable per request: Ollama or Claude."""

    name: str
    default_model: str

    @property
    def available(self) -> bool:
        """False when credentials are absent — checked before use."""
        ...

    async def list_models(self) -> list[ModelInfo]:
        ...

    async def complete(
        self, *, system: str, user: str, model: str | None = None
    ) -> str:
        ...

    def stream(
        self, *, system: str, user: str, model: str | None = None
    ) -> AsyncIterator[str]:
        """Yield answer fragments. Implementations are async generators."""
        ...
