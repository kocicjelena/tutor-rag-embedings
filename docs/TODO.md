# TODO — this project only

`mcp-py` is standalone by choice. Nothing here depends on the other three
projects, and nothing here should grow to.

---

## Needs your decision

**1. What is the demo about?**
You mentioned an AI job-hiring app for employers and employees, and asked for
suggestions. My recommendation: **pick the smallest domain that still shows off
RAG.** The hiring idea works if the documents are CVs and job ads — a question
like *"which candidates have Kubernetes experience?"* demonstrates retrieval
plainly, and inventing 15 fake CVs is an afternoon.

Simpler alternatives, if you'd rather spend the effort on the MCP layer:
a small handbook, or a set of product manuals. Either way the app doesn't
change — only the seed documents do.
jelena: we will focus on finishing app with tutor, fixing bugs, make updates on problems and make deployment. The plan will be left in docs/PLAN.md 
**2. Hugging Face Spaces — two things to know before committing**
- **No Ollama.** The deployed app is Claude-only, so it needs `ANTHROPIC_API_KEY`
  as a Space secret. Locally you keep both providers.
- **Ephemeral disk on the free tier.** Uploaded documents vanish on rebuild. Fine
  for a demo that ships with seed documents; not fine if visitors' uploads must
  persist. Say which you want and I'll handle it (seed-on-startup is the simple
  answer).
jelena:seed-on-startup with dummy models made from learning. that models are in the format this app produces. that model made by user is possible to download.
---

## Done — the learning tutor ✅

Ported into this repo and wired to real retrieval. Plan: `docs/PLAN-M2.md`.

- `POST /tutor/teach` — streams an explanation (generation only, no retrieval)
- `POST /tutor/interactions` — indexes the exchange, synchronously, so recall
  works immediately afterwards
- `POST /tutor/recall` — semantic retrieval over the learner's own lessons
- `GET /tutor/stats` — progress counts read from the index, not a local tally
- UI at `/tutor`, restyled onto this app's design tokens; it reuses the provider
  picker, so the learner chooses who teaches *and* who synthesises recall

Measured against the behaviour it replaced, on *"how does a computer compare
meaning between two sentences"*:

| | result |
|---|---|
| word overlap (the ported `calculateSimilarity`) | best 0.111 — **below its own 0.2 threshold, so it gives up** |
| semantic recall | 0.519 on the correct Embeddings lesson, ranked first, answer cited |
jelena: please print to the user, in nice appealing format on web, that app uses semantic similarity rather then mathematical calculations (cosine similarity). However that should be just in plan.md (sin similarity is used more often and can be implemented in future, but not before finishing at least 20 session following)
## Milestone 3: MCP — the layer is built, the producer is not

Design and reasoning: `docs/MCP.md`.

- [x] **`app/mcp/`** ✅ *built 2026-07-30.* `context.py` (the tenant boundary),
      `tools.py` (four tools, no MCP import), `server.py` (FastMCP +
      descriptions), `client.py` (a real client session, not a function call)
- [x] `GET /api/v1/mcp/tools` and `POST /api/v1/mcp/call` — the catalogue and
      one-tool invocation, both over the protocol so they cannot drift from
      what a model sees
- [x] **`owner_id` comes from the caller's token, never from tool input.** No
      tool has an owner parameter and none can grow one; three tests guard the
      shape, not just the behaviour
- [x] 20 tests, verified live against the real corpus and Ollama embeddings

- [x] **Tool calling** ✅ *built 2026-07-30.* `app/services/agent.py` +
      `POST /query/agent`. The panel is no longer empty. `ToolCallingProvider`
      is a second, optional Protocol so Ollama is not broken or stubbed; the
      loop's types are provider-neutral, so a third provider needs no change to
      it. Round limit of 5. A failed tool goes back to the *model*, not the
      user. 19 tests
- [x] Frontend: a "let the model use tools" toggle on `/`, and `ToolTrace`
      finally rendering something
- [x] **The corpus primer** ✅ *built 2026-07-31* — your idea, derive the agent's
      instructions from the learner's own model. `agent.build_primer` puts the
      corpus shape (lessons, uploads, indexed passages, topics) into the system
      prompt, so the agent does not spend a **paid round** discovering what this
      app can read from its own database in milliseconds. Facts only, never
      instructions: topic names are user-supplied text, so they are capped,
      framed and labelled as data, with a test using a hostile document title

Still missing — **postponed, not in this milestone** (your note in `MCP.md`):

- [ ] **Ollama tool calling** — `llama3.1` supports it; one more `stream_turn`
      implementation, no change to the loop. `ToolCallingProvider` is exactly
      the interface it would implement
- [ ] A Next.js proxy at `/api/mcp/*` so the browser can read the catalogue
- [ ] **Outward transport** — mounting the Streamable HTTP app for an external
      client (Claude Desktop, the console). Needs an auth story first: today the
      caller is a bearer token resolved by FastAPI, and an external MCP endpoint
      has nothing equivalent to feed `app/mcp/context.py`. Related to the
      federated-login question below

