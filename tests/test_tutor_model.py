"""The model: export and import.

"The model" here is the learner's corpus — see `.claude/rules/PLAN.md` §7. These tests
pin the two properties that make the format worth having:

  * **it round-trips** — a file exported from one corpus imports into another
    and is retrievable afterwards, so a download is genuinely reloadable rather
    than a plausible-looking artifact nobody tries to load;
  * **ownership comes from the token, never the file** — the same rule the MCP
    tools will follow, and the one place a new feature could quietly undo the
    tenant isolation from Milestone 1.
"""

import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TUTOR_MODEL_FORMAT, TUTOR_MODEL_VERSION
from tests.conftest import auth_headers, make_user


async def _record(
    client: AsyncClient,
    headers: dict[str, str],
    term: str,
    question: str,
    answer: str,
    **extra: str,
) -> None:
    response = await client.post(
        "/api/v1/tutor/interactions",
        json={"term": term, "question": question, "answer": answer, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text


async def _export(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    response = await client.get("/api/v1/tutor/model/export", headers=headers)
    assert response.status_code == 200, response.text
    return json.loads(response.text)


async def test_export_then_import_round_trips(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    alice_headers = await auth_headers(client, alice.email)

    await _record(
        client, alice_headers, "Embeddings",
        "what is a banana embedding",
        "A banana embedding places the fruit in vector space.",
        provider="ollama", model="stub-model",
    )
    await _record(
        client, alice_headers, "Propulsion",
        "how does a rocket work",
        "A rocket works by throwing mass backwards.",
    )

    exported = await _export(client, alice_headers)

    assert exported["format"] == TUTOR_MODEL_FORMAT
    assert exported["version"] == TUTOR_MODEL_VERSION
    assert exported["lesson_count"] == 2
    assert exported["topics"] == ["Embeddings", "Propulsion"]

    lessons = exported["lessons"]
    assert isinstance(lessons, list)
    first = lessons[0]
    assert isinstance(first, dict)
    assert first["term"] == "Embeddings"
    assert first["question"] == "what is a banana embedding"
    assert first["taught_by_provider"] == "ollama"
    assert first["taught_by_model"] == "stub-model"

    # A different learner loads Alice's file into their own empty corpus.
    bob = await make_user(session)
    bob_headers = await auth_headers(client, bob.email)

    response = await client.post(
        "/api/v1/tutor/model/import", json=exported, headers=bob_headers
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["imported"] == 2
    assert result["skipped"] == 0
    assert result["indexed_chunks"] >= 2

    # The imported corpus is not just stored — it is indexed and retrievable.
    recall = await client.post(
        "/api/v1/tutor/recall",
        json={"question": "tell me about banana"},
        headers=bob_headers,
    )
    assert recall.status_code == 200, recall.text
    body = recall.json()
    assert body["grounded"] is True
    assert "banana" in body["sources"][0]["content"].lower()

    # Re-exporting from Bob reproduces the same lessons.
    round_tripped = await _export(client, bob_headers)
    assert round_tripped["lesson_count"] == 2
    assert round_tripped["topics"] == ["Embeddings", "Propulsion"]


async def test_import_owner_comes_from_token_not_the_file(
    session: AsyncSession, client: AsyncClient
) -> None:
    """A model file cannot name the corpus it lands in.

    The export format carries no owner field at all, and the import route reads
    `owner_id` from the token. Even a file with owner fields bolted on must not
    reach another learner's corpus.
    """
    alice = await make_user(session)
    alice_headers = await auth_headers(client, alice.email)
    bob = await make_user(session)
    bob_headers = await auth_headers(client, bob.email)

    hostile = {
        "format": TUTOR_MODEL_FORMAT,
        "version": TUTOR_MODEL_VERSION,
        # Fields the format does not define. Extra keys must not steer anything.
        "owner_id": str(alice.id),
        "owner_email": alice.email,
        "lessons": [
            {
                "term": "Propulsion",
                "question": "how does a rocket work",
                "answer": "A rocket works by throwing mass backwards.",
                "owner_id": str(alice.id),
            }
        ],
    }

    response = await client.post(
        "/api/v1/tutor/model/import", json=hostile, headers=bob_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1

    # It landed in Bob's corpus...
    assert (await _export(client, bob_headers))["lesson_count"] == 1
    # ...and Alice's is untouched.
    assert (await _export(client, alice_headers))["lesson_count"] == 0


async def test_export_is_owner_scoped(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    alice_headers = await auth_headers(client, alice.email)
    bob = await make_user(session)
    bob_headers = await auth_headers(client, bob.email)

    await _record(
        client, alice_headers, "Embeddings",
        "what is a banana embedding",
        "A banana embedding places the fruit in vector space.",
    )

    bob_export = await _export(client, bob_headers)
    assert bob_export["lesson_count"] == 0
    assert bob_export["lessons"] == []
    assert "banana" not in json.dumps(bob_export).lower()


async def test_export_carries_no_vectors_and_no_identity(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The file is made to be shared, downloaded and used as a seed fixture.

    Vectors are reproducible from the text and valid for exactly one embedding
    space (hard rule #5), so shipping them would be a trap. The learner's
    identity has no business in a file that gets passed around.
    """
    user = await make_user(session, email="private-person@test.local")
    headers = await auth_headers(client, user.email)

    await _record(
        client, headers, "Embeddings",
        "what is a banana embedding",
        "A banana embedding places the fruit in vector space.",
    )

    raw = json.dumps(await _export(client, headers)).lower()

    assert "private-person@test.local" not in raw
    assert "owner_id" not in raw
    assert "embedding_dimensions" in raw  # the metadata note is kept...
    assert '"embedding":' not in raw  # ...but no actual vectors
    assert "hashed_password" not in raw


async def test_import_rejects_an_unrecognised_file(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Refusing outright beats importing half of something unknown."""
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    for bad in (
        {"format": "some-other-app/model", "version": 1, "lessons": []},
        {"format": TUTOR_MODEL_FORMAT, "version": 99, "lessons": []},
    ):
        response = await client.post(
            "/api/v1/tutor/model/import", json=bad, headers=headers
        )
        assert response.status_code == 422, response.text

    # A file missing the required fields entirely is a validation error too.
    response = await client.post(
        "/api/v1/tutor/model/import", json={"lessons": []}, headers=headers
    )
    assert response.status_code == 422


async def test_import_skips_incomplete_lessons(
    session: AsyncSession, client: AsyncClient
) -> None:
    """An empty field would index nothing and label a citation '— '."""
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    response = await client.post(
        "/api/v1/tutor/model/import",
        json={
            "format": TUTOR_MODEL_FORMAT,
            "version": TUTOR_MODEL_VERSION,
            "lessons": [
                {"term": "Propulsion", "question": "how does a rocket work",
                 "answer": "By throwing mass backwards."},
                {"term": "", "question": "q", "answer": "a"},
                {"term": "Gaps", "question": "   ", "answer": "a"},
                {"term": "Gaps", "question": "q", "answer": ""},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["imported"] == 1
    assert result["skipped"] == 3

    assert (await _export(client, headers))["topics"] == ["Propulsion"]


async def test_import_is_additive_not_a_replacement(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Importing merges. Wiping first would make a mistyped upload destructive."""
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    await _record(
        client, headers, "Embeddings",
        "what is a banana embedding",
        "A banana embedding places the fruit in vector space.",
    )

    response = await client.post(
        "/api/v1/tutor/model/import",
        json={
            "format": TUTOR_MODEL_FORMAT,
            "version": TUTOR_MODEL_VERSION,
            "lessons": [
                {"term": "Propulsion", "question": "how does a rocket work",
                 "answer": "By throwing mass backwards."},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert (await _export(client, headers))["topics"] == ["Embeddings", "Propulsion"]


async def test_model_routes_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/tutor/model/export")).status_code == 401
    response = await client.post(
        "/api/v1/tutor/model/import",
        json={"format": TUTOR_MODEL_FORMAT, "version": TUTOR_MODEL_VERSION,
              "lessons": []},
    )
    assert response.status_code == 401


# ──────────────────────── tier 2: the Modelfile ────────────────────────
#
# The syntax was verified against the real Ollama on 2026-08-02 —
# `MESSAGE user """..."""` with multiline content and embedded quotes survives
# `ollama create` and comes back intact from `ollama show --modelfile`. These
# tests pin the properties that would silently break it, since the suite runs
# with no Ollama and cannot re-check the parser.


async def _modelfile(
    client: AsyncClient, headers: dict[str, str], **params: str
) -> str:
    response = await client.get(
        "/api/v1/tutor/model/modelfile", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.text


async def test_modelfile_is_runnable_shape(
    session: AsyncSession, client: AsyncClient
) -> None:
    """FROM, SYSTEM, and a MESSAGE pair per lesson — the whole contract."""
    user = await make_user(session, "mf-shape@example.com")
    headers = await auth_headers(client, user.email)
    await _record(
        client, headers, "Embeddings",
        "What is an embedding?",
        "A vector that stands for a piece of text.",
    )

    content = await _modelfile(client, headers)

    assert "\nFROM llama3.1:8b\n" in content
    assert "SYSTEM " in content
    assert 'MESSAGE user """What is an embedding?"""' in content
    assert 'MESSAGE assistant """A vector that stands for a piece of text."""' in content
    # The claim that must never quietly disappear: this is a prompted model.
    assert "PROMPTED model, not a fine-tuned one" in content


async def test_modelfile_base_model_is_the_learners_choice(
    session: AsyncSession, client: AsyncClient
) -> None:
    """It is never validated against this machine — it resolves on theirs."""
    user = await make_user(session, "mf-base@example.com")
    headers = await auth_headers(client, user.email)
    await _record(client, headers, "RAG", "What is RAG?", "Retrieval then generation.")

    content = await _modelfile(client, headers, base_model="qwen3:4b")
    assert "\nFROM qwen3:4b\n" in content


async def test_triple_quotes_in_a_lesson_cannot_close_the_block(
    session: AsyncSession, client: AsyncClient
) -> None:
    """The one input that would turn a lesson into Modelfile syntax.

    Ollama has no escape for `\"\"\"` inside a triple-quoted argument, so an
    answer containing one would end the block early and hand the rest of the
    text to the parser as instructions. Rewritten, not escaped.
    """
    user = await make_user(session, "mf-quotes@example.com")
    headers = await auth_headers(client, user.email)
    await _record(
        client, headers, "Python",
        'How do I write a docstring?',
        'Use """triple quotes""" around it.',
    )

    content = await _modelfile(client, headers)

    body = content.split("MESSAGE assistant", 1)[1]
    # Exactly one opening and one closing delimiter on that argument — the
    # lesson's own quotes are gone.
    assert body.count('"""') == 2, body[:300]
    assert "'''triple quotes'''" in content


async def test_modelfile_is_capped_and_says_so(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Newest first, and the cap is announced rather than silent.

    Truncating from the wrong end would drop the most recent study, and
    truncating quietly would make an incomplete model look complete.
    """
    from app.services import tutor_model

    user = await make_user(session, "mf-cap@example.com")
    headers = await auth_headers(client, user.email)
    total = tutor_model.MAX_MODELFILE_PAIRS + 3
    for i in range(total):
        await _record(client, headers, f"Topic{i}", f"Question {i}?", f"Answer {i}.")

    content = await _modelfile(client, headers)

    assert content.count("MESSAGE user ") == tutor_model.MAX_MODELFILE_PAIRS
    assert "Left out:      3 older lessons" in content
    # Newest kept, oldest dropped.
    assert f"Question {total - 1}?" in content
    assert "Question 0?" not in content


async def test_modelfile_is_owner_scoped(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Same rule as every other route: one learner's model is their own."""
    alice = await make_user(session, "mf-alice@example.com")
    bob = await make_user(session, "mf-bob@example.com")
    alice_headers = await auth_headers(client, alice.email)
    bob_headers = await auth_headers(client, bob.email)

    await _record(
        client, alice_headers, "Secret", "Alice's question?", "Alice's answer."
    )

    assert "Alice's question?" not in await _modelfile(client, bob_headers)
    assert "Alice's question?" in await _modelfile(client, alice_headers)
