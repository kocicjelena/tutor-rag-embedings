# Findings inventory — `app/` as inherited (pre-Milestone-1)

Produced per `.claude/rules/README.md`: **coverage over precision**. Everything found is listed,
including low-severity and low-confidence items. Nothing was filtered for importance — a
downstream verification pass should do that ranking.

Baseline: `app/` as it existed on 2026-07-27, before any Milestone 1 edits.
Severity: **Critical / High / Medium / Low / Info**. Confidence: **High / Medium / Low**.

---

## Security

### 1. Cross-tenant retrieval leak — Critical, High confidence
`app/crud.py:106-122`. `similarity_search` filters by `document_ids` only when that argument is
supplied. `POST /api/v1/query/` with `document_ids: null` (the default) searches **every chunk of
every user** and returns `content` verbatim in `sources` (`query.py:38-43`, `:56-67`). There is no
`owner_id` join anywhere in the query. The ownership checks at `query.py:26-32` and `:82-88` only
execute when IDs are explicitly passed, so the safe path is opt-in and the default path leaks.
*Fix in M1:* retrieval moved to `app/services/vectors.py` where `owner_id` is a required
positional argument and is filtered inside the `vec0` MATCH clause.

### 2. Privilege escalation via `PATCH /users/me` — Critical, High confidence
`app/models.py:29-31` + `app/api/routes/users.py:49-57`. `UserUpdate(UserBase)` inherits
`is_superuser: bool = False` and `is_active` from `UserBase` (`models.py:12-16`), overriding only
`email` and `password`. `crud.update_user` applies `model_dump(exclude_unset=True)`
(`crud.py:30-34`). Any authenticated user can therefore `PATCH /users/me` with
`{"is_superuser": true}` and become a superuser.
*Fix in M1:* `UserUpdate` declares its fields explicitly and no longer inherits `UserBase`.

### 3. `SECRET_KEY` defaults to `"changethis"` — High, High confidence
`app/core/config.py:21`, with no startup assertion. A deployment that forgets the env var has
forgeable JWTs. Same pattern for `FIRST_SUPERUSER_PASSWORD` (`:59`).

### 4. Live credentials committed in a sibling project — High, High confidence
`related/rag-fastapi-main/.env` contains a real Neon Postgres password and a real
`OPENAI_API_KEY` in plaintext. The same password is additionally hard-coded as
`FIRST_SUPERUSER_PASSWORD` in that project's `config.py`, and `FIRST_SUPERUSER` is a real email
address. `/home/jelena/mcp-py` is not a git repo and has no `.gitignore`, so nothing currently
prevents these from being committed. **Requires rotation by Jelena — Claude cannot do this.**

### 5. Unbounded upload read — Medium, High confidence
`app/api/routes/documents.py:78` does `await file.read()` with no size limit, holding the whole
file in RAM; `:107` then passes the full extracted text into `BackgroundTasks`, retaining a second
copy per request. Trivial memory exhaustion.

### 6. CORS: localhost injected unconditionally — Medium, High confidence
`app/core/config.py:29` appends `http://localhost:5173` to `all_cors_origins` in every
environment, combined with `allow_credentials=True` (`main.py:12-18`).

### 7. Auth error codes leak account existence — Low, Medium confidence
`app/api/deps.py:23-39` returns **403** for an invalid token (should be 401) and **404** when the
token is valid but the user row is missing. The 404-vs-403 split is enumerable.

### 8. No rate limiting or audit log anywhere — Medium, High confidence
Relevant because the brief explicitly asks for "firewalls or implementing policies that mark
certain activities as suspicious". No logging configuration exists in the app at all.

---

## Correctness

### 9. `init_db()` is dead code — Critical, High confidence
`app/core/db.py:19-26` is never called: no lifespan handler, no startup hook, no `initial_data.py`
script. Consequences on a fresh database: `CREATE EXTENSION vector` never runs,
`SQLModel.metadata.create_all` never runs (no tables), and the bootstrap superuser is never
created — so there is **no way to obtain a first login**. The app cannot function as shipped.

### 10. `chunk_text` can loop forever — High, Medium confidence
`app/services/rag.py:54`: `start = end - chunk_overlap` with no guarantee that `end` advanced past
`start + chunk_overlap`. If the boundary backoff (`:44-48`) picks an `idx` close to `start` — e.g.
text with a long run of short lines, or any input where the last `"\n\n"` before `end` falls within
200 chars of `start` — the new `start` moves *backwards*, and the loop repeats indefinitely
emitting duplicate chunks. Confidence is Medium only because triggering it requires a specific
input shape; the logic flaw itself is certain.

### 11. `get_current_user` passes `str` where a `UUID` is expected — High, Medium confidence
`app/api/deps.py:34` calls `session.get(User, token_data.sub)` where `sub` is typed `str | None`
(`models.py:126`) but `User.id` is `uuid.UUID` (`models.py:20`). Depending on SQLAlchemy/psycopg
coercion this either silently works or raises on every authenticated request. Under SQLite it will
not match at all.

### 12. `/query/stream` uses a non-existent SDK method — High, Medium confidence
`app/services/rag.py:140` calls `client.chat.completions.stream(...)`. On the declared floor
`openai>=1.40.0` (`pyproject.toml:17`) that helper lives on the beta namespace, not stable
`chat.completions`. The endpoint would `AttributeError` on any in-range install. Moot after M1
(OpenAI removed) but it means the streaming path was almost certainly never executed.

