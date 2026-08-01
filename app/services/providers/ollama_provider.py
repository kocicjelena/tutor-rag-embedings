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
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from ollama import AsyncClient
from ollama import ResponseError as OllamaResponseError

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

NAME = "ollama"

# The capability string Ollama reports for a model that can call tools.
TOOLS_CAPABILITY = "tools"

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

    # ──────────────────────── tool calling ────────────────────────

    async def supports_tools(self, model: str) -> bool:
        """Ask Ollama whether this model can call tools.

        Measured, not assumed. Ollama serves whatever is pulled, and on this
        machine that is thirty models of which only some do tool use — so a
        provider-level "yes" would be a lie for most of them, and the failure it
        produces is the bad kind: the model ignores the tools it was handed,
        writes a plausible answer from its own knowledge, and the trace panel
        stays empty with nothing saying why.

        `show()` reports a `capabilities` list, which is the model's own answer
        rather than ours. Cached because it is a fact about a file on disk, and
        `forget_model` clears an entry when this app itself replaces a tag.

        Unreachable Ollama is `False`, not an exception: the caller is deciding
        whether to *offer* the agent, and "cannot confirm" and "cannot do it"
        lead to the same honest answer. The real outage surfaces on the next
        call, with a message about the server rather than about tools.
        """
        name = model or self.default_model
        cached = _tool_capable.get(name)
        if cached is not None:
            return cached

        try:
            info = await get_client().show(name)
        except Exception as exc:
            logger.info("could not read capabilities for %s: %s", name, exc)
            return False

        capable = TOOLS_CAPABILITY in (info.capabilities or ())
        _tool_capable[name] = capable
        return capable

    async def stream_turn(
        self,
        *,
        system: str,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        model: str | None = None,
    ) -> AsyncIterator[TurnEvent]:
        """One turn of an agentic exchange. See `base.ToolCallingProvider`.

        Two differences from Claude's, both in the translation rather than in
        the shape — which is the point of the neutral types, and why the agent
        loop needed no edit to gain a second tool-calling provider.

        **Ollama's tool calls carry no id.** Anthropic pairs a `tool_result`
        to its `tool_use` by id and rejects a turn where they do not match;
        Ollama pairs by *name* and position. The neutral `ToolRequest` has an
        id because the SSE trace needs one — the browser has to match a
        `tool_result` frame to the `tool_call` it answers — so one is minted
        here and mapped back to a name in `_to_ollama`.

        **Tool calls arrive inside the stream, not after it.** Anthropic's
        `tool_use` blocks are only on the final message, so Claude's
        implementation drains the text and then reads `get_final_message()`.
        Ollama puts them on whichever chunk carries them, so they are collected
        as the parts go by.
        """
        chosen = model or self.default_model
        text_parts: list[str] = []
        requests: list[ToolRequest] = []
        stop_reason: str | None = None

        try:
            iterator = await get_client().chat(
                model=chosen,
                messages=_to_ollama(system, messages),
                tools=[_to_ollama_tool(tool) for tool in tools],
                stream=True,
            )
            async for part in iterator:
                fragment = part.message.content
                if fragment:
                    text_parts.append(fragment)
                    yield TextDelta(text=fragment)

                for call in part.message.tool_calls or ():
                    requests.append(
                        ToolRequest(
                            id=f"ollama_{uuid.uuid4().hex[:12]}",
                            name=call.function.name,
                            # Already a mapping — Ollama parses the arguments
                            # server-side, so unlike a raw function-calling API
                            # there is no JSON string to decode here. Copied so
                            # the agent cannot mutate the SDK's object.
                            input=dict(call.function.arguments),
                        )
                    )

                if part.done:
                    stop_reason = part.done_reason
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise _unavailable(exc) from exc

        yield TurnDone(
            text="".join(text_parts),
            tool_requests=requests,
            stop_reason=stop_reason,
        )


def forget_model(name: str) -> None:
    """Drop a cached capability answer, because the tag now points elsewhere.

    Called when this app creates or replaces a model (`POST /embeddings/models`).
    Without it, deriving a model over an existing tag would keep answering from
    the capabilities of the thing that used to be there.
    """
    _tool_capable.pop(name, None)


_tool_capable: dict[str, bool] = {}


def _to_ollama_tool(tool: ToolSpec) -> dict[str, Any]:
    """One neutral ToolSpec as Ollama's function-tool shape."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _to_ollama(system: str, messages: Sequence[AgentMessage]) -> list[dict[str, Any]]:
    """Neutral turns → Ollama's message list.

    Kept here, not in the agent loop, so the loop never learns a provider's wire
    format — the same division as `claude_provider._to_anthropic`.

    Three shapes:

        system                    → a leading system message
        assistant + tool_requests → one message with `tool_calls`
        user      + tool_results  → one `role: "tool"` message *per result*

    That last one is why the id→name map exists. Ollama identifies a result by
    `tool_name`, and the neutral `ToolOutcome` carries only the id the trace
    needs — so the names are recovered from the assistant turn that asked for
    them. Every id in a result was minted by `stream_turn` on a previous turn,
    so the lookup cannot miss unless the loop reorders messages, which it does
    not.
    """
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    names: dict[str, str] = {}

    for message in messages:
        for request in message.tool_requests:
            names[request.id] = request.name

        if message.tool_results:
            out.extend(
                {
                    "role": "tool",
                    "tool_name": names.get(result.id, "unknown"),
                    "content": result.content,
                }
                for result in message.tool_results
            )
            continue

        if message.tool_requests:
            out.append(
                {
                    "role": "assistant",
                    # Ollama wants the key present even when the model said
                    # nothing before calling a tool.
                    "content": message.text or "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": request.name,
                                "arguments": request.input,
                            }
                        }
                        for request in message.tool_requests
                    ],
                }
            )
            continue

        if message.text:
            out.append({"role": message.role, "content": message.text})

    return out
