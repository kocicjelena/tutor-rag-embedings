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
4. **Owner scoping**, as everywhere else — now in two indexes rather than one.
5. **The vector is kept**, and goes to `vec_learning`. Jelena overruled dropping
   it: piece-to-piece similarity without re-embedding is what makes the
   embeddings worth having, and it is the raw material for a model of the
   learner's own. Point 1 is asserted from both sides because of it — no rows in
   `DocumentChunk`, and no vectors in `vec_chunks`.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.models import DocumentChunk, LearningEvent, LearningPiece
from app.services import learning_stream, vectors
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


# ──────────────── The vector: kept, and what it is for ────────────────
#
# Jelena overruled an earlier decision to compute `novelty` and drop the vector.
# These pin what keeping it bought — and, just as importantly, that it did not
# cost the property the whole design rests on: the search index is still never
# written to, which `test_the_search_index_is_untouched` above asserts from the
# row side and `test_the_two_indexes_stay_apart` asserts from the vector side.


async def test_the_vector_is_kept_not_discarded(session: AsyncSession) -> None:
    owner = await make_user(session)
    await _drain(session, owner.id, uuid.uuid4(), _pieces("a banana is a fruit"))

    assert await vectors.count_learning_for_owner(session, owner.id) == 1


async def test_the_two_indexes_stay_apart(session: AsyncSession) -> None:
    """Learning goes to `vec_learning`; `vec_chunks` does not move.

    The vector counterpart of the load-bearing test above. A pipeline that wrote
    a half-finished sentence into the search index would make it something a
    citation could point at, and nothing would fail — the count would simply be
    wrong and the results slightly worse forever.
    """
    owner = await make_user(session)
    before = await vectors.count_for_owner(session, owner.id)

    await _drain(session, owner.id, uuid.uuid4(), _pieces("rockets go up"))

    assert await vectors.count_for_owner(session, owner.id) == before
    assert await vectors.count_learning_for_owner(session, owner.id) == 1


async def test_state_reports_how_many_vectors_the_model_holds(
    session: AsyncSession
) -> None:
    """Across every session — the model is the whole of what was accumulated."""
    owner = await make_user(session)
    await _drain(session, owner.id, uuid.uuid4(), _pieces("one", "two"))
    await _drain(session, owner.id, uuid.uuid4(), _pieces("three"))

    state = await learning_stream.read_state(session, owner.id, uuid.uuid4())
    # No events in *this* session, but the model holds three vectors.
    assert state.events == 0
    assert state.vectors == 3


async def test_similar_finds_the_near_piece_and_ranks_it_first(
    session: AsyncSession
) -> None:
    """Piece-to-piece similarity, without re-embedding anything.

    The stub embedder maps "banana" and "rocket" to different axes, so the
    ranking here is a property of the index rather than of a real model's
    behaviour.
    """
    owner = await make_user(session)
    await _drain(
        session,
        owner.id,
        uuid.uuid4(),
        _pieces("a banana is a fruit", "rockets go up", "something else"),
    )

    found = await learning_stream.similar(
        session, owner.id, "tell me about a banana", top_k=3
    )
    assert found.searched == 3
    assert found.matches[0].text == "a banana is a fruit"
    # Ranked, not merely returned: distances ascend.
    assert [m.distance for m in found.matches] == sorted(
        m.distance for m in found.matches
    )


async def test_similar_is_scoped_to_one_owner(session: AsyncSession) -> None:
    """The tenant boundary, in the second index too.

    `search_learning` takes `owner_id` positionally for the same reason
    `search` does — this is one person's study material, and the index is where
    the scoping is enforced rather than a WHERE clause a caller must remember.
    """
    mine = await make_user(session)
    yours = await make_user(session)
    await _drain(session, yours.id, uuid.uuid4(), _pieces("a banana is a fruit"))

    found = await learning_stream.similar(session, mine.id, "banana", top_k=5)
    assert found.matches == []
    assert found.searched == 0