## Identity + who pays for Claude — started 2026-07-30

Full record, including what you must do in the AWS (or Auth0) console:
**`docs/AUTH.md`**.

- [x] **Derived public user id** (`app/core/identity.py`) — one-way HMAC of the
      email, safe to put in a URL. Exposed as `public_id` on `UserPublic`
- [x] **Per-user Anthropic keys** — `GET PUT DELETE /keys/anthropic`. Only a
      hash and a fingerprint are stored; the working key travels per request in
      `X-Anthropic-Key`. Their account is billed, not yours
- [x] `get_chat_provider(name, api_key=...)`, per-user `GET /providers/`, 28 tests
- [x] **Frontend done** — `AnthropicKeyPanel`, httpOnly session cookie, and
      `X-Anthropic-Key` attached in `apiFetch` so no proxy route can be
      forgotten. Cookie cleared on sign-in *and* sign-out
- [x] **Three identifiers documented** (`CLAUDE.md`) — `User.id` is `owner_id`
      everywhere, `public_id` is for URLs only, and no MCP tool may accept
      either. The MCP shape test now rejects `public_id` and `handle` too
- [ ] Federated login, once you have the client id / secret / issuer — **you
      said 2026-07-31 that Cognito is not set up yet and this waits for a later
      session.** Nothing here is blocked by it
- [ ] `note_use` is never called, so `last_used_at` is always null
- [ ] Rate-limit `PUT /keys/anthropic` — it makes a live Anthropic call per
      attempt
- [ ] Before deploying: `ALLOW_APP_KEY_FALLBACK=false` and a real
      `IDENTITY_PEPPER`

## The vector layer ✅ built 2026-07-31

**`docs/VECTORS.md`** has the full reasoning and what changed from the sketch.
Both proposals are additive; the working 768-dimension path was not touched.

- [x] **Streaming ingestion with async generators.** Your `send()`/`close()`
      idea, corrected to `asend()`/`aclose()` — PEP 342 is synchronous and
      cannot `await`, which this pipeline must. `app/services/ingest_stream.py`;
      peak memory is one batch instead of one document. Used by upload; the
      tutor still indexes a lesson in one call. **The trap is handled:** the
      delete is hoisted into `vectors.begin_document`, so per-batch appending
      cannot erase the previous batch
- [x] **Pluggable `EmbeddingProvider`.** One `vec0` index per width
      (`vectors.table_for`), `vec_chunks` keeping its name so nothing migrates.
      `EMBEDDING_PROVIDER=ollama|sentence_transformers`, the second behind
      `uv sync --extra local-embed`
- [x] **Your decision, applied:** show it and offer a re-embed command; never
      merge results across embedding spaces. `indexed_with` + `searchable` on
      `GET /documents/`, a *not searchable* badge in the UI, and
      `uv run python -m app.scripts.reembed`
- [x] 19 new tests, including one asserting the streaming and whole-document
      paths produce identical chunks

Left open:

- [ ] **Progress reporting.** The sink yields a running count — one of the three
      reasons for building it — but upload is a background task with no channel
      to the browser, so nothing reads it. `pending → processing → ready` still
      has nothing in between
- [ ] **The sentence-transformers provider has never run.** Written, typed and
      reviewed, but the extra is ~2 GB of torch and is not installed here.
      Untested until someone installs it and uploads a document
- [ ] `reembed` re-embeds, it does not re-chunk. A `CHUNK_SIZE` change still
      needs a re-upload — deliberate, but worth knowing

## Postponed by your decision, 2026-07-30

Both deferred so MCP could land first. Neither is blocked — they are queued.

- [ ] **Registration UI + a federated login through AWS Cognito (OIDC).**
      `docs/jelena/OIDC.md` is your note on it, and you said you would point at the
      files when we pick it up. The connection you drew is the right one: an
      external identity provider hands back a stable subject claim, and that is
      exactly what `owner_id` wants to be — today it is a UUID this app mints
      itself, which works but means the app *is* the identity provider. It also
      unblocks the outward MCP transport above, which needs a caller identity
      that does not come from this app's own bearer token.
- [ ] **UI for making a new user.** Currently accounts exist only via `.env` at
      startup or `POST /users/` as a superuser.

## Later — Milestone 4

Only if the showcase needs it. The brief mentioned "firewalls / suspicious
activity", but per your note authorisation is a separate session.

- [ ] Rate limiting, audit log, structured logging
jelena: you have the writtings in other_agent.md about the user anonymous who can patch administrator (user/me). That kind of problems goes here
## Deploy

**Plan written: `docs/PLAN.md` → "Deployment".** It answers the Next.js integration
question, compares EC2 / VPS / PaaS / free tiers for your projects as a whole, and
states the conclusion: one Docker image, free on Hugging Face Spaces now, same image
onto one ~€5/month VPS later. Not Vercel for this project; not EC2 for any of them.

Short version of why: **embedding is Ollama-only and runs on the write path**, so the
deployed backend must host a model server. That rules out most free tiers, and it is the
half Vercel can never solve. Generation switches to Claude on deploy.

