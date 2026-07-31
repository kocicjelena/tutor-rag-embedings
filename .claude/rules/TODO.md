# TODO — this project only

`mcp-py` is standalone by choice. Nothing here depends on the other three
projects, and nothing here should grow to.

jelena: 
1. new  branch https://github.com/kocicjelena/tutor-rag-embedings  is not ready and pushed. We can do that in this session
2. make tutor app work with the new embedding model, as tool - the last thing in the session or it will be left for next session and that recorder here
3. make context for chunk (e.g. chunk is proceed not a document will be action made as callBack in GlobalContext.tsx tutor will be able to access that last chunk at least. second problem is virtual piping chanks, what can be solved using React Provider, already scaffold in many of my Next.js applications. Please have a look at !/home/jelena/ollama8jul If FastAPI get input from Next.js it will be state or action of Provider made in GlobalCOntext.tsx. very often. It is there to be helpful, do not force that. Eg async generator passed to corutine has to be async and can be recorded in context, so that what app has to memoise, and memoise can be keept in context and it wont hang or desapear. This approach demand thinking, please ask if you are in any dubt with providing questionare rather then prose. ). Even more important files for auth are deleted and you have made your way to authenticate. As we are making app as identity provider it has to be as you are instruct to do in chat. That was not written in docs/.. anywhere. I paste you the part of the code, provider is set like in project my/ but provider is not Ethereum, but identity I have to make in Cognito AWS console, instead of address we use email... Everything has to be done as I told you to do using [[..nextauth]] route. That is the best rule in Next.js and you will not chasing the circles of issues, bugs and problems. When context and nextauth is implemented you will see the development of this app meaningfull, as you do not trace unpossibilities, but you are writing what else has to be added (as logical process). Please ask any question and say if you can understand after thinking. Please confornt with me, ask me in questionare, disagree and agree on particular.
4. hf public space built on web console, available githubaction on repo https://github.com/kocicjelena/tutor-rag-embedings
5. docker not published, There is no Docker on this
machine, and it is said it is built
6. how can I publish idependant docker for nomic? 
env has now
CR_PAT=

What I have to do is this:
/////
$ echo $CR_PAT | docker login ghcr.io -u USERNAME --password-stdin
> Login Succeeded
Pushing container images
This example pushes the latest version of IMAGE_NAME.

docker push ghcr.io/NAMESPACE/IMAGE_NAME:latest
Replace NAMESPACE with the name of the personal account or organization to which you want the image to be scoped.
///
Please point me to the file explaining github/workflow/ and/or make manual_github.md for using the scripts made
Please tell me what I have to do next
7.  docker image not
  made as I have to have your instructions

## My answers to those seven — 2026-07-31

**1. Pushing.** `origin/main` is a single `init` commit; everything real is
local, on `milestone-3-mcp-agent-deploy` (5 commits ahead of local `main`).
Prepared, not done — pushing is outward-facing and the last step is yours. The
order matters: **the base image first**, because a push to `main` fires
`deploy-space.yml`, and a Space that builds before
`ghcr.io/kocicjelena/mcp-py-ollama` is public fails on the `FROM` line.

**2. The tutor driving the embedding model as a tool.** Not built, and I did not
start it — you scheduled it last precisely so it could slip. Recorded in
`DECISIONS.md` under *Postponed, with a trigger*, so it does not evaporate. It
is two things, not one: a fifth MCP tool, and a decision about whether
re-embedding may ever be a *model's* choice rather than an operator's. My view
is that reading (`indexed_with`, `searchable`, which documents are unreachable)
is a fine tool; re-embedding is not, for the same reason
`POST /documents/{id}/reembed` was refused — it is an all-users operator action.
Worth a session that is not also a deployment.

**3. Context + `[...nextauth]`.** The context half is **built**; NextAuth is
planned in full and not started. Everything about both is in
**`.claude/rules/CONTEXT-AUTH.md`**, and the conventions themselves — read out of
`~/multichain-main/my`, `~/ollama8jul` and `~/my-sei-dapp`, all read-only,
nothing touched — are written once as a skill:
**`.claude/skills/nextjs-context-auth/SKILL.md`**.

Built, on the template you copied in:

- `web/types/interfaces/{actionTypes,StreamType,ContextType}.ts`,
  `web/reducers/StreamReducer.ts`, `web/context/GlobalContext.tsx`, and the
  provider mounted once in `web/app/layout.tsx`
