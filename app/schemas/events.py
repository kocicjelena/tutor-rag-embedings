"""Typed streaming events.

One JSON object per SSE `data:` line, discriminated on `type`. The inherited
code emitted `f"data: {token}\\n\\n"`, which splits into multiple SSE events the
moment a token contains a newline, and used a bare `[DONE]` sentinel that a
legitimate answer could forge.

`tool_call` and `tool_result` have **no producers in Milestone 1**. They are
defined now, and rendered by the frontend now, so that adding MCP tool-calling
in Milestone 2 is a producer-side change only — no transport or UI reshaping.
See docs/jelena/future4.md.
"""

import json
import uuid
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

SSE_MEDIA_TYPE = "text/event-stream"


class _Event(BaseModel):
    def to_sse(self) -> str:
        """Render as a single SSE frame.

        `json.dumps` escapes newlines, so multi-line content stays on one line
        and cannot break the framing.
        """
        return f"data: {self.model_dump_json()}\n\n"


class ProviderEvent(_Event):
    """First frame: which provider/model is answering."""

    type: Literal["provider"] = "provider"
    provider: str
    model: str


class SourceChunk(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    score: float


class SourcesEvent(_Event):
    """Retrieved context, sent before generation so the UI can show it early."""

    type: Literal["sources"] = "sources"
    chunks: list[SourceChunk]


class ToolCallEvent(_Event):
    """Milestone 2. Emitted when an agent invokes a tool."""

    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(_Event):
    """Milestone 2. Result of a tool invocation."""

    type: Literal["tool_result"] = "tool_result"
    id: str
    ok: bool
    preview: str
    duration_ms: int | None = None


class TokenEvent(_Event):
    type: Literal["token"] = "token"
    text: str


class DoneEvent(_Event):
    type: Literal["done"] = "done"
    usage: dict[str, int] | None = None


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    message: str
    code: str | None = None


StreamEvent = Annotated[
    Union[
        ProviderEvent,
        SourcesEvent,
        ToolCallEvent,
        ToolResultEvent,
        TokenEvent,
        DoneEvent,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]


def parse_sse_line(line: str) -> dict[str, Any]:
    """Parse one `data: {...}` frame. Used by tests and the Next.js proxy contract."""
    if not line.startswith("data: "):
        raise ValueError(f"not an SSE data frame: {line!r}")
    parsed: dict[str, Any] = json.loads(line[len("data: ") :])
    return parsed