Checklist (detail and reasoning in `PLAN.md` §6–§7):

- [ ] `Dockerfile` — multi-stage node → python, Next.js on `:7860`, FastAPI on `:8000`,
      Ollama on `:11434`, all in one container (Spaces exposes one port)
- [ ] `output: "standalone"` in `web/next.config.ts`
- [ ] `start.sh` — ollama serve → pull/bake `nomic-embed-text` → uvicorn → next start
- [ ] `/health` must report **embedding readiness**, not just sqlite-vec
- [ ] Confirm the provider picker degrades cleanly when Ollama has no chat models
- [ ] **Rate limiting before launch, not after** — a public URL with uploads and paid
      Claude calls behind it is an open invoice
- [ ] Seed on startup only when the corpus is empty (the free Space disk is ephemeral)
- [ ] Decide how visitors get accounts — there is no public signup route by design

## The model — export in three tiers

Confirmed 2026-07-28: **the model is the learner's corpus** — lessons + metadata. Full
reasoning in `docs/PLAN.md` §7, including why GGUF is a *different object* from JSON
rather than another way of writing it, and why the app should never run the training.

Tier 1 is required. Tiers 2 and 3 are small additions on top of it.

- [x] **Tier 1 — `model.json`** ✅ *built 2026-07-28.* `TutorLesson` keeps each exchange
      verbatim (the indexed chunks overlap, so the original cannot be reassembled from
      them); `app/services/tutor_model.py` holds record / export / import; 8 tests
- [x] `GET /tutor/model/export` and `POST /tutor/model/import` — import re-embeds and
      goes through the same `record_lesson` as `POST /interactions`, so **export/import
      are one code path in opposite directions** and seeding is just import with
      fixture files
- [ ] **Frontend:** a download button and a drop-target on `/tutor`. The API is done;
      nothing in the UI reaches it yet
- [ ] **Lessons recorded before 2026-07-28 have no `TutorLesson` row and will not
      export.** They still recall normally. Either re-record them or accept the gap —
      backfilling would mean parsing overlapping chunks, which is exactly what the new
      table exists to avoid
- [ ] **Tier 2 — `Modelfile`.** `FROM llama3.1:8b` + `SYSTEM` + `MESSAGE` pairs built
      from tier 1. `ollama create` makes it real in seconds, no GPU. Honest about being
      a *prompted* model, not a fine-tuned one
- [ ] **Tier 3 — `?format=jsonl`** training pairs + a documented Colab recipe. The app
      produces the input, never the training run. **No NVIDIA GPU on this machine**, so
      fine-tuning happens on a free Colab/Kaggle T4; output ≈ 4.6 GB Q4_K_M, which comes
      back into tier 2 as `FROM ./model.gguf` or `ADAPTER ./adapter`
- [ ] Keep GGUF **off the deployed Space** — 4.6 GB on an ephemeral free tier is a bad
      trade. Tiers 1 and 2 are what the public demo hands out
---

## Done — Milestone 1 ✅

Runs locally, end to end, verified against live Ollama.

- Ollama + Claude behind one interface, chosen per request
- SQLite + sqlite-vec, fully async; tenant scoping enforced inside the index
- Next.js 16 UI: streaming answers, source panel, provider picker, tool-trace panel
- 56 tests, `pyright` strict clean
- Fixed from the inherited code: cross-tenant leak, privilege escalation,
  `init_db` never called, chunking loop, SSE framing
  (full list in `../other_agent.md`)

## Your setup steps

- [x] `ollama pull nomic-embed-text` — done
- [ ] `git init` (a `.gitignore` is ready; review `git status` first)
- [ ] `/plugin marketplace add kocicjelena/claude-fastapi-plugin` then
      `/plugin install claude-fastapi-plugin@jelena-plugins` — slash commands are yours to run
- [ ] `ANTHROPIC_API_KEY` in `.env`, if you want to demo the provider switch

## Known gaps, accepted for now

- **`grounded` means "retrieval returned something", not "the answer is
  supported".** sqlite-vec KNN always returns the k nearest, however far away
  they are, so it is only `false` on a completely empty corpus. In practice the
  model handles this well — asked about CNNs with only embeddings/RAG/transformer
  lessons indexed, it answered *"none of them discuss CNNs"*. A distance
  threshold would make the flag stronger, but the observed spread is narrow
  (0.519 relevant vs 0.497 unrelated), so a naive cutoff would be fragile. Left
  to the model's judgement deliberately.
- **Local models are slow on this machine** — `llama3.1:8b` took ~180s for one
  sentence and ~22s for a recall synthesis. `OLLAMA_TIMEOUT_SECONDS` is now 600.
  For a snappier demo, pick a smaller model in the picker or use Claude.

- No migrations — schema comes from `create_all`. Fine at showcase scale.
- No ANN index on `vec_chunks` — brute-force scan. Fine below ~100k chunks.
- No per-user document privacy — deliberate, see `CLAUDE.md`.