- the slice holds `lastChunk` — the frame exactly as it arrived — plus the
  running `text`, `chunkCount`, `status`, `kind`, `provider`/`model`
- **`runStream`**, the async action: it owns the async generator inside the
  provider, so the pipe does not die with a component, and it is
  `useCallback(…, [])` so its identity is stable — the memoisation you meant
- two real producers use it: `hooks/useLearningTutor.ts` (teach) and
  `components/ChatStream.tsx` (query/agent)
- `tsc` clean, `npm run build` green. **Not clicked in a browser yet.**

`reducers/WalletReducer.ts` was deleted rather than adapted — it imports `viem`
and there is no wallet here. Its shape is what survived, in `StreamReducer.ts`.

Left to do on this, in order:

- [ ] **Run it in a browser** — ask one question on `/`, one on `/tutor`, and
      watch a stream finish. Nothing here has been clicked
- [ ] **A visible consumer of `lastChunk`.** Nothing renders it yet, so the
      slice is proven by its producers and not by the UI. The obvious one is a
      small "receiving…" line on `/tutor` reading `state.stream`
- [ ] **NextAuth**, steps 2–5 of `CONTEXT-AUTH.md` → *Order of work*: install
      `next-auth@beta`, `web/lib/auth.ts`, the `[...nextauth]` route, move
      `lib/api.ts::getToken()` onto `auth()`, `AUTH_SECRET` into the Space
      secrets **before** that branch is pushed
- [ ] **Cognito as a second provider** — the only part waiting on the AWS
      console (`.claude/rules/AUTH.md`)
- [ ] Optional, when a fourth slice appears: swap the manual `rootReducer` for
      `react-combine-reducers`, as in `~/ollama8jul/globalx/`. Not before —
      a dependency in `npm ci` costs more than six lines do

**4. The Space.** Done on your side, and the workflow now matches it:
`HF_SPACE: kjelenak/my_tutor`, no `HF_TOKEN` anywhere, trusted publisher via
GitHub OIDC. See `.claude/rules/MANUAL-GITHUB.md`.

**5 + 7. "Docker is not made, and it says it is built."** Both are true and the
sentence to keep is: the Docker *files* are written, reviewed and typed; no
image has ever been built, here or anywhere. You need no Docker on this machine
— GitHub's runners build it. Instructions: `.claude/rules/MANUAL-GITHUB.md`.

**6. An independent Docker image for nomic.** It already has its own workflow —
`ollama-base.yml` — and that is exactly what it publishes: Ollama plus
`nomic-embed-text`, no app code, its own tag, its own schedule. Your `CR_PAT`
commands are correct but are the *laptop* route; CI needs no `CR_PAT` at all,
because the runner's own `GITHUB_TOKEN` can write to GHCR. Both routes are
written out in the manual, with the one step everyone forgets — **make the GHCR
package public** — called out on its own.

## SQLite — postponed on purpose, and the first thing to trace back

**Jelena's decision, 2026-07-31:** the live SQLite questions wait until the
context layer is integrated, because *"SQLite will be simpler and less buggy,
with fewer issues, once the context is in."* That reasoning is right and worth
keeping: half of what looks like a database problem here is really a **plumbing**
problem — nothing in the browser can hear about a row changing, so the fixes get
invented in the wrong layer. `runStream` and the store are that missing channel.

This section is the trace-back point. Read it before touching the database.

### Already done — do not rebuild it

`app/core/db.py` and the container already handle the parts people usually add
twice:

