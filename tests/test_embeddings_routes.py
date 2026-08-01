"""Embedding as a user-reachable operation, and the honest claim about derived models.

The central test here is `test_a_derived_model_admits_it_changes_no_vector`. It
pins a *statement the API makes about itself*, and it is worth more than the
plumbing around it.

The claim was measured, not reasoned about. On 2026-08-01, against the live
Ollama on this machine, a model was created from `nomic-embed-text` with the
system prompt from Jelena's note and one sentence embedded with each:

    identical vectors:    True
    max abs diff:         0.0
    capabilities:         ['embedding']
    modelfile has SYSTEM: True

The prompt is stored and does nothing, because an embedding model has no
generation step to read it. So a route that reported "custom model created" and
stopped there would be true and misleading, and the difference would be looked
for in the wrong place for a long time. `note_affects_vectors: false` is that
finding, made part of the contract — which means a future change that quietly
starts claiming otherwise fails here rather than in someone's understanding.

Ollama is faked throughout: these are tests about what this app says and checks,
not about whether Ollama embeds.
"""

from collections.abc import MutableSequence, Sequence
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import embeddings
from tests.conftest import auth_headers, make_user


class FakeShow:
    def __init__(self, capabilities: list[str], modelfile: str = "") -> None:
        self.capabilities = capabilities
        self.modelfile = modelfile


class FakeEmbed:
    def __init__(self, embeddings_: list[list[float]]) -> None:
        self.embeddings = embeddings_


class FakeDetails:
    family = "nomic-bert"


class FakeEntry:
    def __init__(self, model: str) -> None:
        self.model = model
        self.size = 274_000_000
        self.details = FakeDetails()


class FakeList:
    def __init__(self, names: list[str]) -> None:
        self.models = [FakeEntry(n) for n in names]


class FakeClient:
    """Enough of `ollama.AsyncClient` for these routes, and it records calls.

    `list` is a method on the real client, so inside this class body it shadows
    the builtin — which is why the annotations below use `Sequence` and
    `MutableSequence` rather than `list[...]`.
    """

    def __init__(self) -> None:
        self.created: MutableSequence[dict[str, Any]] = []
        self.embed_calls: MutableSequence[dict[str, Any]] = []

    async def list(self) -> FakeList:
        return FakeList(["nomic-embed-text", "llama3.1:8b", "my_nomic"])

    async def show(self, name: str) -> FakeShow:
        if name == "llama3.1:8b":
            return FakeShow(["completion", "tools"])
        if name == "my_nomic":
            # A real derived model's FROM is a blob path, not a model name — the
            # same path its base reports. See `_weights_digest`.
            return FakeShow(
                ["embedding"],
                modelfile="FROM /root/.ollama/models/blobs/sha256-970aa74c0a90ef74\n",
            )
        return FakeShow(["embedding"])

    async def embed(self, *, model: str, input: Sequence[str]) -> FakeEmbed:
        self.embed_calls.append({"model": model, "input": input})
        # 768-ish in shape, small in fact — the tests care about batching and
        # truncation, not about the numbers.
        return FakeEmbed([[0.6, 0.8] + [0.0] * 10 for _ in input])

    async def create(self, **kwargs: Any) -> None:
        self.created.append(kwargs)