async def test_similar_can_narrow_to_one_stretch_of_learning(
    session: AsyncSession
) -> None:
    owner = await make_user(session)
    today = uuid.uuid4()
    await _drain(session, owner.id, today, _pieces("a banana is a fruit"))
    await _drain(session, owner.id, uuid.uuid4(), _pieces("a banana is yellow"))

    everything = await learning_stream.similar(session, owner.id, "banana", top_k=5)
    assert len(everything.matches) == 2

    just_today = await learning_stream.similar(
        session, owner.id, "banana", top_k=5, session_id=today
    )
    assert [m.text for m in just_today.matches] == ["a banana is a fruit"]


async def test_similar_on_an_empty_model_says_so(session: AsyncSession) -> None:
    """"Your model is empty" and "nothing matched" are different answers."""
    owner = await make_user(session)
    found = await learning_stream.similar(session, owner.id, "anything")
    assert found.matches == []
    assert found.searched == 0


async def test_similar_route_answers_from_the_learners_own_model(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    session_id = str(uuid.uuid4())

    await client.post(
        "/api/v1/tutor/learn",
        headers=headers,
        json={
            "session_id": session_id,
            "pieces": [{"seq": 0, "text": "a banana is a fruit"}],
        },
    )

    response = await client.post(
        "/api/v1/tutor/learn/similar",
        headers=headers,
        json={"text": "is a banana a fruit?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["searched"] == 1
    assert body["matches"][0]["text"] == "a banana is a fruit"


async def test_similar_route_requires_a_caller(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tutor/learn/similar", json={"text": "x"})
    assert response.status_code in (401, 403)


async def test_deleting_a_user_takes_their_vectors_with_them(
    session: AsyncSession
) -> None:
    """Nothing cascades into a vec0 table, so `delete_user` must do it by hand.

    Without this the vectors outlive the rows they describe: orphaned, in an
    index nothing will ever query them from, and counted by nothing that would
    notice. It is one person's study material, which is why it is worth the
    explicit call rather than being left to a periodic sweep that does not exist.
    """
    from app import crud

    owner = await make_user(session)
    await _drain(session, owner.id, uuid.uuid4(), _pieces("a banana is a fruit"))
    assert await vectors.count_learning_for_owner(session, owner.id) == 1

    await crud.delete_user(session=session, db_user=owner)

    assert await vectors.count_learning_for_owner(session, owner.id) == 0


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


async def test_state_route_rehydrates_a_session(
    client: AsyncClient, session: AsyncSession
) -> None:
    """After a reload the browser has no push to be answered — so it asks."""
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    session_id = str(uuid.uuid4())

    await client.post(
        "/api/v1/tutor/learn",
        json={
            "session_id": session_id,
            "term": "Vectors",
            "pieces": [{"seq": 0, "text": "one"}, {"seq": 1, "text": "two"}],
        },
        headers=headers,
    )

    response = await client.get(
        f"/api/v1/tutor/learn?session_id={session_id}", headers=headers
    )
    assert response.status_code == 200
    state = response.json()
    assert state["events"] == 2
    # What the client resumes from: last_seq + 1, so a reloaded page does not
    # rewrite rows that already exist.
    assert state["last_seq"] == 1
    assert state["terms"] == ["Vectors"]


async def test_an_unknown_session_reads_as_empty_not_an_error(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    response = await client.get(
        f"/api/v1/tutor/learn?session_id={uuid.uuid4()}", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["events"] == 0
    assert response.json()["last_seq"] is None


async def test_another_user_cannot_read_your_session(
    client: AsyncClient, session: AsyncSession
) -> None:
    owner = await make_user(session)
    owner_headers = await auth_headers(client, owner.email)
    session_id = str(uuid.uuid4())
    await client.post(
        "/api/v1/tutor/learn",
        json={"session_id": session_id, "pieces": [{"seq": 0, "text": "mine"}]},
        headers=owner_headers,
    )

    stranger = await make_user(session)
    stranger_headers = await auth_headers(client, stranger.email)
    response = await client.get(
        f"/api/v1/tutor/learn?session_id={session_id}", headers=stranger_headers
    )
    # Not 404: the session id is not a secret, and its emptiness is the honest
    # answer for someone who owns nothing in it.
    assert response.status_code == 200
    assert response.json()["events"] == 0
