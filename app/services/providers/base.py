"""Provider protocols.

Two protocols, not one — and that asymmetry is deliberate.

**Anthropic exposes no embeddings endpoint.** So "the user picks the provider"
can only ever apply to *generation*. Embedding must be local and fixed: vectors
from different models are not comparable, so making the embedder switchable
per-request would silently corrupt the index rather than offer a choice.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

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


# ──────────────────────────── Tool calling ────────────────────────────
#
# A second, **optional** Protocol rather than three more methods on
# `ChatProvider`. Tool use is not universal — it depends on the model, not just
# the provider — so requiring every provider to implement it would fill the
# ones that cannot with stubs that raise.
#
# Both Ollama and Claude implement it now, which does *not* make the protocol
# redundant: it is what a third provider is measured against, and it is why
# adding Ollama tool calling in 2026-08 changed one file and touched neither the
# agent loop nor the route's shape. The per-model question moved into
# `supports_tools` at the same time — see its docstring.
#
# The types below are deliberately provider-neutral. Anthropic's content-block
# format and Ollama's differ, and translating is each provider's own job — the
# agent loop must not learn either shape, or adding a third provider means
# editing the loop.


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model. Mirrors what MCP's `tools/list` returns."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolRequest:
    """The model asking for a tool to be run."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolOutcome:
    """What running it produced, on its way back to the model."""

    id: str
    content: str
    ok: bool


@dataclass
class AgentMessage:
    """One turn of the conversation, in a shape no provider owns."""

    role: Literal["user", "assistant"]
    text: str | None = None
    # Set on an assistant turn where the model asked for tools.
    tool_requests: list[ToolRequest] = field(default_factory=list)
    # Set on the user turn that answers those requests.
    tool_results: list[ToolOutcome] = field(default_factory=list)


@dataclass(frozen=True)
class TextDelta:
    """A fragment of the model's prose, as it is written."""

    text: str


@dataclass(frozen=True)
class TurnDone:
    """The end of one turn: what it said, and what it wants run.

    `tool_requests` empty means the model is finished and this is the answer.
    """

    text: str
    tool_requests: list[ToolRequest]
    stop_reason: str | None = None


TurnEvent = TextDelta | TurnDone


@runtime_checkable
class ToolCallingProvider(Protocol):
    """A provider that can be handed tools and ask for them to be run."""

    name: str
    default_model: str

    async def supports_tools(self, model: str) -> bool:
        """Can *this model* call tools?

        Separate from implementing the protocol, and that separation is the
        whole reason this method exists. `isinstance(provider, ...)` is a
        structural check: it answers "has this provider written the code", which
        for Ollama is now yes for every model it serves — including
        `gemma3:1b`, which cannot call a tool and would fail obscurely halfway
        through a turn.

        So the protocol answers *can this provider*, and this answers *can this
        model*. A route must ask both, and `POST /query/agent` does, because a
        clean 422 naming a model that works is worth more than a stream that
        starts and then says nothing.
        """
        ...

    def stream_turn(
        self,
        *,
        system: str,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        model: str | None = None,
    ) -> AsyncIterator[TurnEvent]:
        """One turn. Yields `TextDelta`s, then exactly one `TurnDone` last.

        Streaming through tool turns rather than buffering them is what lets
        the UI show the model reasoning *before* it calls something, which is
        most of the value of a tool trace.
        """
        ...
