"""Application settings.

Loaded from environment / `.env`. See `.env.example` for the documented set.

Two deliberate changes from the inherited config:
  * All `POSTGRES_*` and `OPENAI_*` settings are gone — the store is SQLite and
    the providers are Ollama and Claude only.
  * `SECRET_KEY` and the bootstrap password are validated at import time rather
    than silently defaulting to "changethis" in production.
"""

from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import AnyUrl, BeforeValidator, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER = "changethis"

# The Next.js dev server. Added to CORS only when ENVIRONMENT == "local".
DEV_ORIGIN = "http://localhost:3000"


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    if isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "RAG API"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    SECRET_KEY: str = PLACEHOLDER
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field
    @property
    def all_cors_origins(self) -> list[str]:
        origins = [str(o).rstrip("/") for o in self.BACKEND_CORS_ORIGINS]
        # Only in local dev. The inherited config appended localhost:5173
        # unconditionally, including in production.
        if self.ENVIRONMENT == "local" and DEV_ORIGIN not in origins:
            origins.append(DEV_ORIGIN)
        return origins

    # ─── Database ────────────────────────────────────────────
    SQLITE_PATH: str = "./rag.db"

    @computed_field
    @property
    def sqlite_file(self) -> Path:
        return Path(self.SQLITE_PATH).expanduser().resolve()

    @computed_field
    @property
    def async_database_uri(self) -> str:
        return f"sqlite+aiosqlite:///{self.sqlite_file}"

    # ─── Embeddings ──────────────────────────────────────────
    # Ollama only: Anthropic does not expose an embeddings endpoint.
    OLLAMA_HOST: str = "http://127.0.0.1:11434"
    # Generous by default: an 8B model on CPU can take several minutes for a
    # long answer, and prompt processing grows with retrieved context. A tight
    # timeout here surfaces as a confusing 503 mid-demo.
    OLLAMA_TIMEOUT_SECONDS: float = 600.0
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSIONS: int = 768

    # ─── Generation ──────────────────────────────────────────
    DEFAULT_CHAT_PROVIDER: Literal["ollama", "claude"] = "ollama"
    OLLAMA_CHAT_MODEL: str = "llama3.1:8b"

    ANTHROPIC_API_KEY: str = ""
    CLAUDE_CHAT_MODEL: str = "claude-opus-5"
    CLAUDE_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    LLM_MAX_TOKENS: int = 1024

    @computed_field
    @property
    def claude_available(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY.strip())

    # ─── RAG ─────────────────────────────────────────────────
    TOP_K_RESULTS: int = 5
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10 MiB

    # ─── Bootstrap accounts ──────────────────────────────────
    # Both are created on startup **if missing** (see `init_db`) and are never
    # renamed: changing an email here adds an account, it does not rewrite the
    # existing one.
    #
    # Real addresses belong in `.env`, which is gitignored — not here. This file
    # is committed, and a real email plus a real password baked into committed
    # source is precisely the leak found in `related/rag-fastapi-main`
    # (`other_agent.md` #3). The defaults below are deliberately fake.
    FIRST_SUPERUSER: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = PLACEHOLDER

    # The demo account: an ordinary user, not a superuser, for showing the app.
    # Off unless an email is set — a live account with a known password is
    # exactly what should not appear by default.
    DEMO_USER: str = ""
    DEMO_USER_PASSWORD: str = PLACEHOLDER

    @computed_field
    @property
    def demo_user_enabled(self) -> bool:
        return bool(self.DEMO_USER.strip())

    @model_validator(mode="after")
    def _check_secrets(self) -> Self:
        """Fail fast on placeholder secrets outside local development.

        The inherited config shipped SECRET_KEY="changethis" with no check, so a
        deployment that forgot the env var had forgeable JWTs.
        """
        if self.ENVIRONMENT == "local":
            return self
        placeholders = [
            name
            for name, value in (
                ("SECRET_KEY", self.SECRET_KEY),
                ("FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD),
                # Only when the demo account is switched on — otherwise it is
                # never created and its password is irrelevant.
                *(
                    [("DEMO_USER_PASSWORD", self.DEMO_USER_PASSWORD)]
                    if self.demo_user_enabled
                    else []
                ),
            )
            if value == PLACEHOLDER
        ]
        if placeholders:
            raise ValueError(
                f"{', '.join(placeholders)} still set to '{PLACEHOLDER}' with "
                f"ENVIRONMENT={self.ENVIRONMENT}. Set real values in .env."
            )
        if self.CHUNK_OVERLAP >= self.CHUNK_SIZE:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return self


settings = Settings()
