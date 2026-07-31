"""SQLModel tables and request/response schemas.

Two structural changes from the inherited schema:

* `DocumentChunk` no longer holds the embedding. Vectors live in the
  `vec_chunks` sqlite-vec virtual table (see `app/services/vectors.py`), which
  carries `owner_id` so tenant scoping is enforced inside the index itself.
* `UserUpdate` no longer inherits `UserBase`. Inheriting it exposed
  `is_superuser` to `PATCH /users/me`, letting any user self-promote.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import computed_field
from sqlmodel import Field, Relationship, SQLModel

ProviderName = Literal["ollama", "claude"]
DocumentStatus = Literal["pending", "processing", "ready", "error"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────── User ────────────────────────────

class UserBase(SQLModel):
    email: str = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    documents: list["Document"] = Relationship(back_populates="owner")


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=40)


class UserUpdateMe(SQLModel):
    """Self-service profile update.

    Deliberately does NOT inherit UserBase: that would expose `is_superuser`
    and `is_active`, and crud.update_user applies model_dump(exclude_unset=True)
    straight onto the row. Only a superuser route may change privileges.
    """

    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=40)


class UserUpdate(UserUpdateMe):
    """Superuser-only update — may change privileges."""

    is_active: bool | None = None
    is_superuser: bool | None = None


class UserPublic(UserBase):
    id: uuid.UUID

    @computed_field
    @property
    def public_id(self) -> str:
        """The derived, shareable handle — see `app/core/identity.py`.

        Computed rather than stored, so it cannot drift from the email and
        there is no column to migrate. `id` stays the internal key; this is the
        one safe to put in a URL, because it is one-way and reveals no address.
        """
        from app.core.identity import derive_public_id

        return derive_public_id(self.email)


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# ──────────────────────────── Document ────────────────────────────

class DocumentBase(SQLModel):
    title: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=1000)


class Document(DocumentBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    owner: User | None = Relationship(back_populates="documents")
    chunks: list["DocumentChunk"] = Relationship(
        back_populates="document", cascade_delete=True
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    file_type: str | None = Field(default=None, max_length=50)
    char_count: int = Field(default=0)
    chunk_count: int = Field(default=0)
    status: str = Field(default="pending", max_length=50)
    # Populated when status == "error". The inherited code swallowed the
    # exception with a bare `except`, leaving failures undiagnosable.
    error_message: str | None = Field(default=None, max_length=2000)


class DocumentPublic(DocumentBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    file_type: str | None
    char_count: int
    chunk_count: int
    status: str
    error_message: str | None = None

    # Which embedding model indexed this document, read from its chunk rows
    # (`crud.get_embedding_models`) rather than stored on the row — there are no
    # migrations here, so a new Document column would not exist on an existing
    # database. None while it is still pending.
    indexed_with: str | None = None
    # False when it was indexed by a model other than the active one. Vectors
    # from two models are not comparable, so search cannot reach it — and the
    # honest answer is to say so rather than return nothing and look empty.
    # `uv run python -m app.scripts.reembed` is the fix.
    searchable: bool = True


class DocumentsPublic(SQLModel):
    data: list[DocumentPublic]
    count: int


# ──────────────────────────── DocumentChunk ────────────────────────────

class DocumentChunk(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id", nullable=False, ondelete="CASCADE", index=True
    )
    document: Document | None = Relationship(back_populates="chunks")
    content: str
    chunk_index: int
    # Which model produced this chunk's vector. Vectors from different models
    # are not comparable, so this is what makes a future embedding-model
    # migration detectable rather than silently wrong.
    embedding_model: str = Field(max_length=100)


# ──────────────────────────── Query / Chat ────────────────────────────

class QueryRequest(SQLModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[uuid.UUID] | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    # Which provider generates the answer. Embedding is always local (Ollama):
    # Anthropic exposes no embeddings endpoint.
    provider: ProviderName | None = None
    model: str | None = Field(default=None, max_length=200)


class ChunkResult(SQLModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    score: float


class QueryResponse(SQLModel):
    question: str
    answer: str
    sources: list[ChunkResult]
    provider: str
    model: str


# ──────────────────────────── Providers ────────────────────────────

class ModelInfo(SQLModel):
    name: str
    size: int | None = None
    family: str | None = None


class ProviderInfo(SQLModel):
    name: str
    available: bool
    default_model: str
    models: list[ModelInfo]
    detail: str | None = None


class ProvidersPublic(SQLModel):
    data: list[ProviderInfo]
    default_provider: str
    embedding_model: str
    embedding_dimensions: int


# ──────────────────────────── Tutor ────────────────────────────
# The learner's own history, indexed. `trained` mode in the tutor answers from
# this corpus instead of replaying the closest past answer by word overlap.

TutorMode = Literal["casual", "structured"]


class TutorTeachRequest(SQLModel):
    """Ask the tutor to explain something. Generation only — no retrieval."""

    question: str = Field(min_length=1, max_length=2000)
    term: str = Field(max_length=100)
    mode: TutorMode = "casual"
    goals: list[str] = Field(default_factory=list)
    provider: ProviderName | None = None
    model: str | None = Field(default=None, max_length=200)


class TutorLesson(SQLModel, table=True):
    """One exchange, kept verbatim.

    The indexed copy lives in `DocumentChunk` as overlapping chunks of a single
    composed string, which is right for retrieval and useless for export — the
    overlap means the original cannot be reassembled by joining chunks. So the
    lesson is also stored here, unsplit, as the source of truth for
    `GET /tutor/model/export`.

    A separate table rather than columns on `Document` for two reasons: these
    fields are meaningless for uploaded files, and there are no migrations here
    (`create_all` adds missing *tables* but never missing *columns*), so a new
    table upgrades an existing database and a new column would not.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    # The indexed representation. Deleting the document deletes the lesson.
    document_id: uuid.UUID = Field(
        foreign_key="document.id", nullable=False, ondelete="CASCADE", index=True
    )
    term: str = Field(max_length=100, index=True)
    question: str
    answer: str
    # Who taught it. Part of the export because "Claude taught me this" is a
    # fact about the learner's model, not incidental logging.
    taught_by_provider: str | None = Field(default=None, max_length=50)
    taught_by_model: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=_utcnow)


