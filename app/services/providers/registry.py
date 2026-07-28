"""Provider lookup.

Routes call `get_chat_provider(name)` and never import a concrete provider
module, so adding a provider means adding a file plus one registry entry.
"""

from app.core.config import settings
from app.models import ModelInfo, ProviderInfo, ProvidersPublic
from app.services.providers.base import (
    ChatProvider,
    EmbeddingProvider,
    ProviderUnavailableError,
)
from app.services.providers.claude_provider import ClaudeChatProvider
from app.services.providers.ollama_provider import (
    OllamaChatProvider,
    OllamaEmbeddingProvider,
)

_embedder: EmbeddingProvider = OllamaEmbeddingProvider()
_chat_providers: dict[str, ChatProvider] = {
    "ollama": OllamaChatProvider(),
    "claude": ClaudeChatProvider(),
}


def get_embedding_provider() -> EmbeddingProvider:
    """The single embedding provider.

    Not selectable per request: Anthropic has no embeddings API, and vectors
    from different models are not comparable, so switching mid-index would
    corrupt retrieval rather than offer a choice.
    """
    return _embedder


def get_chat_provider(name: str | None = None) -> ChatProvider:
    resolved = (name or settings.DEFAULT_CHAT_PROVIDER).lower()
    provider = _chat_providers.get(resolved)
    if provider is None:
        raise ProviderUnavailableError(
            resolved,
            f"unknown provider. Available: {', '.join(sorted(_chat_providers))}.",
        )
    if not provider.available:
        raise ProviderUnavailableError(
            resolved, "not configured — see .env.example."
        )
    return provider


def resolve_model(provider: ChatProvider, requested: str | None) -> str:
    return requested or provider.default_model


async def describe_providers() -> ProvidersPublic:
    """Live provider/model inventory for the frontend picker."""
    infos: list[ProviderInfo] = []
    for name, provider in sorted(_chat_providers.items()):
        models: list[ModelInfo] = []
        detail: str | None = None
        available = provider.available
        if available:
            try:
                models = await provider.list_models()
            except ProviderUnavailableError as exc:
                available = False
                detail = exc.detail
        else:
            detail = "not configured — see .env.example"
        infos.append(
            ProviderInfo(
                name=name,
                available=available,
                default_model=provider.default_model,
                models=models,
                detail=detail,
            )
        )
    return ProvidersPublic(
        data=infos,
        default_provider=settings.DEFAULT_CHAT_PROVIDER,
        embedding_model=_embedder.model,
        embedding_dimensions=_embedder.dimensions,
    )
