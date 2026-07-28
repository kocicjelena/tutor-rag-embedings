"""Test fixtures.

Every test runs against a throwaway SQLite file with a 4-dimensional embedding
space and a stub embedder, so the suite needs neither Ollama nor a network.
"""

import os
import tempfile
import uuid
from collections.abc import AsyncGenerator, Iterator, Sequence
from pathlib import Path

# Must be set before app.core.config is imported anywhere.
_TMP = Path(tempfile.mkdtemp(prefix="ragtest-"))
os.environ["ENVIRONMENT"] = "local"
os.environ["SQLITE_PATH"] = str(_TMP / "test.db")
os.environ["EMBEDDING_DIMENSIONS"] = "4"
os.environ["EMBEDDING_MODEL"] = "stub-embed"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["FIRST_SUPERUSER"] = "admin@test.local"
os.environ["FIRST_SUPERUSER_PASSWORD"] = "adminpassword123"
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app import crud  # noqa: E402
from app.core.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User, UserCreate  # noqa: E402
from app.services.providers import registry  # noqa: E402

DIMS = 4


class StubEmbedder:
    """Deterministic embeddings — no Ollama, no network.

    Maps text to a fixed vector by keyword so tests can assert on which chunk
    is nearest without depending on a real model's behaviour.
    """

    name = "stub"
    model = "stub-embed"
    dimensions = DIMS

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            if "banana" in lowered:
                out.append([0.0, 1.0, 0.0, 0.0])
            elif "rocket" in lowered:
                out.append([0.0, 0.0, 1.0, 0.0])
            else:
                out.append([1.0, 0.0, 0.0, 0.0])
        return out

    async def health(self) -> None:
        return None


class StubChatProvider:
    """Echoes the retrieved context so tests can assert on what was passed in."""

    name = "ollama"

    def __init__(self) -> None:
        self.default_model = "stub-model"
        self.last_system: str | None = None

    @property
    def available(self) -> bool:
        return True

    async def list_models(self):  # type: ignore[no-untyped-def]
        from app.models import ModelInfo

        return [ModelInfo(name="stub-model")]

    async def complete(
        self, *, system: str, user: str, model: str | None = None
    ) -> str:
        self.last_system = system
        return f"ANSWER({user})"

    async def stream(
        self, *, system: str, user: str, model: str | None = None
    ) -> AsyncGenerator[str, None]:
        self.last_system = system
        # Deliberately includes newlines — the SSE framing must survive them.
        for fragment in ("line one\n", "line two\n\nline three", " [1]"):
            yield fragment


@pytest.fixture(autouse=True)
def _stub_providers(  # pyright: ignore[reportUnusedFunction]  (pytest fixture)
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[StubChatProvider]:
    chat = StubChatProvider()
    monkeypatch.setattr(registry, "_embedder", StubEmbedder())
    monkeypatch.setattr(registry, "_chat_providers", {"ollama": chat})
    yield chat


@pytest.fixture(scope="session", autouse=True)
async def _create_schema() -> (  # pyright: ignore[reportUnusedFunction]  (pytest fixture)
    AsyncGenerator[None, None]
):
    await init_db()
    yield
    await engine.dispose()


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as s:
        yield s


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def make_user(session: AsyncSession, email: str | None = None) -> User:
    return await crud.create_user(
        session=session,
        user_create=UserCreate(
            email=email or f"user-{uuid.uuid4().hex[:8]}@test.local",
            password="password12345",
        ),
    )


async def auth_headers(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": "password12345"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