@pytest.fixture
def fake_ollama(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(
        "app.services.embeddings.get_client", lambda: client
    )
    return client


# ──────────────────────── The service ────────────────────────


async def test_a_list_is_embedded_in_one_round_trip(fake_ollama: FakeClient) -> None:
    """Her ask, directly: `embed(model=..., input=[a, b])` — one call, not two."""
    result = await embeddings.embed_texts(
        model="nomic-embed-text",
        texts=[
            "The sky is blue because of rayleigh scattering",
            "Grass is green because of chlorophyll",
        ],
    )

    assert result.count == 2
    assert result.dimensions == 12
    assert len(fake_ollama.embed_calls) == 1
    assert len(fake_ollama.embed_calls[0]["input"]) == 2


async def test_vectors_are_previewed_unless_the_caller_asks_for_all(
    fake_ollama: FakeClient
) -> None:
    """A response that is normally 15 KB of floats teaches its caller to ignore it."""
    short = await embeddings.embed_texts(model="nomic-embed-text", texts=["x"])
    assert len(short.vectors[0].preview) == embeddings.PREVIEW_COMPONENTS
    assert short.vectors[0].truncated is True
    # The magnitude is computed over the *whole* vector, not the preview —
    # otherwise it would be a number about the truncation.
    assert short.vectors[0].magnitude == pytest.approx(1.0)

    whole = await embeddings.embed_texts(
        model="nomic-embed-text", texts=["x"], full=True
    )
    assert len(whole.vectors[0].preview) == 12
    assert whole.vectors[0].truncated is False


async def test_a_model_name_cannot_be_a_path(fake_ollama: FakeClient) -> None:
    """The sketch this replaced tried `ollama.copy('my_nomic', '../web/public/my_nomic')`.

    Both arguments to Ollama are *model names*. Passing a path creates a model
    with a very strange name and writes no file — so the name is checked, and
    the error says what a name is.
    """
    with pytest.raises(embeddings.EmbeddingRequestError) as caught:
        await embeddings.embed_texts(
            model="../web/public/my_nomic", texts=["x"]
        )
    assert "not a model name" in str(caught.value)


async def test_empty_and_oversized_input_are_the_callers_mistake(
    fake_ollama: FakeClient
) -> None:
    with pytest.raises(embeddings.EmbeddingRequestError):
        await embeddings.embed_texts(model="nomic-embed-text", texts=["  ", ""])

    with pytest.raises(embeddings.EmbeddingRequestError):
        await embeddings.embed_texts(
            model="nomic-embed-text", texts=["x"] * (embeddings.MAX_INPUTS + 1)
        )


async def test_models_are_listed_by_capability_not_by_name(
    fake_ollama: FakeClient
) -> None:
    """`llama3.1` is excluded because it cannot embed, not because of its name.

    The reverse of the chat picker's heuristic, and it matters: a derived model
    called `my_nomic` has no "embed" in its name and belongs here.
    """
    listed = await embeddings.list_embedding_models()
    names = [m.name for m in listed]

    assert "llama3.1:8b" not in names
    assert names == ["my_nomic", "nomic-embed-text"]


async def test_a_model_reports_the_weights_it_points_at(
    fake_ollama: FakeClient
) -> None:
    """Not "is it derived" — that question cannot be answered, and this one can.

    Measured 2026-08-01: a model created with `from_='nomic-embed-text'` reports
    a `FROM` line that is byte for byte the blob path `nomic-embed-text` itself
    reports. Ollama is saying the two names share one set of weights, which is
    why their vectors are identical — so the digest is the honest field, and a
    "custom model" badge would have implied the opposite of the truth.
    """
    listed = await embeddings.list_embedding_models()
    derived = next(m for m in listed if m.name == "my_nomic")

    assert derived.weights == "970aa74c0a90"


async def test_a_derived_model_admits_it_changes_no_vector(
    fake_ollama: FakeClient
) -> None:
    """The test this module exists for. See the module docstring for the measurement."""
    result = await embeddings.derive_model(
        name="my_nomic",
        base="nomic-embed-text",
        note="You are professor for machine learning and AI development.",
    )

    # The note is stored — it is not thrown away, and it records what the pin
    # is for.
    assert result.note is not None
    assert fake_ollama.created[0]["system"] == result.note

    # And it changes nothing. Both flags, because they are different claims:
    # the note has no effect, and the model is the base model's weights.
    assert result.note_affects_vectors is False
    assert result.vectors_identical_to_base is True
    assert "identical to the base" in result.summary
    # The value that *is* real is named, so the feature is not left looking
    # pointless once the honest part is said.
    assert "pin" in result.summary


async def test_a_derived_model_ships_a_modelfile_not_a_blob(
    fake_ollama: FakeClient
) -> None:
    """The download that works. A GGUF is 274 MB; this is a few hundred bytes."""
    result = await embeddings.derive_model(name="my_nomic", base="nomic-embed-text")

    assert "FROM nomic-embed-text" in result.modelfile
    assert "ollama create my_nomic -f Modelfile" in result.modelfile


def test_a_note_containing_a_quote_cannot_break_the_modelfile() -> None:
    content = embeddings.build_modelfile(
        name="my_nomic", base="nomic-embed-text", note='say "hello" \\ now'
    )
    system_line = next(l for l in content.splitlines() if l.startswith("SYSTEM"))
    assert system_line == 'SYSTEM "say \\"hello\\" \\\\ now"'


# ──────────────────────── The routes ────────────────────────


async def test_embed_route_needs_a_caller(client: AsyncClient) -> None:
    response = await client.post("/api/v1/embeddings/", json={"texts": ["x"]})
    assert response.status_code in (401, 403)


async def test_embed_route_defaults_to_the_apps_own_model(
    client: AsyncClient, session: AsyncSession, fake_ollama: FakeClient
) -> None:
    """"Show me what this app actually does to my text" is the common case."""
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    response = await client.post(
        "/api/v1/embeddings/", headers=headers, json={"texts": ["hello"]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["model"] == "stub-embed"


async def test_embed_route_reports_a_bad_request_as_422_not_503(
    client: AsyncClient, session: AsyncSession, fake_ollama: FakeClient
) -> None:
    """The user's mistake is 4xx; a provider outage is 503. They are not the same."""
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    response = await client.post(
        "/api/v1/embeddings/", headers=headers, json={"texts": []}
    )

    assert response.status_code == 422
    assert "at least one" in response.json()["detail"]


async def test_deriving_a_model_is_a_superuser_action(
    client: AsyncClient, session: AsyncSession, fake_ollama: FakeClient
) -> None:
    """It writes to a store every user of this app shares.

    And the tag it would most plausibly overwrite is the one the whole index
    depends on — so an ordinary account cannot reach it.
    """
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    response = await client.post(
        "/api/v1/embeddings/models", headers=headers, json={"name": "my_nomic"}
    )

    assert response.status_code == 403
    assert fake_ollama.created == []


async def test_the_modelfile_downloads_as_a_file(
    client: AsyncClient, session: AsyncSession, fake_ollama: FakeClient
) -> None:
    user = await make_user(session)
    headers = await auth_headers(client, user.email)

    response = await client.get(
        "/api/v1/embeddings/models/my_nomic/modelfile", headers=headers
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="Modelfile"'
    assert "FROM stub-embed" in response.text
