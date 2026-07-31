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
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from app.core.config import settings
from app.models import ModelInfo
from app.services.providers.base import (
    AgentMessage,
    ProviderUnavailableError,
    TextDelta,
    ToolRequest,
    ToolSpec,
    TurnDone,
    TurnEvent,
)

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

NO_KEY_MESSAGE = (
    "Claude needs an Anthropic API key. Add your own in settings — your key is "
    "never stored, and your Claude usage is billed to your own Anthropic "
    "account. Or switch the provider to Ollama."
)

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    """The shared client, using this app's own key.

    Only reached when no user key was supplied *and* the app is willing to
    spend its own — see `settings.ALLOW_APP_KEY_FALLBACK`.
    """
    global _client
    if _client is None:
        if not settings.claude_available:
            raise ProviderUnavailableError(NAME, NO_KEY_MESSAGE)
        _client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _wrap(exc: Exception, *, caller_key: bool = False) -> ProviderUnavailableError:
    """Turn an Anthropic exception into a 503 the user can act on.

    `caller_key` changes who the message is addressed to. Telling a visitor
    that "ANTHROPIC_API_KEY is invalid" is doubly wrong when the bad key is
    theirs: it names a server-side variable they cannot see, and it implies the
    app is broken when the fix is entirely in their hands.
    """
    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderUnavailableError(
            NAME,
            "Anthropic rejected your API key — it may have been revoked. "
            "Add a new one in settings."
            if caller_key
            else "ANTHROPIC_API_KEY is invalid.",
        )
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderUnavailableError(
            NAME,
            "Your Anthropic account is rate limited — retry shortly."
            if caller_key
            else "rate limited — retry shortly.",
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderUnavailableError(NAME, "could not reach the Anthropic API.")
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderUnavailableError(NAME, f"API error {exc.status_code}.")
    return ProviderUnavailableError(NAME, str(exc))


class ClaudeChatProvider:
    """Claude, billed either to this app or to the caller.

    `api_key` is the caller's own. When supplied, a client is built for this
    request only and the app's key is never touched — which is what makes the
    usage land on *their* Anthropic invoice. When absent, the shared client is
    used, and that only works if the app has a key and is willing to spend it.

    Instances carrying a user key are per-request and short-lived. They are
    deliberately **not** cached: a cache keyed by anything would be a place
    where one user's credential could be handed to another, and the client
    object is cheap to build.
    """

    name = NAME

    def __init__(self, api_key: str | None = None) -> None:
        self.default_model = settings.CLAUDE_CHAT_MODEL
        self._api_key = (api_key or "").strip() or None

    @property
    def available(self) -> bool:
        return bool(self._api_key) or settings.claude_available

    @property
    def billed_to_caller(self) -> bool:
        """True when this request is spending the user's own key, not the app's."""
        return self._api_key is not None

    def _client(self) -> AsyncAnthropic:
        if self._api_key is None:
            return get_client()
        # Per request, never cached — see the class docstring.
        return AsyncAnthropic(api_key=self._api_key)

    async def list_models(self) -> list[ModelInfo]:
        return list(KNOWN_MODELS)

    async def complete(
        self, *, system: str, user: str, model: str | None = None
    ) -> str:
        client = self._client()
        try:
            response = await client.messages.create(
                model=model or self.default_model,
                max_tokens=settings.LLM_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": settings.CLAUDE_EFFORT},
            )
        except Exception as exc:
            raise _wrap(exc, caller_key=self.billed_to_caller) from exc

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
        client = self._client()
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
            raise _wrap(exc, caller_key=self.billed_to_caller) from exc

    # ──────────────────────── tool calling ────────────────────────

    async def stream_turn(
        self,
        *,
        system: str,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        model: str | None = None,
    ) -> AsyncIterator[TurnEvent]:
        """One turn of an agentic exchange. See `base.ToolCallingProvider`.

        `get_final_message()` after the stream drains is what carries the
        `tool_use` blocks — they do not arrive as text deltas, so a loop that
        only reads `text_stream` would see the model fall silent and conclude
        it had finished.
        """
        client = self._client()
        try:
            async with client.messages.stream(
                model=model or self.default_model,
                max_tokens=settings.LLM_MAX_TOKENS,
                system=system,
                # The SDK's TypedDicts describe the same JSON these dicts hold;
                # building them typed would mean importing a block type per
                # variant for no runtime difference.
                messages=_to_anthropic(messages),  # pyright: ignore[reportArgumentType]
                tools=[
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                    for tool in tools
                ],
                output_config={"effort": settings.CLAUDE_EFFORT},
            ) as stream:
                async for text in stream.text_stream:
                    yield TextDelta(text=text)
                final = await stream.get_final_message()
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise _wrap(exc, caller_key=self.billed_to_caller) from exc

        if final.stop_reason == "refusal":
            logger.warning("Claude refused a tool-calling turn")
            yield TurnDone(text=REFUSAL_MESSAGE, tool_requests=[], stop_reason="refusal")
            return

        yield TurnDone(
            text="".join(b.text for b in final.content if b.type == "text"),
            tool_requests=[
                ToolRequest(
                    id=block.id,
                    name=block.name,
                    # Every tool here declares an object schema, so `input` is
                    # always a mapping — copied rather than aliased so the
                    # agent cannot mutate the SDK's object.
                    input=dict(block.input),
                )
                for block in final.content
                if block.type == "tool_use"
            ],
            stop_reason=final.stop_reason,
        )


def _to_anthropic(messages: Sequence[AgentMessage]) -> list[dict[str, Any]]:
    """Neutral turns → Anthropic content blocks.

    Kept here, not in the agent loop, so the loop never learns one provider's
    wire format. Two shapes matter:

      assistant + tool_requests → text block(s) plus `tool_use` blocks
      user      + tool_results  → `tool_result` blocks, matched by id

    The ids must be echoed back exactly, or the API rejects the turn — that
    pairing is the whole protocol.
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        blocks: list[dict[str, Any]] = []

        if message.tool_results:
            blocks.extend(
                {
                    "type": "tool_result",
                    "tool_use_id": result.id,
                    "content": result.content,
                    **({"is_error": True} if not result.ok else {}),
                }
                for result in message.tool_results
            )

        if message.text:
            blocks.append({"type": "text", "text": message.text})

        blocks.extend(
            {
                "type": "tool_use",
                "id": request.id,
                "name": request.name,
                "input": request.input,
            }
            for request in message.tool_requests
        )

        if blocks:
            out.append({"role": message.role, "content": blocks})
    return out
