"""Claude provider — generation only.

Anthropic exposes no embeddings endpoint, so there is deliberately no
`ClaudeEmbeddingProvider`. Embedding stays local (Ollama).

Opus 5 API rules enforced here (see the `claude-api` skill before editing):

* `temperature`, `top_p`, `top_k`, and `budget_tokens` all return **400**.
  None of them appear below — do not add them.
* Thinking is on by default; `output_config.effort` is the cost/latency lever.
  We do NOT disable thinking: on Opus 5 that can make the model emit tool calls
  as plain text and leak `<thinking>` tags. Lower `effort` instead.
* Safety classifiers can decline a request: HTTP 200 with
  `stop_reason == "refusal"` and possibly empty `content`. Check the stop reason
  **before** reading content, or indexing `content[0]` raises.
"""

import logging
from collections.abc import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic

from app.core.config import settings
from app.models import ModelInfo
from app.services.providers.base import ProviderUnavailableError

logger = logging.getLogger(__name__)

NAME = "claude"

# Curated rather than fetched: the Models API lists every model the key can see,
# including ones inappropriate for short RAG answers.
KNOWN_MODELS: list[ModelInfo] = [
    ModelInfo(name="claude-opus-5", family="opus"),
    ModelInfo(name="claude-sonnet-5", family="sonnet"),
    ModelInfo(name="claude-haiku-4-5", family="haiku"),
]

REFUSAL_MESSAGE = (
    "The request was declined by Claude's safety classifiers. "
    "Try rephrasing, or switch the provider to Ollama."
)

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        if not settings.claude_available:
            raise ProviderUnavailableError(
                NAME,
                "ANTHROPIC_API_KEY is not set. Add it to .env, or use "
                "provider=ollama.",
            )
        _client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _wrap(exc: Exception) -> ProviderUnavailableError:
    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderUnavailableError(NAME, "ANTHROPIC_API_KEY is invalid.")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderUnavailableError(NAME, "rate limited — retry shortly.")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderUnavailableError(NAME, "could not reach the Anthropic API.")
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderUnavailableError(NAME, f"API error {exc.status_code}.")
    return ProviderUnavailableError(NAME, str(exc))


class ClaudeChatProvider:
    name = NAME

    def __init__(self) -> None:
        self.default_model = settings.CLAUDE_CHAT_MODEL

    @property
    def available(self) -> bool:
        return settings.claude_available

    async def list_models(self) -> list[ModelInfo]:
        return list(KNOWN_MODELS)

    async def complete(
        self, *, system: str, user: str, model: str | None = None
    ) -> str:
        client = get_client()
        try:
            response = await client.messages.create(
                model=model or self.default_model,
                max_tokens=settings.LLM_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": settings.CLAUDE_EFFORT},
            )
        except Exception as exc:
            raise _wrap(exc) from exc

        # Check the stop reason before touching content — a refusal can carry
        # an empty content list.
        if response.stop_reason == "refusal":
            logger.warning("Claude refused a request")
            return REFUSAL_MESSAGE
        return "".join(
            block.text for block in response.content if block.type == "text"
        )

    async def stream(
        self, *, system: str, user: str, model: str | None = None
    ) -> AsyncIterator[str]:
        client = get_client()
        try:
            async with client.messages.stream(
                model=model or self.default_model,
                max_tokens=settings.LLM_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": settings.CLAUDE_EFFORT},
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
                if final.stop_reason == "refusal":
                    logger.warning("Claude refused mid-stream")
                    yield f"\n\n{REFUSAL_MESSAGE}"
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise _wrap(exc) from exc
