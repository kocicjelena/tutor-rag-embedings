"""SSE framing regressions.

The inherited stream emitted `f"data: {token}\\n\\n"`, so any token containing a
newline split into multiple SSE events and corrupted the stream. The stub chat
provider in conftest deliberately yields fragments containing `\\n` and `\\n\\n`.
"""

import json
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.models import DocumentChunk
from app.schemas.events import TokenEvent, parse_sse_line
from app.services import vectors
from tests.conftest import auth_headers, make_user


async def _seed_doc(
    session: AsyncSession, owner_id: uuid.UUID, content: str
) -> None:
    doc = await crud.create_document(
        session=session, owner_id=owner_id, title="Doc",
        description=None, file_type="text/plain",
    )
    chunk = DocumentChunk(
        document_id=doc.id, content=content, chunk_index=0, embedding_model="stub-embed"
    )
    await crud.replace_chunks(session=session, document_id=doc.id, chunks=[chunk])
    await vectors.upsert_chunks(session, owner_id, doc.id, [(chunk.id, [1.0, 0.0, 0.0, 0.0])])
    await session.commit()


def test_newline_token_survives_framing() -> None:
    frame = TokenEvent(text="line one\nline two\n\nline three").to_sse()
    assert frame.endswith("\n\n")
    body = frame[: -len("\n\n")]
    assert body.count("\n") == 0, "newlines must be JSON-escaped, not literal"
    assert parse_sse_line(body)["text"] == "line one\nline two\n\nline three"


def test_frames_are_individually_parseable() -> None:
    for text in ["plain", "with\nnewline", 'quote " and \\ backslash', "emoji 🎉", ""]:
        parsed = parse_sse_line(TokenEvent(text=text).to_sse().strip())
        assert parsed["text"] == text
        assert parsed["type"] == "token"


async def test_stream_endpoint_emits_valid_json_frames(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    await _seed_doc(session, user.id, "The answer is 42.")
    headers = await auth_headers(client, user.email)

    async with client.stream(
        "POST", "/api/v1/query/stream",
        json={"question": "what is the answer"}, headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join([chunk async for chunk in response.aiter_text()])

    frames = [
        json.loads(line[len("data: "):])
        for line in body.split("\n\n")
        if line.startswith("data: ")
    ]
    assert frames, "no frames received"

    types = [f["type"] for f in frames]
    assert types[0] == "provider"
    assert "sources" in types
    assert types[-1] == "done"
    assert "error" not in types

    # Reassembling tokens must recover the newlines the stub emitted.
    answer = "".join(f["text"] for f in frames if f["type"] == "token")
    assert "line one\nline two\n\nline three" in answer


async def test_stream_reports_provider_and_model(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    await _seed_doc(session, user.id, "content")
    headers = await auth_headers(client, user.email)

    async with client.stream(
        "POST", "/api/v1/query/stream",
        json={"question": "q"}, headers=headers,
    ) as response:
        body = "".join([chunk async for chunk in response.aiter_text()])

    first = json.loads(body.split("\n\n")[0][len("data: "):])
    assert first["type"] == "provider"
    assert first["provider"] == "ollama"
    assert first["model"] == "stub-model"


async def test_stream_with_no_matching_documents(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    async with client.stream(
        "POST", "/api/v1/query/stream",
        json={"question": "nothing was ever uploaded"}, headers=headers,
    ) as response:
        body = "".join([chunk async for chunk in response.aiter_text()])

    frames = [
        json.loads(line[len("data: "):])
        for line in body.split("\n\n")
        if line.startswith("data: ")
    ]
    assert [f for f in frames if f["type"] == "sources"][0]["chunks"] == []
    assert frames[-1]["type"] == "done"


async def test_stream_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/v1/query/stream", json={"question": "hi"})
    assert response.status_code == 401


def test_tool_events_are_defined_for_milestone_2() -> None:
    """The frontend renders these from day one; M2 only adds producers."""
    from app.schemas.events import ToolCallEvent, ToolResultEvent

    call = parse_sse_line(
        ToolCallEvent(id="t1", name="search_documents", input={"q": "x"}).to_sse().strip()
    )
    assert call["type"] == "tool_call" and call["name"] == "search_documents"

    result = parse_sse_line(
        ToolResultEvent(id="t1", ok=True, preview="3 hits").to_sse().strip()
    )
    assert result["type"] == "tool_result" and result["ok"] is True