### 13. SSE framing is broken for multi-line tokens — High, High confidence
`app/api/routes/query.py:107` emits `f"data: {token}\n\n"`. Any token containing a newline splits
into multiple SSE events and corrupts the stream. The terminator `data: [DONE]` is also
indistinguishable from a legitimate answer containing that text.
*Fix in M1:* one JSON object per line, typed by `app/schemas/events.py`.

### 14. Background task swallows every exception silently — High, High confidence
`app/api/routes/documents.py:37-38` — bare `except`, sets `status="error"` with no error message
stored and no logging. Ingestion failures are undiagnosable. `char_count`/`chunk_count` are also
only set on success, so a failed document reports zero of both.

### 15. Embedding dimension hard-coded, diverges from config — Medium, High confidence
`app/models.py:92` declares `Vector(1536)` while `config.py:48` exposes
`EMBEDDING_DIMENSIONS: int = 1536` as if configurable. Changing the setting produces a dimension
mismatch at insert time. Directly relevant to the provider swap: `nomic-embed-text` is 768.

### 16. No vector index — Medium, High confidence
`core/db.py:14` runs only `create_all`; no HNSW or IVFFlat index is ever created on the embedding
column. Every similarity search is a sequential scan over all chunks.

### 17. N+1 query per result chunk — Medium, High confidence
`app/api/routes/query.py:58` calls `crud.get_document` once per returned chunk, purely to fetch a
title. A single `IN` query or a relationship access would do.

### 18. `chunk_text` binds config at import time — Medium, High confidence
`app/services/rag.py:27-28` uses `settings.CHUNK_SIZE` / `CHUNK_OVERLAP` as *default argument
values*, evaluated once at module import. They cannot be changed at runtime.

### 19. `settings.TOP_K_RESULTS` is never read — Low, High confidence
`config.py:53` is dead; the actual default is hard-coded at `models.py:101`.

### 20. `crud.get_documents` count query lacks `select_from` — Low, High confidence
`crud.py:67-69` is `select(func.count()).where(Document.owner_id == ...)`. SQLAlchemy infers the
FROM from the WHERE so it works, but the sibling at `users.py:27` correctly uses `.select_from()`.
Inconsistent and fragile.

### 21. Dead parameter + `__import__` in background task — Low, High confidence
`documents.py:14-41` takes a `session_factory: Any` that is never used (caller passes `None` at
`:107`), and resolves the model via
`session.get(__import__("app.models", fromlist=["Document"]).Document, ...)` (`:24`) instead of a
normal import.

### 22. `__import__("sqlmodel").text(...)` in db.py — Low, High confidence
`core/db.py:10-12` uses a dynamic import instead of `from sqlmodel import text`.

### 23. `SQLALCHEMY_DATABASE_URI` is a `computed_field` — Low, High confidence
`config.py:37-43` means it cannot be overridden by a single env var, so a one-DSN deployment
(Neon, Fly, Railway) has no supported way in. Only reachable by setting the five `POSTGRES_*` parts.

### 24. No uniqueness constraint on `(document_id, chunk_index)` — Low, Medium confidence
A retried ingestion can produce duplicate chunk rows.

### 25. `Document` has no `updated_at` — Info, High confidence

### 26. `DocumentCreate` is an empty `pass` stub — Info, High confidence
`models.py:62-63`. Harmless; standard SQLModel pattern.

---

## Operational

### 27. No tests exist — High, High confidence
No `tests/`, no `conftest.py`, no `test_*.py` anywhere in `app/`. `pytest`, `pytest-asyncio`,
`httpx`, and `coverage` are declared in `pyproject.toml:24-30` but unused.

### 28. No migrations — Medium, High confidence
`alembic>=1.13.0` is a dependency (`pyproject.toml:20`) but there is no `alembic.ini`, no
`migrations/`, no `versions/`. Schema comes from `create_all`, which cannot evolve a live DB.

### 29. Environment cannot run the app — Critical, High confidence
No Postgres, no `psql`, no Docker on the machine. `pyproject.toml` requires Python `>=3.11`;
system Python is 3.10.12. Ollama is running (v0.30.6) with 30 models but **zero embedding
models** — no `nomic-embed-text`, `mxbai-embed-large`, or `bge-*`.

### 30. No `.env.example`, `.gitignore`, `Dockerfile`, or `/health` endpoint — Medium, High confidence

### 31. `app/` is a near-duplicate of `related/rag-fastapi-main/app` — Info, High confidence
`diff -r` shows only 6 files differing, all cosmetic; `services/rag.py`, `crud.py`,
`api/routes/*`, and `core/security.py` are byte-identical. `app/` is the sanitised copy (the other
has real credentials as config defaults). Nothing needs porting back — but the duplication means
any fix applied to one silently diverges from the other.

### 32. `related/rag-fastapi-main/rag/` is a committed virtualenv — Low, High confidence
Thousands of files. Must be excluded from tooling and from any future git repo.

---

## Design observations (not defects)

### 33. Anthropic has no embeddings endpoint — Info, High confidence
This constrains the whole "user chooses provider" feature: it can only apply to *generation*.
Any design that lets the user pick an embedding provider per query would also silently invalidate
the existing index, since vectors from different models are not comparable.

### 34. The provider seam is unusually clean — Info, High confidence
Despite the defects, OpenAI touches exactly three call sites in one file
(`rag.py:66`, `:120`, `:140`) plus five config values. The swap is genuinely contained.

### 35. No `provider` field exists anywhere yet — Info, High confidence
Neither `User`, `Document`, nor `QueryRequest` carries a provider or model column, so there is no
persistence of "which model answered this" for the trace UI to display.
