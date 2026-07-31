# Manual

Two halves: [using the app](#part-1--user-guide) and [working on it](#part-2--developer-guide).

---

# Part 1 — User guide

## What it does

Upload documents, ask questions about them, and get answers grounded in their
actual content — with the **answering model chosen by you at ask time**, either
a local Ollama model or Claude.

Two things are worth understanding up front:

- **Embeddings are always local** (Ollama `nomic-embed-text`). Anthropic has no
  embeddings API, so only *generation* is switchable. Your documents are turned
  into vectors on your machine either way.
- **With provider = Ollama, nothing leaves your computer.** Choosing Claude
  sends the question and the retrieved excerpts to Anthropic.

## First run

You need two terminals.

**Terminal 1 — the API:**

```bash
cd ~/mcp-py
uv sync --extra dev          # first time only
uv run fastapi dev app/main.py
```

**Terminal 2 — the web UI:**

```bash
cd ~/mcp-py/web
npm install                  
npm run dev &
npm install-scripts ls
  \ npm approve-scripts --all
  \ npm approve-scripts --allow-scripts-pending
  npm audit fix --force   # first time only
cp .env.local.example .env.local
npm run dev
```

Open <http://localhost:3000>.

Sign in with the values of `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` from
`~/mcp-py/.env`. There is no public signup — accounts are created by a
superuser, by design.

## Using it

1. **Upload** a `.txt`, `.md`, `.csv`, or `.pdf` in the right-hand panel. The
   badge shows `pending` → `processing` → `ready (N chunks)`. If it says
   `error`, hover it for the reason.
2. **Pick a provider** above the upload box. Ollama models are listed live —
   `ollama pull` something new and it appears here without a restart. Claude
   shows as unavailable until `ANTHROPIC_API_KEY` is set.
3. **Ask a question.** ⌘/Ctrl + Enter sends. The answer streams in word by word.
4. **Check the sources.** "Retrieved context" shows exactly which chunks were
   used and how strongly each matched. Click one to expand it. The answer cites
   them as `[1]`, `[2]`.
5. **Tick "let the model use tools"** to run the agent instead of plain RAG.
   Claude decides what to search, and every call appears in the tool-execution
   panel with its arguments, its result and how long it took. It is slower and
   costs more tokens, which is why it is a checkbox rather than the default.
   Ollama does not do this yet and says so rather than failing quietly.
6. **`/status`** shows what the app can currently do, checked as the page
   loads rather than read from a list. Four states — *running* (verified a
   moment ago), *built*, *building*, and *explored, refused*. The last one is
   the interesting part: things examined closely and deliberately not built,
   with the reason, because building them would have made the rest mean less.
7. **A *not searchable* badge** on a document means it was indexed by a
   different embedding model than the one now in use, so search cannot reach
   it. See *Changing the embedding model* in the developer half.

## When something goes wrong

| Symptom | Cause and fix |
|---|---|
| Document stuck at `error` | Hover it. Usually the embedding model is missing: `ollama pull nomic-embed-text` |
| "not configured — see .env.example" | `ANTHROPIC_API_KEY` is unset. Add it to `.env` and restart the API, or use Ollama |
| "cannot reach the Ollama server" | Start it: `ollama serve` |
| "Could not reach the API" in the UI | The FastAPI terminal isn't running, or `API_BASE_URL` in `web/.env.local` points at the wrong port |
| Sign-in works but everything else 401s | You're serving the UI over HTTPS with a proxy that doesn't set `x-forwarded-proto` |
| Answer says "I don't have enough information" | Either nothing matched, or the document is still `processing`. This is the intended behaviour rather than a guess |
| A document is marked *not searchable* | `EMBEDDING_MODEL` changed since it was indexed. `uv run python -m app.scripts.reembed` |
| Search finds nothing at all, and every document is marked | Same cause, whole corpus. Same fix — or change `EMBEDDING_MODEL` back |

---

# Part 2 — Developer guide

## Layout

```
app/
  main.py              FastAPI app, lifespan, /health, 503 handler
  models.py            SQLModel tables + request/response schemas
  crud.py              DB access (no vector code — see services/vectors.py)
  core/
    config.py          settings; fails fast on placeholder secrets
    db.py              async engine, sqlite-vec loader, init_db
    security.py        bcrypt + JWT
  schemas/events.py    typed SSE event union
  services/
    vectors.py         THE only module touching the vec0 tables
    rag.py             chunking, whole-document ingestion, retrieval, prompts
    ingest_stream.py   streaming ingestion — the async-generator sink
    tutor_model.py     record / export / import / stats
    agent.py           the tool-calling loop, and the corpus primer
    capabilities.py    the self-report behind GET /status/ — probes, not claims
    providers/         base (Protocols), ollama, claude, sentence_transformers, registry
  mcp/                 context, tools, server, client — see docs/MCP.md
  api/routes/          login, users, documents, query, tutor, providers, keys, mcp
  scripts/             check_providers.py, reembed.py
tests/                 175 tests, no network required
web/                   Next.js 16 App Router
```

## Commands

```bash
# Backend
uv sync --extra dev
uv sync --extra local-embed               # optional: sentence-transformers (~2 GB)
uv run fastapi dev app/main.py            # :8000, auto-reload
uv run pytest                             # 175 tests, ~44s, no network
uv run pyright                            # strict, must stay clean
uv run python -m app.scripts.check_providers   # diagnose provider setup
uv run python -m app.scripts.reembed --dry-run # what a model change would cost
uv run python -m app.scripts.reembed           # re-embed unsearchable documents

# Frontend
cd web
npm install
npm run dev            # :3000
npm run build          # production build
npx tsc --noEmit       # typecheck
```

## Adding a chat provider

1. Create `app/services/providers/<name>_provider.py` with a class satisfying
   the `ChatProvider` Protocol in `base.py`: `name`, `default_model`,
   `available`, `list_models()`, `complete()`, `stream()`.
2. Register it in `registry.py`'s `_chat_providers` dict.
3. Add its literal to `ProviderName` in `models.py`.

No route imports a concrete provider, so nothing else changes. Raise
`ProviderUnavailableError` for anything the user can fix — it becomes a 503 with
your message rather than a stack trace.

## Adding an embedding provider

1. Create `app/services/providers/<name>_provider.py` with a class satisfying
   the `EmbeddingProvider` Protocol: `name`, `model`, `dimensions`,
   `embed(texts)`, `health()`.
2. Add its literal to `EMBEDDING_PROVIDER` in `config.py` and a branch in
   `registry._build_embedder`.
3. If it needs heavy dependencies, put them behind an optional extra in
   `pyproject.toml` and import them **inside** the function that uses them.

Three rules, each of which has bitten someone:

- **Never block the event loop.** In-process models are synchronous CPU work.
  Wrap them in `anyio.to_thread.run_sync`, or one upload freezes every other
  request in a single-worker app.
- **Never load at construction.** The registry builds providers at import, so
  a model download there stalls startup before `/health` can answer.
- **A new width is a new index, not a new column.** `vectors.table_for()`
  handles that automatically; you do not write SQL. But understand what it
  means for existing data — see below.

## Changing the embedding model

Vectors from two models are not comparable, and `vec0` fixes a vector's width
when its table is created. So each width gets its own index (`vec_chunks` for
768, `vec_chunks_d384` for 384) and **a search reads exactly one of them**.

Changing `EMBEDDING_MODEL` therefore destroys nothing and hides everything:
documents indexed under the old model are still on disk, still listed, and
completely unreachable by search. The app reports that — `searchable: false` on
`GET /documents/`, a *not searchable* badge in the UI — rather than returning
an empty result set that looks like a working search over an empty corpus.

```bash
uv run python -m app.scripts.reembed --dry-run
uv run python -m app.scripts.reembed
```

It re-embeds the stored chunk **text**, so it does not need the original file
and does not re-chunk. A `CHUNK_SIZE` change is a different operation and needs
a re-upload.

## The two ingestion paths

| | Used by | Why |
|---|---|---|
| `rag.ingest_document` | the tutor | one short lesson, indexed in one call |
| `ingest_stream.ingest_streaming` | document upload | bounded memory over a 10 MiB file |

They produce identical output — a test runs both over the same text and
compares chunk-for-chunk, because two implementations of one thing is exactly
the shape that drifts.

The streaming one is a PEP 525 async generator: prime with `anext(sink)`, feed
with `await sink.asend(chunk)`, finish with `await sink.aclose()`, which
flushes the partial batch and commits. **The delete is hoisted out**
(`vectors.begin_document` once, `append_chunks` per batch) because
`upsert_chunks` starts by deleting the document's vectors — call it per batch
and each batch erases the last one, with no error and a plausible chunk count.

## Adding an MCP tool

Full design in `docs/MCP.md`. Write the function in `app/mcp/tools.py` — a
plain async function, no MCP import — and register it in `app/mcp/server.py`
with a description written for a model to read. The catalogue, `GET /mcp/tools`
and the agent all pick it up with no further edit.

**The one thing that must not slip:** the tool takes no owner. Resolve the
caller from `app/mcp/context.py`, never from tool input — a tool's arguments
are chosen by the model, so an `owner_id` parameter is attacker-influenced
input rather than identity. Two tests assert on the *shape* of every tool
signature and JSON Schema, because a regression there would be silent.

## Invariants worth protecting

These are load-bearing; there are tests pinning each one.

1. **`vectors.search()` takes `owner_id` as a required positional argument.**
   Tenant scoping is enforced inside the `vec0` index, not by a WHERE clause a
   caller must remember. `test_vector_search_requires_owner_positionally`
   asserts the signature itself.
2. **`UserUpdateMe` has no privilege fields.** `PATCH /users/me` must never be
   able to set `is_superuser`.
3. **One JSON object per SSE line.** Never emit bare text — a token containing
   `\n` breaks the framing.
4. **One embedding space per index.** `vec_chunks` is `float[768]`. Changing the
   model means re-embedding everything, not editing config.

## The sqlite-vec loading glue

`app/core/db.py` reaches through two private APIs
(`aiosqlite.Connection._conn` and `._execute`) to load the extension. This is
not arbitrary — aiosqlite creates the real `sqlite3.Connection` inside a private
worker thread and sqlite3 objects are thread-bound, so:

- calling `enable_load_extension` on the SQLAlchemy adapter → `AttributeError`
- calling it on the raw connection from the event thread → `ProgrammingError:
  SQLite objects created in a thread can only be used in that same thread`

Scheduling the load back onto aiosqlite's own thread is what works.
`test_sqlite_vec_loaded` asserts `vec_version()` resolves, so a library upgrade
that breaks this fails loudly instead of silently disabling vector search.

## The `overrides` block in `web/package.json`

Added 2026-07-28. It is deliberate — **do not remove it to "clean up", and never
run `npm audit fix --force` on this project.**

```json
"overrides": { "postcss": "^8.5.24", "sharp": "^0.35.3" }
```

`npm audit` reported three high-severity advisories in `postcss` and `sharp`,
both pulled in by Next. Next pins `postcss` to an exact `8.4.31` and `sharp` to
`^0.34.5`, so neither `npm update` nor a fresh install can move them — an
override is the only lever.

**Why `--force` is wrong here.** It cannot patch a transitive dependency; its
only move is changing the version of `next` itself. The advisory range is
`next 9.3.4-canary.0 - 16.3.0-preview.7` and nothing is released above it, so
the only version outside the range is *below* it — it offers **next@9.3.3, from
March 2020**. That is range arithmetic, not a security judgment: the tree has no
matching advisories because it predates them, while carrying five years of its
own. We are on Next 16 by decision.

Verified after applying: `npm audit` 0 vulnerabilities, `next` still 16.2.12,
`tsc --noEmit` clean, `npm run build` green.

**When to remove it:** once Next depends on patched versions itself. Check with
`npm ls postcss sharp` after deleting the block — if the resolved versions are
still at or above the overrides, they are no longer doing anything. An override
is a pin you own, so left too long it can hold you *behind* an upstream fix.

*Neither advisory was reachable in this app* — the postcss issues need
attacker-controlled CSS (ours is authored in the repo) and `sharp` is only used
by `next/image`, which is not imported anywhere. Fixed because it was free, not
because it was urgent.

## Testing notes

`tests/conftest.py` stubs both providers and drops the embedding space to 4
dimensions, so the suite needs neither Ollama nor a network and runs in ~11s.
The stub chat provider deliberately yields fragments containing `\n` and `\n\n`
so the SSE framing is exercised on every streaming test.

---

# Appendix — how this was built

## Commands used during the Milestone 1 session

```bash
# Environment survey
ollama list                                    # 30 models, zero embedding models
curl -s http://127.0.0.1:11434/api/version     # 0.30.6
diff -r app related/rag-fastapi-main/app       # only 6 files differ, all cosmetic

# Verifying the stack before committing to it
uv pip compile -                               # sqlite-vec 0.1.9, anthropic 0.120.0, mcp 1.28.1
uv run python -c "...sqlite_vec KNN + metadata filter..."   # confirmed tenant filtering works
uv run python -c "...vec0 multi-value IN, PK enforcement..." # confirmed both

# Build + verification
uv sync --extra dev
uv run pyright                                 # 0 errors
uv run pytest -q                               # 56 passed
uv run python -m app.scripts.check_providers
ollama pull nomic-embed-text                   # 768-dim embedder
uv run uvicorn app.main:app --port 8123
cd web && npm install && npm run build && npm run start
```

## Bugs found and fixed

Full inventory with severity and confidence in `../other_agent.md`. The ones
that mattered:

| # | Bug | How it was closed |
|---|---|---|
| 1 | `POST /query/` with no `document_ids` returned **every user's** chunk text | Retrieval moved into `vectors.search()` with `owner_id` required and filtered inside the index |
| 2 | `PATCH /users/me {"is_superuser": true}` promoted any user | `UserUpdateMe` no longer inherits `UserBase` |
| 3 | `init_db()` was never called — no tables, no way to log in | Invoked from the FastAPI lifespan |
| 4 | `chunk_text` looped forever on short-line input | Guaranteed forward progress + break at end of text |
| 5 | **A 286-char document produced 201 chunks** | Found only by watching a real ingestion — see below |
| 6 | SSE corrupted on any token containing a newline | Typed JSON frames, one per line |
| 7 | Sign-in silently broken on a local production build | Cookie `secure` derived from request protocol, not `NODE_ENV` |

Two of those are worth calling out because tests alone would not have caught
them:

- **#5** was invisible to the test suite. The original loop was an infinite
  hang; the first fix bounded it, and the bounded-but-wrong version passed a
  test asserting `len(chunks) < 10_000`. It only surfaced as `chunks=200
  chars=287` in a real upload. The test now asserts average forward progress
  per chunk, which is the property that was actually violated.
- **#7** only appears under `npm run build && npm run start` on http://localhost
  — the dev server never triggers it.

## Decisions taken with Jelena

| Question | Decision |
|---|---|
| Vector store | SQLite + sqlite-vec — zero infrastructure |
| Embeddings | Ollama `nomic-embed-text`; sentence-transformers deferred to `docs/jelena/future3.md` |
| Frontend | Full Next.js 16 app in `web/` |
| Milestone 1 | Make it run + provider swap; MCP-first ordering deferred to `docs/jelena/future4.md` |
