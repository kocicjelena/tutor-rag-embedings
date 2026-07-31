# API and pages

Generated from the live OpenAPI schema and the `web/app` tree on 2026-07-28.
Everything under **Available** is built, tested, and verified running.

FastAPI base URL `http://localhost:8000`, docs at `/docs`.
Next.js at `http://localhost:3000`.

---

# Available

## Pages

| Page | What it does |
|---|---|
| `/` | Documents. Upload files, ask questions, watch the answer stream with its sources and the tool-trace panel. |
| `/status` | What the app can do, checked as the page loads, plus what it refused to build and why. |
| `/tutor` | AI learning tutor. Claude or Ollama teaches, every exchange is indexed, and "My model" recalls from your own lessons. |

## Backend API — FastAPI

`Auth` = requires a bearer token. Get one from `POST /login/access-token`.

### meta

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `GET` | `/health` | – | Liveness, plus confirmation that sqlite-vec actually loaded |

### login

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `POST` | `/api/v1/login/access-token` | – | OAuth2 password form (`username` is the email) → JWT |
| `GET` | `/api/v1/login/test-token` | ✓ | Validate a token, echo back its user |

### users

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `GET` | `/api/v1/users/` | superuser | List users |
| `POST` | `/api/v1/users/` | superuser | Create a user (there is no public signup) |
| `GET` | `/api/v1/users/me` | ✓ | Your profile |
| `PATCH` | `/api/v1/users/me` | ✓ | Update your own profile — **cannot** set privileges |
| `GET` | `/api/v1/users/{user_id}` | ✓ | Read a user (self, or any if superuser) |
| `PATCH` | `/api/v1/users/{user_id}` | superuser | Update a user, including privileges |
| `DELETE` | `/api/v1/users/{user_id}` | superuser | Delete a user |

### documents

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `GET` | `/api/v1/documents/` | ✓ | Your documents, newest first |
| `POST` | `/api/v1/documents/upload` | ✓ | Upload `.txt` / `.md` / `.csv` / `.pdf`; embedding runs in the background |
| `GET` | `/api/v1/documents/{document_id}` | ✓ | One document, owner-checked |
| `DELETE` | `/api/v1/documents/{document_id}` | ✓ | Delete document, chunks, and vectors |

Every document carries `indexed_with` (which embedding model produced its
vectors) and `searchable`. `searchable: false` means it was indexed by a model
other than the one in use, so search genuinely cannot reach it — vectors from
two models are not comparable, and each width has its own `vec0` index. The UI
marks those documents rather than letting them look findable; the fix is
`uv run python -m app.scripts.reembed`. Detail in `VECTORS.md`.

Upload goes through the **streaming ingestion** path
(`app/services/ingest_stream.py`): an async generator consumes chunks and
writes them in batches, so peak memory is one batch rather than the whole
document. The tutor still indexes a lesson in one call — same result, and
streaming buys nothing for one short text.

### query

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `POST` | `/api/v1/query/` | ✓ | Ask; complete answer plus sources |
| `POST` | `/api/v1/query/stream` | ✓ | Same, as typed SSE: `provider` → `sources` → `token`* → `done` |
| `POST` | `/api/v1/query/agent` | ✓ | The tool-calling loop — the model chooses what to search. Adds `tool_call` / `tool_result` frames. Claude only; 422 naming the alternative on Ollama |

The agent's system prompt is **primed** from the learner's own model — lesson
count, upload count, indexed passages, topic names — so it does not spend a
paid round discovering what this app can read from its own database in
milliseconds. Facts only, never instructions: see `MCP.md`.

### tutor

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `POST` | `/api/v1/tutor/teach` | ✓ | Stream an explanation. Generation only — no retrieval |
| `POST` | `/api/v1/tutor/interactions` | ✓ | Index one completed exchange (synchronous, so recall works right after) |
| `POST` | `/api/v1/tutor/recall` | ✓ | Answer from the learner's own indexed lessons |
| `GET` | `/api/v1/tutor/stats` | ✓ | Lessons, topics, chunk count — read from the index |
| `GET` | `/api/v1/tutor/model/export` | ✓ | **The model** — download the learner's corpus as `tutor-model.json` |
| `POST` | `/api/v1/tutor/model/import` | ✓ | Load a model file into your corpus, re-embedding as it lands. Additive |

`export` and `import` are one code path in opposite directions — importing goes
through the same `record_lesson` that `POST /interactions` uses, which is what
makes seed fixtures and user downloads the same format. Two rules worth knowing:
the export carries **no vectors** (reproducible, and valid for one embedding
space only) and **nothing identifying the learner**; and import takes `owner_id`
**from the token, never from the file**. Detail in `PLAN.md` §7.

### providers

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `GET` | `/api/v1/providers/` | ✓ | Which providers are usable now, with live Ollama model list |

