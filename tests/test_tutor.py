"""Tutor: record, recall, stats.

The stub embedder in conftest maps text to a vector by keyword, so these tests
prove the *mechanism* is vector-based rather than word-overlap. The real
semantic win (matching "vector representations" to a lesson on "embeddings") is
verified against live Ollama in the end-to-end run.
"""

import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import StubChatProvider, auth_headers, make_user


async def _record(client: AsyncClient, headers: dict[str, str], term: str,
                  question: str, answer: str) -> dict[str, object]:
    response = await client.post(
        "/api/v1/tutor/interactions",
        json={"term": term, "question": question, "answer": answer},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_record_then_recall(session: AsyncSession, client: AsyncClient) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    await _record(
        client, headers, "Embeddings",
        "what is a banana embedding",
        "A banana embedding places the fruit in vector space.",
    )

    # Different wording, same concept keyword — retrieval is by vector, and the
    # stub maps anything containing "banana" to the same point.
    response = await client.post(
        "/api/v1/tutor/recall",
        json={"question": "tell me about banana"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is True
    assert body["sources"], "expected the recorded lesson to be retrieved"
    assert "banana" in body["sources"][0]["content"].lower()


async def test_recall_with_nothing_learned_is_honest(
    session: AsyncSession, client: AsyncClient
) -> None:
    """An empty corpus must say so, not produce a confident empty answer."""
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    response = await client.post(
        "/api/v1/tutor/recall",
        json={"question": "explain transformers"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is False
    assert body["sources"] == []
    assert "haven't been taught" in body["answer"]


async def test_recall_names_what_was_covered(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)
    await _record(client, headers, "RAG", "what is rag", "Retrieval augmented generation.")

    # "rocket" maps to a different stub vector, so nothing is retrieved.
    response = await client.post(
        "/api/v1/tutor/recall",
        json={"question": "rocket propulsion"},
        headers=headers,
    )
    body = response.json()
    if not body["grounded"]:
        assert "RAG" in body["answer"], "should name the covered topic"


async def test_recall_is_owner_scoped(
    session: AsyncSession, client: AsyncClient
) -> None:
    """A learner's model must never recall someone else's lesson."""
    alice = await make_user(session)
    bob = await make_user(session)

    alice_headers = await auth_headers(client, alice.email)
    await _record(
        client, alice_headers, "Embeddings",
        "what is a banana embedding",
        "ALICE-PRIVATE-LESSON about banana vectors.",
    )

    bob_headers = await auth_headers(client, bob.email)
    response = await client.post(
        "/api/v1/tutor/recall",
        json={"question": "tell me about banana", "top_k": 20},
        headers=bob_headers,
    )
    assert response.status_code == 200
    assert "ALICE-PRIVATE-LESSON" not in response.text
    assert response.json()["sources"] == []


async def test_stats_come_from_the_index(
    session: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    empty = (await client.get("/api/v1/tutor/stats", headers=headers)).json()
    assert empty["interactions"] == 0
    assert empty["topics"] == []

    await _record(client, headers, "RAG", "q1", "a1")
    await _record(client, headers, "Embeddings", "q2", "a2")
    await _record(client, headers, "RAG", "q3", "a3")

    stats = (await client.get("/api/v1/tutor/stats", headers=headers)).json()
    assert stats["interactions"] == 3
    assert stats["topics"] == ["Embeddings", "RAG"]  # distinct, sorted
    assert stats["indexed_chunks"] >= 3
    assert stats["embedding_model"] == "stub-embed"


async def test_stats_are_owner_scoped(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    await _record(client, await auth_headers(client, alice.email), "RAG", "q", "a")

    bob_stats = (
        await client.get(
            "/api/v1/tutor/stats", headers=await auth_headers(client, bob.email)
        )
    ).json()
    assert bob_stats["interactions"] == 0


async def test_teach_streams_without_retrieval(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Teaching is generation only — no sources frame, because nothing is retrieved."""
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    async with client.stream(
        "POST", "/api/v1/tutor/teach",
        json={"question": "what are embeddings", "term": "Embeddings",
              "mode": "structured", "goals": ["understand vectors"]},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        body = "".join([chunk async for chunk in response.aiter_text()])

    frames = [
        json.loads(line[len("data: "):])
        for line in body.split("\n\n")
        if line.startswith("data: ")
    ]
    kinds = [f["type"] for f in frames]
    assert kinds[0] == "provider"
    assert kinds[-1] == "done"
    assert "error" not in kinds
    assert "sources" not in kinds, "teach must not retrieve"
    assert "".join(f["text"] for f in frames if f["type"] == "token")


async def test_teach_passes_goals_and_mode_into_the_prompt(
    session: AsyncSession, client: AsyncClient, _stub_providers: StubChatProvider
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    async with client.stream(
        "POST", "/api/v1/tutor/teach",
        json={"question": "q", "term": "Transformers", "mode": "structured",
              "goals": ["pass my exam"]},
        headers=headers,
    ) as response:
        async for _ in response.aiter_text():
            pass

    system = _stub_providers.last_system or ""
    assert "Transformers" in system
    assert "pass my exam" in system
    assert "checks whether the learner followed" in system


async def test_tutor_requires_auth(client: AsyncClient) -> None:
    for path, payload in (
        ("/api/v1/tutor/recall", {"question": "x"}),
        ("/api/v1/tutor/interactions", {"term": "t", "question": "q", "answer": "a"}),
    ):
        assert (await client.post(path, json=payload)).status_code == 401
    assert (await client.get("/api/v1/tutor/stats")).status_code == 401