class TutorInteractionCreate(SQLModel):
    """One completed exchange, to be indexed into the learner's corpus."""

    term: str = Field(max_length=100)
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=20000)
    # Optional so the existing frontend keeps working unchanged; when sent,
    # they are carried into the export.
    provider: ProviderName | None = None
    model: str | None = Field(default=None, max_length=200)


class TutorInteractionPublic(SQLModel):
    document_id: uuid.UUID
    term: str
    chunk_count: int


class TutorRecallRequest(SQLModel):
    """Answer from what the learner has already been taught."""

    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    provider: ProviderName | None = None
    model: str | None = Field(default=None, max_length=200)


class TutorRecallResponse(SQLModel):
    question: str
    answer: str
    sources: list[ChunkResult]
    provider: str
    model: str
    # False when nothing was retrieved — the UI shows this as "not learned yet"
    # rather than dressing up an empty answer.
    grounded: bool


class TutorStats(SQLModel):
    interactions: int
    topics: list[str]
    indexed_chunks: int
    embedding_model: str


# ──────────────────── The model — export / import ────────────────────
#
# "The model" in this app is the learner's corpus: the lessons they were
# taught, plus metadata. This is the tier-1 artifact in `docs/PLAN.md` §7 and
# the source of truth the other two tiers are generated from.
#
# Deliberately absent:
#   * vectors — reproducible from the text, and valid for exactly one
#     embedding space (hard rule #5), so shipping them would be a trap
#   * anything identifying the learner — this file is made to be downloaded,
#     shared and used as a seed fixture

TUTOR_MODEL_FORMAT = "mcp-py/tutor-model"
TUTOR_MODEL_VERSION = 1


class TutorLessonExport(SQLModel):
    term: str
    question: str
    answer: str
    taught_by_provider: str | None = None
    taught_by_model: str | None = None
    learned_at: datetime | None = None


class TutorModelMeta(SQLModel):
    """How the corpus was indexed when exported.

    Informational: import always re-embeds with whatever is configured now.
    Kept so a mismatch is *visible* rather than silent.
    """

    embedding_model: str
    embedding_dimensions: int


class TutorModelExport(SQLModel):
    format: str = TUTOR_MODEL_FORMAT
    version: int = TUTOR_MODEL_VERSION
    exported_at: datetime = Field(default_factory=_utcnow)
    indexed_with: TutorModelMeta
    topics: list[str]
    lesson_count: int
    lessons: list[TutorLessonExport]


class TutorModelImport(SQLModel):
    """The same document, on the way back in.

    `format` and `version` are required: refusing an unrecognised file is
    friendlier than half-importing one.
    """

    format: str
    version: int
    lessons: list[TutorLessonExport]