### keys — bring your own Anthropic key

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `GET` | `/api/v1/keys/anthropic` | ✓ | Have I a key on file, and does the app have a fallback |
| `PUT` | `/api/v1/keys/anthropic` | ✓ | Hand over a key — verified, hashed, plaintext dropped |
| `DELETE` | `/api/v1/keys/anthropic` | ✓ | Forget it |

The user's Claude usage is billed to **their** Anthropic account. Only a
`sha256` and a fingerprint (`sk-ant-…AB12`) are stored — neither can call
Anthropic. The working key travels per request in the `X-Anthropic-Key` header
and is never written down. **No route returns a key**, for anyone. Reasoning
and the deployment checklist in `AUTH.md`.

### status

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `GET` | `/api/v1/status/` | ✓ | Every capability, **probed** — what actually works right now |

`/health` answers "is this process alive". This answers "and which parts of it
work", by checking rather than by reading a list someone maintained by hand: it
opens a real MCP session and counts the tools, embeds a string, and asks SQLite
for `vec_version()`. Four statuses — `running` (measured just now), `built`
(committed and tested, not verified here), `building`, and `exploring`.

**`exploring` is the one worth reading.** Those are not a backlog: they are
things examined closely and deliberately refused, because building them would
have made the rest of the app mean less — a tool that generates its own text, a
search that merges two embedding spaces, an `owner_id` argument on a tool.

Two rules hold. A probe may **promote** a capability to `running`; it may never
overrule `building` or `exploring`, because those are decisions and no runtime
check can argue with one. And a probe that fails or times out becomes
*evidence*, never an error — a status page that falls over when a service is
down is worse than none. Design in `app/services/capabilities.py`.

### mcp

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `GET` | `/api/v1/mcp/tools` | ✓ | The tool catalogue, fetched over the protocol |
| `POST` | `/api/v1/mcp/call` | ✓ | Invoke one tool as the signed-in user |

Four tools: `search_documents`, `list_documents`, `get_document`,
`tutor_stats`. Both routes go through a real MCP client session, so this
surface cannot drift from what a model sees. A tool that runs and fails is
`200` with `ok: false`; only an unknown tool name is a `404`. **No tool takes
an owner** — the caller comes from the token and nothing else. Design in
`MCP.md`.

## Frontend API — Next.js route handlers

These proxy FastAPI so the JWT stays in an httpOnly cookie and never reaches the
browser.

| Method | Path | Proxies to |
|---|---|---|
| `POST` `DELETE` `GET` | `/api/auth` | sign in / sign out / session check |
| `POST` | `/api/chat` | `/api/v1/query/stream`, or `/api/v1/query/agent` when the request sets `agent: true` |
| `GET` `PUT` `DELETE` | `/api/keys` | `/api/v1/keys/anthropic` — plus the session cookie holding the working key |
| `GET` `POST` | `/api/documents` | list / upload |
| `GET` | `/api/providers` | `/api/v1/providers/` |
| `GET` | `/api/status` | `/api/v1/status/` — `no-store`, because a cached status page lies exactly when something has just broken |
| `POST` | `/api/tutor/teach` | SSE passthrough |
| `POST` | `/api/tutor/interactions` | record a lesson |
| `POST` | `/api/tutor/recall` | recall |
| `GET` | `/api/tutor/stats` | progress counts |

---

# Planned

## Milestone 3 — MCP: done

Server, tools, client, the two `/mcp` routes, **and** the agent loop that calls
them (`POST /query/agent`) all built 2026-07-30. The tool-execution panel on `/`
is no longer empty. Detail in `MCP.md`.

What remains:

| Item | Purpose |
|---|---|
| Ollama `stream_turn` | `llama3.1` supports tools; the loop is provider-neutral so nothing else changes |
| A Next.js proxy at `/api/mcp/*` | So the browser can read the catalogue directly |
| Streamable HTTP mount | So an external client (Claude Desktop, the console) can reach these tools — needs an auth story first |

## Milestone 4 — the "firewall" ask

Only if the showcase needs it; you said authorisation is a separate session.

| Item | Purpose |
|---|---|
| Rate limiting | Per-user and per-IP |
| Audit log | Auth events, uploads, queries |
| Suspicious-activity policies | Burst queries, mass download, repeated auth failures |
| Structured logging | There is currently no logging config beyond the basics |

## Deployment

| Item | Purpose |
|---|---|
| `Dockerfile` + Spaces entrypoint | Hugging Face Spaces (a hosting variant — results still render in this app) |
| Seed documents | So a fresh Space is not empty on first visit |

Two constraints if you go there: **no Ollama** (Claude-only, needs the key as a
Space secret) and an **ephemeral disk** on the free tier (uploads reset on
rebuild).

## Not planned — deferred by decision

| Item | Where |
|---|---|
| sentence-transformers embeddings | `jelena/future3.md` — needs per-dimension vector tables |
| Per-user document privacy | Your call: deliberate, not an oversight |
| Structured/tabular ingestion | Out of scope on purpose |
| Alembic migrations | Schema comes from `create_all`; fine at showcase scale |
