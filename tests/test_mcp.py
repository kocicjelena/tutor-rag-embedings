"""The MCP layer.

Two things are worth testing here and one of them is not obvious.

The obvious half: the protocol round trip works and the tools return what they
should. The other half is that **a tool's arguments are model-controlled**, so
the tenant boundary in `app/mcp/context.py` is load-bearing in a way the HTTP
routes' is not — a route's `owner_id` comes from a signed token, a tool's would
come from whatever the model was talked into passing. Several tests below guard
the *shape* of that boundary rather than a behaviour, because a regression here
would be silent.
"""

import inspect
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.mcp import client as mcp_client
from app.mcp import context as mcp_context
from app.mcp import tools
from app.models import DocumentChunk
from app.services import tutor_model, vectors
from tests.conftest import auth_headers, make_user

ALICE_SECRET = "ALICE-PRIVATE-LESSON-ON-BANANAS"
BOB_TEXT = "BOB-PUBLIC-NOTES-ON-BANANAS"

TOOL_NAMES = {"search_documents", "list_documents", "get_document", "tutor_stats"}


async def _seed_document(
    session: AsyncSession,
    owner_id: uuid.UUID,
    content: str,
    *,
    file_type: str = "text/plain",
) -> uuid.UUID:
    """One document, one chunk, one vector — all owners get the same vector.

    Identical vectors mean nothing but owner scoping can separate the results.
    """
    doc = await crud.create_document(
        session=session,
        owner_id=owner_id,
        title=content[:20],
        description="bananas",
        file_type=file_type,
    )
    chunk = DocumentChunk(
        document_id=doc.id,
        content=content,
        chunk_index=0,
        embedding_model="stub-embed",
    )
    await crud.replace_chunks(session=session, document_id=doc.id, chunks=[chunk])
    await vectors.upsert_chunks(
        session, owner_id, doc.id, [(chunk.id, [0.0, 1.0, 0.0, 0.0])]
    )
    doc.status = "ready"
    doc.chunk_count = 1
    session.add(doc)
    await session.commit()
    return doc.id


# ──────────────────── the protocol round trip ────────────────────

async def test_list_tools_goes_over_the_protocol(session: AsyncSession) -> None:
    alice = await make_user(session)

    descriptors = await mcp_client.list_tools(session=session, owner_id=alice.id)

    assert {d.name for d in descriptors} == TOOL_NAMES
    for descriptor in descriptors:
        # Description text is prompt text — a tool shipped without one is a tool
        # the model will guess about.
        assert descriptor.description, f"{descriptor.name} has no description"
        assert descriptor.input_schema["type"] == "object"


async def test_call_tool_returns_structured_content(session: AsyncSession) -> None:
    alice = await make_user(session)
    await _seed_document(session, alice.id, BOB_TEXT)

    invocation = await mcp_client.call_tool(
        session=session,
        owner_id=alice.id,
        name="search_documents",
        arguments={"query": "bananas"},
    )

    assert invocation.ok
    assert invocation.structured is not None
    assert invocation.structured["match_count"] == 1
    assert invocation.duration_ms >= 0


# ──────────────────── the tenant boundary ────────────────────

async def test_no_tool_accepts_an_owner_argument(session: AsyncSession) -> None:
    """The structural claim: `owner_id` is not addressable from tool input.

    Guards the invariant, not a behaviour. If someone adds an owner parameter
    to a tool "for convenience", every other isolation test here still passes
    while the boundary is gone.
    """
    alice = await make_user(session)
    descriptors = await mcp_client.list_tools(session=session, owner_id=alice.id)

    # `public_id` and `handle` are on this list for a reason. Since the derived
    # public id exists, a tool taking one looks harmless — it is "not the real
    # id", after all — but resolving a handle back to an owner is exactly the
    # cross-tenant hole the context variable closes.
    forbidden = (
        "owner",
        "owner_id",
        "user",
        "user_id",
        "email",
        "tenant",
        "public_id",
        "handle",
    )
    for descriptor in descriptors:
        properties = set(descriptor.input_schema.get("properties", {}))
        assert not properties & set(forbidden), (
            f"{descriptor.name} exposes a caller-identity argument: "
            f"{properties & set(forbidden)} — see app/mcp/context.py"
        )


