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
from app.services.providers.claude_provider import NO_KEY_MESSAGE, ClaudeChatProvider
from app.services.providers.ollama_provider import (
    OllamaChatProvider,
    OllamaEmbeddingProvider,
)

def _build_embedder() -> EmbeddingProvider:
    """The configured embedding backend, constructed once at import.

    Constructing must not load or download anything — the sentence-transformers
    provider defers that to first use, so a misconfigured extra surfaces as a
    503 on the first embed rather than a hang at startup.
    """
    if settings.EMBEDDING_PROVIDER == "sentence_transformers":
        from app.services.providers.sentence_transformers_provider import (
            SentenceTransformersEmbeddingProvider,
        )

        return SentenceTransformersEmbeddingProvider()
    return OllamaEmbeddingProvider()


_embedder: EmbeddingProvider = _build_embedder()
_chat_providers: dict[str, ChatProvider] = {
    "ollama": OllamaChatProvider(),
    "claude": ClaudeChatProvider(),
}


def get_embedding_provider() -> EmbeddingProvider:
    """The single embedding provider.

    Configurable (`EMBEDDING_PROVIDER`) but **not selectable per request**:
    vectors from different models are not comparable, so a per-request choice
    would corrupt retrieval rather than offer one. Changing it in config is a
    deliberate act with a documented consequence — see
    `.claude/rules/VECTORS.md` and `app/scripts/reembed.py`.
    """
    return _embedder


def get_chat_provider(
    name: str | None = None, *, api_key: str | None = None
) -> ChatProvider:
    """The provider for this request.

    `api_key` is the **caller's own** key, when they have supplied one. Passing
    it builds a short-lived provider bound to that key, so the call is billed
    to them rather than to this app. Ignored by providers that need no
    credential — Ollama runs locally and has nothing to bill.

    The registry stays the only place routes look, so no route ever imports a
    concrete provider module (and no route ever has to know which providers
    cost money).
    """
    resolved = (name or settings.DEFAULT_CHAT_PROVIDER).lower()

    if resolved == "claude" and api_key:
        # Not cached, and not registered: this instance carries one user's
        # credential and must not outlive their request.
        return ClaudeChatProvider(api_key=api_key)

    provider = _chat_providers.get(resolved)
    if provider is None:
        raise ProviderUnavailableError(
            resolved,
            f"unknown provider. Available: {', '.join(sorted(_chat_providers))}.",
        )
    if not provider.available:
        # Two different audiences. "See .env.example" is right for the operator
        # running this locally and useless to a visitor on a public deploy, who
        # cannot see that file and whose actual fix is to add their own key.
        raise ProviderUnavailableError(
            resolved,
            NO_KEY_MESSAGE
            if resolved == "claude" and settings.USER_ANTHROPIC_KEYS
            else "not configured — see .env.example.",
        )
    return provider


def resolve_model(provider: ChatProvider, requested: str | None) -> str:
    return requested or provider.default_model


async def describe_providers(*, caller_has_key: bool = False) -> ProvidersPublic:
    """Live provider/model inventory for the frontend picker.

    `caller_has_key` is whether *this* user has supplied their own Anthropic
    key. It matters because availability is now per-user: on a public deploy
    the app holds no key of its own, yet Claude is perfectly usable by anyone
    who brought one. Reporting a flat "not configured" there would hide a
    working feature behind a message the visitor cannot act on.
    """
    infos: list[ProviderInfo] = []
    for name, provider in sorted(_chat_providers.items()):
        models: list[ModelInfo] = []
        detail: str | None = None
        available = provider.available or (name == "claude" and caller_has_key)
        if available:
            try:
                models = await provider.list_models()
            except ProviderUnavailableError as exc:
                available = False
                detail = exc.detail
        elif name == "claude" and settings.USER_ANTHROPIC_KEYS:
            # Offerable, but only once they add a key — say which, and say the
            # thing that makes it worth doing.
            detail = (
                "Add your own Anthropic API key to use Claude. It is never "
                "stored, and your usage is billed to your own account."
            )
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
