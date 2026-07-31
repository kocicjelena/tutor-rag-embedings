"""An MCP client, talking to this app's own server over a real session.

The shortcut would be to call `tools.search_documents(...)` directly and label
it "MCP". This does the actual thing: a client session, an `initialize`
handshake, `tools/list` and `tools/call` as JSON-RPC, content blocks coming
back. That costs microseconds over an in-memory stream pair and buys the only
property that matters — the client code here is transport-shaped, so pointing
it at somebody else's MCP server over stdio or Streamable HTTP later is a
change of connection, not a rewrite.

**Why a session per call.** The server runs as a task spawned inside
`tool_session`, and anyio copies the current context when a task starts. So the
caller must be bound *before* the server task exists, which is exactly what
this module guarantees by owning both steps. A single long-lived server task
would be spawned once, under whichever user happened to arrive first, and every
later tool call would silently read that user's corpus. The per-call session is
not a simplification to be optimised away later; it is the isolation.
"""

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp import context as mcp_context
from app.mcp.server import server

# How much tool output goes into the trace preview. The full result still
# reaches the model; this is only what a human sees in the UI panel.
PREVIEW_CHARS = 500


class UnknownToolError(LookupError):
    """No tool by that name is registered.

    Distinct from a tool that ran and failed: this one is the *caller's*
    mistake, so the route answers 404 and names what does exist.
    """

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        super().__init__(
            f"No MCP tool named {name!r}. Available: {', '.join(available)}."
        )


@dataclass(frozen=True)
class ToolDescriptor:
    """One entry from `tools/list`, as the catalogue the UI and the agent read."""

    name: str
    title: str | None
    description: str | None
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocation:
    """One `tools/call` round trip, shaped for both the model and the trace panel."""

    name: str
    arguments: dict[str, Any]
    ok: bool
    text: str
    structured: dict[str, Any] | None
    duration_ms: int

    @property
    def preview(self) -> str:
        if len(self.text) <= PREVIEW_CHARS:
            return self.text
        return self.text[:PREVIEW_CHARS] + "…"


@asynccontextmanager
async def tool_session(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> AsyncGenerator[ClientSession, None]:
    """An initialised MCP session with `owner_id` bound for its whole lifetime.

    Bind first, spawn second — see the module docstring. Nothing outside this
    module should open a session, because nothing else enforces that order.
    """
    with mcp_context.bind(session=session, owner_id=owner_id):
        async with create_connected_server_and_client_session(server) as client:
            yield client


async def list_tools(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> list[ToolDescriptor]:
    """The tool catalogue, fetched over the protocol rather than hard-coded.

    Asking the server means the list cannot drift from what is registered — a
    tool added in `server.py` shows up in the UI and in the agent's tool list
    with no second edit.
    """
    async with tool_session(session=session, owner_id=owner_id) as client:
        result = await client.list_tools()

    return [
        ToolDescriptor(
            name=tool.name,
            title=tool.title,
            description=tool.description,
            input_schema=tool.inputSchema,
        )
        for tool in result.tools
    ]


async def call_tool(
    *,
    session: AsyncSession,
    owner_id: uuid.UUID,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> ToolInvocation:
    """Invoke one tool and time it.

    A tool that raises comes back as `ok=False` with the message in `text`,
    not as an exception. That is MCP's own convention and it is the right one
    here: a failed tool call is something the *model* should see and recover
    from — by fixing its arguments, or by saying it could not look something up
    — not a 500 that ends the user's request.

    A tool that does not *exist* is different, and raises `UnknownToolError`.
    Checked in the same session as the call, so the two cannot disagree.

    **Nothing raises inside the session block.** A session is an anyio task
    group, and an exception crossing its `__aexit__` comes out wrapped in an
    `ExceptionGroup` — so `except UnknownToolError` in the route would not
    catch it, and the caller would get a 500 instead of a 404. Collect the
    outcome first, raise after the block. Same rule for any error added here
    later.
    """
    payload = arguments or {}
    started = time.perf_counter()
    result: CallToolResult | None = None

    async with tool_session(session=session, owner_id=owner_id) as client:
        catalogue = await client.list_tools()
        available = sorted(tool.name for tool in catalogue.tools)
        if name in available:
            result = await client.call_tool(name, payload)

    if result is None:
        raise UnknownToolError(name, available)

    return ToolInvocation(
        name=name,
        arguments=payload,
        ok=not result.isError,
        text=_text_of(result),
        structured=result.structuredContent,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _text_of(result: CallToolResult) -> str:
    """Flatten the content blocks a model would read.

    Non-text blocks (images, embedded resources) are named rather than
    dropped, so a trace never shows an empty result for a call that returned
    something this app simply does not render yet.
    """
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        else:
            parts.append(f"[{block.type} content]")
    return "\n".join(parts)
