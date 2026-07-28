# mcp-py — LLM / RAG / MCP showcase

A demonstration app: document RAG over local SQLite, with the **generating model chosen by the
user at request time** (Ollama or Claude), an MCP server + client exposed as internal APIs, and a
Next.js frontend that visualises agent/tool execution.

> **Do not read `docs/jelena/` or `docs/ORIGINAL_BRIEF.md`.** They stay in the repo as
> Jelena's own reminders and are hers to keep — not session input. Everything that governs
> this codebase has been lifted out of them and into this file, `docs/PLAN.md` and
> `docs/TODO.md`. Don't open them for context, don't cite them as a source, don't ask her to
> reconcile them. If something seems missing, ask her directly.

## Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + SQLModel, **async throughout** | brief asks for async/coroutines/workers |
| DB | SQLite via `aiosqlite` | zero infra — the demo runs anywhere |
| Vectors | `sqlite-vec` `vec0` virtual table | no Postgres/Docker needed |
| Embeddings | Ollama `nomic-embed-text` (768-dim) | local, free, offline |
| Generation | Ollama **or** Claude, user-selectable | the core demo |
| Frontend | Next.js 16 App Router (`web/`) | |
| Types | `pyright` strict | |

## API — built and working

All under `/api/v1`. Every route is owner-scoped; `/health` is the only unauthenticated
one. Full table with auth levels, purposes and the Next.js proxy routes: `docs/API.md`.

| Group | Routes | Note |
|---|---|---|
| meta | `GET /health` *(unprefixed)* | also confirms sqlite-vec loaded |
| login | `POST /login/access-token` · `GET /login/test-token` | `username` is the email |
| users | `GET POST /users/` · `GET PATCH /users/me` · `GET PATCH DELETE /users/{id}` | `/me` and `/{id}` take **different schemas** — that asymmetry is the privilege-escalation fix, not an inconsistency (hard rule #4) |
| documents | `GET /documents/` · `POST /documents/upload` · `GET DELETE /documents/{id}` | embedding runs in the background |
| query | `POST /query/` · `POST /query/stream` | stream is typed SSE: `provider` → `sources` → `token`* → `done` |
| tutor | `POST /tutor/teach` · `POST /tutor/interactions` · `POST /tutor/recall` · `GET /tutor/stats` | teach is SSE and generation-only; interactions index synchronously so recall works immediately |
| tutor model | `GET /tutor/model/export` · `POST /tutor/model/import` | tier 1 of `PLAN.md` §7. Export carries no vectors and no identity; import takes `owner_id` **from the token, never the file** |
| providers | `GET /providers/` | live Ollama model list |

Planned, not built: MCP (`/mcp/...` — Milestone 3), rate limiting and audit log
(Milestone 4). `tool_call` / `tool_result` events and the `ToolTrace` UI already exist
with no producer — MCP is a producer change only.

## Decided (don't re-litigate)

- **Standalone.** No shared data with Jelena's other three projects — this one is
  deliberately the simple one. SQLite stays.
- **Purpose:** showcase / learning / theory. Prefer the simple option; the goal is
  something understandable and demoable, not maximal.
- **Data:** document-oriented only. No structured/tabular path. No real, sensitive,
  or regulated data — the demo content is invented.
- **Users:** multi-user with login, but no per-user document privacy yet. Real
  authorisation is a later session — don't build it speculatively.
- **Results are shown in *this* app.** Not in Hugging Face Spaces. HF Spaces is
  an acceptable *variant* / hosting option, not where the work is displayed.
  Don't move the UI there.
- **Shape:** frontend-first, working backwards — the model is built in the
  frontend, embeddings run in the backend, results render in the app.
- **Default local model:** `llama3.1:8b`.
- **MCP:** goal is to reach the Claude console from inside the app. Postponed.

## Hard rules

1. **No OpenAI.** `openai`, `pgvector`, and `psycopg` were removed deliberately. Only Ollama and
   Claude are permitted providers. Do not reintroduce them.
2. **Anthropic ships no embeddings API.** Embedding is Ollama-only and is *not* user-selectable;
   only *generation* is. Don't add a "Claude embeddings" provider — it does not exist.
3. **`vectors.search()` takes `owner_id` as a required positional argument.** Never add an
   overload that makes it optional. This is what prevents the cross-tenant leak that existed in
   the original code — see `docs/ORIGINAL_BRIEF.md` history and `other_agent.md` finding #1.
4. **`UserUpdate` must not inherit `UserBase`.** Inheriting it exposes `is_superuser` to
   `PATCH /users/me` and lets any user self-promote. Declare its fields explicitly.
5. **One embedding space per index.** `vec_chunks` is declared `float[768]`. Changing the
   embedding model requires re-embedding every chunk, not just editing config.
6. **Never commit `related/`.** It contains a checked-in virtualenv and (until rotated) live
   credentials. It is reference material only.

## Claude API specifics

Read the `claude-api` skill before touching `app/services/providers/claude.py`. Current rules:

- Default `claude-opus-5`; `claude-sonnet-5` / `claude-haiku-4-5` also selectable.
- Use `thinking={"type": "adaptive"}` and `output_config={"effort": ...}`.
- **Never** send `temperature`, `top_p`, `top_k`, or `budget_tokens` — all 400 on Opus 5.
- Check `response.stop_reason == "refusal"` **before** reading `response.content`.
- Streaming: `async with client.messages.stream(...)` → `async for text in stream.text_stream`.

## Ollama specifics

- `await client.embed(model=..., input=[...])` is natively batched — one call for all chunks.
- Streaming needs the `await` *before* the `async for`:
  `async for part in await client.chat(..., stream=True)`.
- `AsyncClient` defaults to **no timeout** — always pass one.

## Layout

```
app/
  api/routes/tutor.py   teach / record / recall / stats
  core/       config, db (async engine + sqlite-vec loader), security
  models.py   SQLModel tables + request/response schemas
  schemas/    events.py — typed SSE event union
  services/
    vectors.py          the ONLY module that touches vec_chunks
    rag.py              chunking, retrieval, prompt assembly
    providers/          base (Protocols), ollama, claude, registry
  api/routes/ login, users, documents, query, providers
web/          Next.js 16 frontend
docs/         see docs/TODO.md for what's next
```

## Conventions

- Every route is `async def`; every DB call goes through `AsyncSession`.
- Streaming responses emit **one JSON object per SSE line**, typed by `app/schemas/events.py`.
  Never emit bare text — a token containing `\n` corrupts the stream.
- New provider → implement the Protocol in `providers/base.py`, register it in `registry.py`.
  No route should ever import a concrete provider module.
- Errors that are the user's fault are HTTP 4xx with a `Message`; provider outages are 503.

## Commands

```bash
uv sync --extra dev              # install
uv run pyright                   # types (strict, must be clean)
uv run pytest                    # tests
uv run fastapi dev app/main.py   # API on :8000
cd web && npm run dev            # UI on :3000
```

## Docs map

`docs/API.md` every route and page, available vs planned ·
`docs/PLAN.md` architecture, **deployment**, and the model export format ·
`docs/TODO.md` what's next + your duties · `docs/MANUAL.md` user + developer guide ·
`docs/CONTINUE.md` session handoff · `other_agent.md` full defect inventory

**Off-limits:** `docs/jelena/` and `docs/ORIGINAL_BRIEF.md` — see the note at the top.