- `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, set on
  **every** connection through the `connect` event — not once at startup
- `SQLITE_PATH` is configuration (`app/core/config.py`), `/data/rag.db` in the
  image, with `VOLUME ["/data"]` and the directory owned by `appuser`
- the `vec0` tables live in the same file, so vectors travel with the data and
  no second store has to be kept in step
- one writer, one replica — a hard constraint, already in `DECISIONS.md`

### What has to be written additionally

- [ ] **A backup script.** `sqlite3 .backup` (or `VACUUM INTO`) while the app is
      running — never `cp`, which copies a file mid-write and a WAL that does
      not match it. `app/scripts/backup.py` beside `reembed.py`, plus a
      `wal_checkpoint(TRUNCATE)` first. Nothing exists today
- [ ] **A restore path, written down and tried once.** A backup nobody has
      restored is a belief, not a backup
- [ ] **The persistence decision for the Space.** The free tier's disk is
      ephemeral: `/data` is a volume in the image, but the Space rebuilds and it
      is gone. Three options — accept it and say so in the UI (today's plan),
      buy HF persistent storage, or snapshot the file to a private HF Dataset
      on a timer. **Not urgent for a dummy publish**, and that is exactly why it
      is written down rather than decided in a hurry
- [ ] **Seed-on-startup when the corpus is empty.** Already listed under Deploy;
      it belongs here too, because it is the *reason* ephemerality is survivable
- [ ] **The migration gap, in writing, at the place it bites.** `create_all`
      adds missing **tables** and never missing **columns**. So: a new column on
      an existing table needs a hand-written `ALTER TABLE` in the lifespan, or a
      new table instead — which is why `TutorLesson` is its own table. This will
      bite the moment identity grows a column (a Cognito `sub`, a `last_seen`),
      which is the next thing on the roadmap
- [ ] **Ingestion progress.** The streaming sink already yields a running count
      and nothing reads it, because upload is a background task with no channel
      to the browser. **This is the one that needed the context layer**: a
      `progress` slice fed by an SSE route turns the count into something a user
      sees. Do it after NextAuth, not before — it is the same plumbing
- [ ] **A disk/persistence line on `/status`.** The page probes everything else;
      "where the database is and whether it survives a restart" is exactly the
      kind of honest fact it exists to show

## Local Docker + `docker-compose` — a later session, after the four above

**Jelena's ask, 2026-07-31**, placed deliberately behind: SQLite, bug fixes,
improvements, then auth. Not before.

One correction to the wording of the ask, because it will matter when you look
for the image: the workflows push to **GHCR** (`ghcr.io`), GitHub's own
registry, **not Docker Hub**. That was a decision with a reason — Docker Hub
rate-limits anonymous pulls per IP and Hugging Face builds on shared runners, so
a Space rebuild would fail with `toomanyrequests` at an unpredictable moment.
GHCR has no such limit for public images. Recorded in `DECISIONS.md`.

What "all Docker locally" means here, once it is worth doing:

- [ ] **`compose.yaml`** with two services — the app image and the Ollama base
      image — instead of the single container that the Space needs. The Space
      gets one container because Spaces exposes one port; a laptop has no such
      constraint, and splitting them means a code change does not rebuild a
      1.4 GB Ollama layer
- [ ] **A named volume for `/data`**, so the SQLite file survives
      `docker compose down`. This is where it meets the SQLite section above:
      locally, persistence is free and the ephemeral-disk problem does not exist
- [ ] **A `compose.override.yaml` for development** — bind-mount the source and
      run `fastapi dev` + `next dev`, so the container is not rebuilt on every
      edit
- [ ] **`ollama pull llama3.1:8b` into the local Ollama volume**, which the Space
      deliberately does not have: locally you can generate without Claude and
      without spending anything
- [ ] **One page in `MANUAL-GITHUB.md` or its own doc** — `docker compose up`,
      where the data lives, how to back it up, how to reach the API directly
- [ ] Only then: whether the laptop in `docs/ops/LAPTOP8.md` runs the same
      compose file. It should; that is the point of one image

Trigger to start it: a first successful Space build, so there is a known-good
image to compare against. Debugging Docker locally and remotely at the same time
is two unknowns.

### How it integrates — the order that makes it simple

1. Context store ✅ *(done — `.claude/rules/CONTEXT-AUTH.md`)*
2. NextAuth in front of the existing FastAPI login — identity settles, and any
   new user column is known *before* the migration gap is tested
3. Then the database work above, in one pass: backup + restore, the persistence
   decision, the progress channel

Doing it in the other order means writing a migration for a column that gets
renamed a week later, and inventing a progress mechanism that the store makes
unnecessary.

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
jelena: we will focus on finishing app with tutor, fixing bugs, make updates on problems and make deployment. The plan will be left in .claude/rules/PLAN.md 
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

Ported into this repo and wired to real retrieval. Plan: `.claude/rules/PLAN-M2.md`.

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

Design and reasoning: `.claude/rules/MCP.md`.

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
**`.claude/rules/AUTH.md`**.

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

**`.claude/rules/VECTORS.md`** has the full reasoning and what changed from the sketch.
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
jelena: you have the writtings in .claude/rules/other_agent.md about the user anonymous who can patch administrator (user/me). That kind of problems goes here
## Deploy

**Plan written: `.claude/rules/PLAN.md` → "Deployment".** It answers the Next.js integration
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
reasoning in `.claude/rules/PLAN.md` §7, including why GGUF is a *different object* from JSON
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