async def test_tool_functions_take_no_session_or_owner() -> None:
    """The same claim one level down, where the schema is generated from.

    A tool that took a session or an owner would have them appear in its JSON
    Schema, which is the check above — but this one names the reason at the
    place a developer would be editing.
    """
    for name in TOOL_NAMES:
        function = getattr(tools, name)
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {"session", "owner_id", "ctx", "context"}, (
            f"{name} must read its caller from app.mcp.context, not a parameter"
        )


async def test_search_tool_is_owner_scoped(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    await _seed_document(session, alice.id, ALICE_SECRET)
    await _seed_document(session, bob.id, BOB_TEXT)

    invocation = await mcp_client.call_tool(
        session=session,
        owner_id=bob.id,
        name="search_documents",
        arguments={"query": "bananas", "top_k": 20},
    )

    assert invocation.ok
    assert ALICE_SECRET not in invocation.text
    assert invocation.structured is not None
    contents = [m["content"] for m in invocation.structured["matches"]]
    assert contents == [BOB_TEXT]


async def test_list_documents_tool_is_owner_scoped(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    await _seed_document(session, alice.id, ALICE_SECRET)
    await _seed_document(session, bob.id, BOB_TEXT)

    invocation = await mcp_client.call_tool(
        session=session, owner_id=bob.id, name="list_documents"
    )

    assert invocation.ok
    assert ALICE_SECRET not in invocation.text
    assert invocation.structured is not None
    assert invocation.structured["total"] == 1


async def test_get_document_refuses_another_owners_id(session: AsyncSession) -> None:
    """Naming someone else's document id must fail, and must not confirm it exists."""
    alice = await make_user(session)
    bob = await make_user(session)
    alice_doc = await _seed_document(session, alice.id, ALICE_SECRET)

    real = await mcp_client.call_tool(
        session=session,
        owner_id=bob.id,
        name="get_document",
        arguments={"document_id": str(alice_doc)},
    )
    invented = await mcp_client.call_tool(
        session=session,
        owner_id=bob.id,
        name="get_document",
        arguments={"document_id": str(uuid.uuid4())},
    )

    assert not real.ok
    assert not invented.ok
    assert ALICE_SECRET not in real.text
    # Identical wording apart from the id: the tool must not work as an
    # existence oracle for other users' document ids.
    assert real.text.replace(str(alice_doc), "ID") == invented.text.replace(
        str(uuid.UUID(invented.arguments["document_id"])), "ID"
    )


async def test_tools_fail_closed_with_no_caller_bound() -> None:
    """Unbound means "read nothing", never "read as somebody"."""
    with pytest.raises(mcp_context.ToolContextError):
        await tools.list_documents()


async def test_binding_reaches_the_server_task(session: AsyncSession) -> None:
    """The ordering hazard in `app/mcp/client`, asserted rather than commented.

    The MCP server runs in a task spawned inside `tool_session`, and anyio
    copies the context at spawn time. If a future refactor hoists the server
    out into a long-lived task, this test fails — which is the point, because
    the symptom in production would be every user reading the first user's
    corpus.
    """
    alice = await make_user(session)
    await _seed_document(session, alice.id, ALICE_SECRET)

    async with mcp_client.tool_session(session=session, owner_id=alice.id) as client:
        result = await client.call_tool("list_documents", {})

    assert not result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["total"] == 1


async def test_nested_bind_restores_the_outer_caller(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)

    with mcp_context.bind(session=session, owner_id=alice.id):
        with mcp_context.bind(session=session, owner_id=bob.id):
            assert mcp_context.require().owner_id == bob.id
        assert mcp_context.require().owner_id == alice.id


# ──────────────────── model-controlled input ────────────────────

async def test_top_k_is_clamped(session: AsyncSession) -> None:
    """`top_k` comes from the model, so an absurd value must not reach retrieval."""
    alice = await make_user(session)
    for index in range(3):
        await _seed_document(session, alice.id, f"{BOB_TEXT}-{index}")

    with mcp_context.bind(session=session, owner_id=alice.id):
        result = await tools.search_documents("bananas", top_k=100_000)

    assert result["match_count"] <= tools.MAX_TOP_K


async def test_malformed_document_id_is_a_tool_error(session: AsyncSession) -> None:
    """A bad argument comes back as a result the model can act on, not a crash."""
    alice = await make_user(session)

    invocation = await mcp_client.call_tool(
        session=session,
        owner_id=alice.id,
        name="get_document",
        arguments={"document_id": "not-a-uuid"},
    )

    assert not invocation.ok
    assert "list_documents" in invocation.text


async def test_unknown_tool_raises(session: AsyncSession) -> None:
    alice = await make_user(session)

    with pytest.raises(mcp_client.UnknownToolError) as excinfo:
        await mcp_client.call_tool(
            session=session, owner_id=alice.id, name="drop_everything"
        )

    # The message names what does exist — an agent that guessed a tool name can
    # correct itself from the error alone.
    assert "search_documents" in str(excinfo.value)


# ──────────────────── the HTTP surface ────────────────────

async def test_tools_route_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/mcp/tools")).status_code == 401
    assert (
        await client.post("/api/v1/mcp/call", json={"name": "list_documents"})
    ).status_code == 401


async def test_tools_route_lists_the_catalogue(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    response = await client.get("/api/v1/mcp/tools", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == len(TOOL_NAMES)
    assert {t["name"] for t in body["tools"]} == TOOL_NAMES
    assert body["server"] == "mcp-py"
    assert body["instructions"]


async def test_call_route_is_owner_scoped(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    await _seed_document(session, alice.id, ALICE_SECRET)
    await _seed_document(session, bob.id, BOB_TEXT)

    headers = await auth_headers(client, bob.email)
    response = await client.post(
        "/api/v1/mcp/call",
        json={"name": "search_documents", "arguments": {"query": "bananas"}},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert ALICE_SECRET not in response.text
    assert response.json()["ok"] is True


async def test_call_route_ignores_an_owner_in_the_body(
    session: AsyncSession, client: AsyncClient
) -> None:
    """A hostile body naming Alice must still read Bob's corpus.

    The same rule as `POST /tutor/model/import`: identity comes from the token,
    never from the payload. Here the extra fields are simply not part of the
    schema, so they are dropped rather than honoured.
    """
    alice = await make_user(session)
    bob = await make_user(session)
    await _seed_document(session, alice.id, ALICE_SECRET)
    await _seed_document(session, bob.id, BOB_TEXT)

    headers = await auth_headers(client, bob.email)
    response = await client.post(
        "/api/v1/mcp/call",
        json={
            "name": "list_documents",
            "arguments": {"owner_id": str(alice.id), "query": "bananas"},
            "owner_id": str(alice.id),
            "owner_email": alice.email,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert ALICE_SECRET not in response.text
    # `list_documents` takes no arguments at all, so the smuggled ones are
    # rejected by the tool's own schema rather than quietly ignored.
    assert body["ok"] is False or body["structured"]["total"] == 1


async def test_call_route_404s_on_unknown_tool(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    response = await client.post(
        "/api/v1/mcp/call", json={"name": "rm_rf"}, headers=headers
    )

    assert response.status_code == 404
    assert "search_documents" in response.json()["detail"]


async def test_failing_tool_is_200_with_ok_false(
    session: AsyncSession, client: AsyncClient
) -> None:
    """A tool that runs and fails is a result, not an HTTP error."""
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    response = await client.post(
        "/api/v1/mcp/call",
        json={"name": "get_document", "arguments": {"document_id": "nope"}},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is False


# ──────────────────── one implementation, two transports ────────────────────

async def test_stats_tool_agrees_with_the_stats_route(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The page and an agent must never report different progress."""
    alice = await make_user(session)
    await _seed_document(
        session, alice.id, ALICE_SECRET, file_type=tutor_model.TUTOR_FILE_TYPE
    )
    await _seed_document(session, alice.id, BOB_TEXT)

    headers = await auth_headers(client, alice.email)
    route = (await client.get("/api/v1/tutor/stats", headers=headers)).json()
    invocation = await mcp_client.call_tool(
        session=session, owner_id=alice.id, name="tutor_stats"
    )

    assert invocation.structured == route
    assert route["interactions"] == 1
    assert route["indexed_chunks"] == 2
