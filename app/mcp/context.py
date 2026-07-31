"""Who a tool is acting for — the one thing a tool must never be *told*.

A tool's arguments are chosen by the **model**, not by the application. Every
parameter in a tool signature is therefore untrusted input, however
authoritative it looks. If `search_documents` took an `owner_id`, then any
prompt that talked the model into passing a different UUID would read another
learner's corpus, and no amount of prompt hardening would reliably stop it.

So `owner_id` is not a parameter of any tool in `app/mcp/tools.py`, and cannot
become one: it is read from this context variable, which only an authenticated
route can set. That makes the rule structural rather than a convention someone
has to remember — the same move as hard rule #3, where `vectors.search()` takes
`owner_id` as a required positional argument so no call shape can omit it.

**Ordering hazard.** `bind()` must be entered *before* the MCP server task is
spawned. anyio copies the current context when a task starts, so a binding made
afterwards is invisible inside the tool. `app.mcp.client.tool_session` is the
supported way to get this right; `tests/test_mcp.py` asserts it.
"""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


class ToolContextError(RuntimeError):
    """A tool ran with no caller bound.

    Always a bug in the calling code, never something a model can provoke — but
    it fails closed, which is the point: an unbound tool reads nothing at all
    rather than defaulting to some owner.
    """


@dataclass(frozen=True)
class ToolContext:
    """The authenticated caller, plus the session the tool should read through.

    **`owner_id` is `User.id` — the internal UUID, never the public handle.**
    Since 2026-07-30 this app has three identifiers and only one of them
    belongs here:

    | | what it is | where it belongs |
    |---|---|---|
    | `User.id` | random UUID, the primary key | `owner_id` everywhere: documents, `vec_chunks`, tools |
    | `public_id` | one-way HMAC of the email | URLs and links, nowhere else |
    | email | the login | authentication only |

    Putting `public_id` here would break every ownership check silently — it
    matches no row — and putting the email here would make the tenant boundary
    depend on a mutable field. The type is the guard: `uuid.UUID` will not
    accept the 26-character handle.
    """

    session: AsyncSession
    owner_id: uuid.UUID


_current: ContextVar[ToolContext | None] = ContextVar("mcp_tool_context", default=None)


@contextmanager
def bind(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> Generator[ToolContext, None, None]:
    """Bind the caller for the duration of the block.

    The token-based reset is not decoration: MCP sessions nest during tests and
    could nest in an agent loop, and resetting to the *previous* value rather
    than to `None` keeps an inner block from silently unbinding an outer one.
    """
    context = ToolContext(session=session, owner_id=owner_id)
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


def require() -> ToolContext:
    """The bound caller, or raise. Every tool body starts with this."""
    context = _current.get()
    if context is None:
        raise ToolContextError(
            "No caller is bound. MCP tools must run inside "
            "app.mcp.context.bind(), which app.mcp.client.tool_session() does."
        )
    return context
