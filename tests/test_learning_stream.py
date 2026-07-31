"""The live channel: pieces of learning embedded as they arrive.

What these pin, in order of how badly a regression would hurt:

1. **The search index is never written to.** The whole design rests on
   embedding-for-the-model being separate from indexing. A live pipeline that
   quietly added rows to `vec_chunks` would make every document count wrong and
   every search noisier, and nothing would fail.
2. **A retry is a no-op.** The channel is many small requests, so duplicates are
   normal rather than exceptional.
3. **Nothing is committed when the embedder fails**, so a failure leaves the
   model as it was rather than half-updated.
4. **Owner scoping**, as everywhere else.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.models import DocumentChunk, LearningEvent, LearningPiece
from app.services import learning_stream
from tests.conftest import auth_headers, make_user


def _pieces(*texts: str, start: int = 0) -> list[LearningPiece]:
    return [LearningPiece(seq=start + i, text=t) for i, t in enumerate(texts)]


async def _drain(
    session: AsyncSession,
    owner_id: uuid.UUID,
    session_id: uuid.UUID,
    pieces: list[LearningPiece],
    **kwargs: object,
) -> int:
    sink = learning_stream.learning_sink(session, owner_id, session_id, **kwargs)  # type: ignore[arg-type]
    await anext(sink)
    written = 0
    for piece in pieces:
        written = await sink.asend(piece)
    await sink.aclose()
    return written


async def test_pieces_persist_with_the_embedding_model_named(
    session: AsyncSession
) -> None:
    owner = await make_user(session)
    session_id = uuid.uuid4()
    await _drain(
        session,
        owner.id,
        session_id,
        _pieces("a banana is a fruit", "rockets go up"),
        term="Fruit",
    )

    rows = (
        await session.execute(
            select(LearningEvent).where(LearningEvent.session_id == session_id)
        )
    ).scalars().all()

    assert [r.seq for r in rows] == [0, 1]
    assert {r.term for r in rows} == {"Fruit"}
    # Not a default: the row says which space its novelty was measured in, for
    # the same reason a document says what indexed it.
    assert {r.embedded_with for r in rows} == {"stub-embed"}


async def test_the_search_index_is_untouched(
    session: AsyncSession
) -> None:
    """The load-bearing test. Embedding here builds the model, not the index."""
    owner = await make_user(session)
    before = (
        await session.execute(select(func.count()).select_from(DocumentChunk))
    ).scalar_one()

    await _drain(
        session, owner.id, uuid.uuid4(), _pieces("something new entirely")
    )

    after = (
        await session.execute(select(func.count()).select_from(DocumentChunk))
    ).scalar_one()
    assert after == before


async def test_a_replayed_piece_is_skipped_not_duplicated(
    session: AsyncSession
) -> None:
    owner = await make_user(session)
    session_id = uuid.uuid4()
    await _drain(session, owner.id, session_id, _pieces("first", "second"))
    # The same two arrive again — a retried request, a reconnect, a reload.
    await _drain(
        session, owner.id, session_id, _pieces("first", "second", "third")
    )

    rows = (
        await session.execute(
            select(LearningEvent).where(LearningEvent.session_id == session_id)
        )
    ).scalars().all()
    assert [r.seq for r in rows] == [0, 1, 2]


async def test_blank_pieces_are_dropped(
    session: AsyncSession
) -> None:
    owner = await make_user(session)
    session_id = uuid.uuid4()
    await _drain(
        session, owner.id, session_id, _pieces("   ", "real content", "\n")
    )
    rows = (
        await session.execute(
            select(LearningEvent).where(LearningEvent.session_id == session_id)
        )
    ).scalars().all()
    assert [r.text for r in rows] == ["real content"]


async def test_novelty_is_none_on_an_empty_corpus(
    session: AsyncSession
) -> None:
    """With nothing to compare against, "how new is this" has no answer."""
    owner = await make_user(session)
    session_id = uuid.uuid4()
    await _drain(session, owner.id, session_id, _pieces("anything"))
    row = (
        await session.execute(
            select(LearningEvent).where(LearningEvent.session_id == session_id)
        )
    ).scalars().one()
    assert row.novelty is None


async def test_a_failing_embedder_commits_nothing(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await make_user(session)
    session_id = uuid.uuid4()

    class Broken:
        name = "broken"
        model = "broken"
        dimensions = 4

        async def embed(self, _texts: object) -> list[list[float]]:
            raise RuntimeError("ollama is down")

        async def health(self) -> None:
            return None

    monkeypatch.setattr(
        learning_stream, "get_embedding_provider", lambda: Broken()
    )

    with pytest.raises(RuntimeError):
        await _drain(
            session,
            owner.id,
            session_id,
            _pieces("one", "two", "three", "four"),
        )

    await session.rollback()
    count = (
        await session.execute(
            select(func.count())
            .select_from(LearningEvent)
            .where(LearningEvent.session_id == session_id)
        )
    ).scalar_one()
    assert count == 0


async def test_state_is_read_back_from_sqlite(
    session: AsyncSession
) -> None:
    owner = await make_user(session)
    session_id = uuid.uuid4()
    await _drain(
        session, owner.id, session_id, _pieces("one", "two"), term="Vectors"
    )

    state = await learning_stream.read_state(session, owner.id, session_id)
    assert state.events == 2
    assert state.last_seq == 1
    assert state.terms == ["Vectors"]
    assert state.embedded_with == "stub-embed"


async def test_state_is_scoped_to_the_owner(
    session: AsyncSession
) -> None:
    owner = await make_user(session)
    session_id = uuid.uuid4()
    await _drain(session, owner.id, session_id, _pieces("mine"))

    stranger = uuid.uuid4()
    state = await learning_stream.read_state(session, stranger, session_id)
    assert state.events == 0


async def test_route_returns_accepted_skipped_and_state(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    session_id = str(uuid.uuid4())
    body = {
        "session_id": session_id,
        "term": "Embeddings",
        "pieces": [{"seq": 0, "text": "a vector is a list of numbers"}],
    }

    first = await client.post(
        "/api/v1/tutor/learn", json=body, headers=headers
    )
    assert first.status_code == 200
    payload = first.json()
    assert [e["seq"] for e in payload["accepted"]] == [0]
    assert payload["skipped"] == []
    assert payload["state"]["events"] == 1

    # The same piece again: nothing new, and the state still reads 1.
    again = await client.post(
        "/api/v1/tutor/learn", json=body, headers=headers
    )
    assert again.status_code == 200
    repeat = again.json()
    assert repeat["accepted"] == []
    assert repeat["skipped"] == [0]
    assert repeat["state"]["events"] == 1


async def test_route_requires_a_caller(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tutor/learn",
        json={"session_id": str(uuid.uuid4()), "pieces": []},
    )
    assert response.status_code == 401