class TutorModelImportResult(SQLModel):
    imported: int
    skipped: int
    indexed_chunks: int
    embedding_model: str


# ─────────────────── Bring-your-own Anthropic key ───────────────────
#
# The user supplies their own Anthropic key so **their** account is billed for
# Claude, not this app's. What is kept here is deliberately not enough to make
# an API call:
#
#   * `key_sha256`    — recognises the same key again (rotation, "is this the
#                       one you already gave me?"). One-way.
#   * `fingerprint`   — for display: "sk-ant-…AB12". Never enough to use.
#
# **The plaintext is never persisted.** It lives in the caller's session and
# arrives on each request as a header, is used, and is dropped. A dump of this
# table is worth nothing to an attacker — that is the entire point, and the
# reason this is not an "encrypted key" column.
#
# A separate TABLE rather than columns on `User`: `create_all` adds missing
# tables but never missing columns, and there are no migrations here. Same
# reasoning as `TutorLesson`.

class UserApiKey(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    # Only "anthropic" today. Present so a second paid provider does not need a
    # second table.
    provider: str = Field(default="anthropic", max_length=50, index=True)
    key_sha256: str = Field(max_length=64)
    fingerprint: str = Field(max_length=32)
    created_at: datetime = Field(default_factory=_utcnow)
    last_used_at: datetime | None = None


class UserApiKeyCreate(SQLModel):
    """Hand over a key. The plaintext leaves again immediately — it is verified
    against Anthropic, hashed, and dropped."""

    api_key: str = Field(min_length=8, max_length=512)


class UserApiKeyPublic(SQLModel):
    """What the owner may see about their own key. Never the key."""

    provider: str
    fingerprint: str
    created_at: datetime
    last_used_at: datetime | None = None


class UserApiKeyStatus(SQLModel):
    configured: bool
    key: UserApiKeyPublic | None = None
    # True when this app has its own key and is willing to spend it. False on a
    # public deploy, where a user without their own key simply cannot use Claude.
    app_key_fallback: bool


# ──────────────────────────── MCP ────────────────────────────
#
# The wire shapes for `/mcp/...`. They mirror MCP's own `tools/list` and
# `tools/call` closely on purpose: this surface exists so the frontend and a
# human can see exactly what a model sees, and a translation layer that
# prettified it would defeat that.

class MCPToolInfo(SQLModel):
    name: str
    title: str | None = None
    description: str | None = None
    # JSON Schema, straight from the server. The frontend renders it as the
    # tool's signature, and an agent hands it to the provider unchanged.
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPToolsPublic(SQLModel):
    server: str
    instructions: str | None = None
    tools: list[MCPToolInfo]
    count: int


class MCPCallRequest(SQLModel):
    """Invoke one tool by name.

    There is no owner field, and there must never be one — see
    `app/mcp/context.py`. The caller is the bearer token.
    """

    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPCallResult(SQLModel):
    name: str
    arguments: dict[str, Any]
    # False for a tool that refused or failed. Still HTTP 200: a failed tool
    # call is a result the model reads and recovers from, not a broken request.
    ok: bool
    text: str
    structured: dict[str, Any] | None = None
    duration_ms: int


# ──────────────────── Capabilities — what is real ────────────────────
#
# The app reporting its own state, honestly, instead of a README claiming it.
# Four statuses, and the fourth is the interesting one — see
# `app/services/capabilities.py`.

CapabilityStatus = Literal["running", "built", "building", "exploring"]

CapabilityArea = Literal["llm", "rag", "mcp", "identity", "deploy"]


class CapabilityPublic(SQLModel):
    key: str
    name: str
    area: CapabilityArea
    status: CapabilityStatus
    # One line, for the badge row.
    summary: str
    # The reasoning. For `exploring` this is the whole point of the entry.
    detail: str | None = None
    # Where the decision is written down, e.g. "docs/DECISIONS.md".
    doc: str | None = None
    # What the probe actually observed, when there was one. None means the
    # status is declared rather than measured — which the UI says out loud.
    evidence: str | None = None
    probed: bool = False


class CapabilityReport(SQLModel):
    data: list[CapabilityPublic]
    generated_at: datetime
    # Counts by status, so the UI does not have to tally them.
    totals: dict[str, int]


# ──────────────────────────── Auth ────────────────────────────

class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: str | None = None


class Message(SQLModel):
    message: str
