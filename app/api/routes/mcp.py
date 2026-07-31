"""MCP as an internal API.

Two routes that expose this app's own MCP server over HTTP, so the frontend —
and you, with `curl` — can see the tool catalogue a model would be given, and
invoke a tool by hand.

Both go through `app.mcp.client`, meaning a real protocol session rather than a
direct function call. The point is that this surface cannot drift from what an
agent actually sees: if `tools/list` would show a tool, so does `GET
/mcp/tools`, with the same description text and the same JSON Schema.

The caller is the bearer token and nothing else. `MCPCallRequest` has no owner
field by construction — see `app/mcp/context.py` for why that is the whole
security design of this layer.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.mcp import client as mcp_client
from app.mcp.server import server
from app.models import MCPCallRequest, MCPCallResult, MCPToolInfo, MCPToolsPublic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/tools", response_model=MCPToolsPublic)
async def list_tools(
    session: SessionDep, current_user: CurrentUser
) -> MCPToolsPublic:
    """The tool catalogue, fetched over the protocol.

    Read-only and identical for every user — what differs per user is what the
    tools *return*, never which tools exist.
    """
    tools = await mcp_client.list_tools(
        session=session, owner_id=current_user.id
    )
    return MCPToolsPublic(
        server=server.name,
        instructions=server.instructions,
        tools=[
            MCPToolInfo(
                name=tool.name,
                title=tool.title,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in tools
        ],
        count=len(tools),
    )


@router.post("/call", response_model=MCPCallResult)
async def call_tool(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: MCPCallRequest,
) -> MCPCallResult:
    """Invoke one tool as the signed-in user.

    A tool that runs and fails returns 200 with `ok: false` — that is a result,
    and the trace panel shows it as one. Only an unknown tool name is a 404,
    because that is the caller getting it wrong rather than the tool.
    """
    try:
        invocation = await mcp_client.call_tool(
            session=session,
            owner_id=current_user.id,
            name=body.name,
            arguments=body.arguments,
        )
    except mcp_client.UnknownToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    if not invocation.ok:
        logger.info("tool %s returned an error: %s", body.name, invocation.preview)

    return MCPCallResult(
        name=invocation.name,
        arguments=invocation.arguments,
        ok=invocation.ok,
        text=invocation.text,
        structured=invocation.structured,
        duration_ms=invocation.duration_ms,
    )
