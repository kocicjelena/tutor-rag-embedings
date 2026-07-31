# Continue here

> ## Jelena — how to start the next session
>
> **Open a new session and say: `please read .claude/rules/CONTINUE.md`.**
>
> Not `/resume`. `/resume` reloads an entire previous conversation — every tool
> call, every file I read, every dead end — before it can do anything. This
> session ran long, so that is a large cost paid up front to recover context
> that is already written down here, and it arrives cluttered with detail that
> is no longer true.
>
> A fresh session loads `CLAUDE.md` automatically and reads this file in a few
> seconds. That is the whole handover, deliberately.
>
> **`/resume` is the right tool for one case:** you stopped mid-task, within a
> few hours, and the state that matters was never written down — a half-applied
> edit, a debugging thread. That is not this. Everything from 2026-07-30 and
> 2026-07-31 is in the docs.
>
> If a session ever *cannot* continue from this file, that is a bug in this
> file. Tell me and I will fix it rather than reach for `/resume`.

Last worked: **2026-07-31** — the vector layer (streaming ingestion, pluggable
embedding provider, re-embed command), the agent's corpus primer, and the whole
deployment path (Dockerfile, base image, two GitHub workflows). Before that,
2026-07-30: the MCP layer, tool calling, bring-your-own-key, and the two tutor
bugs. Before that: Milestone 1 end to end, the model export format (tier 1).

## The documents moved — 2026-07-31

**`docs/*.md` → `.claude/rules/*.md`**, and `other_agent.md` with them. Jelena's
decision: a repository should read the way any GitHub repository reads —
`README.md` for whoever arrives — and *"my structure with making a folder docs
for you is inappropriate"*. `.claude/` is where the tooling lives, so the
working documents live beside it.

Three things a future session needs to know about it:

- **They are still tracked in git.** That is not an accident and must not be
  undone. `docs/` was once ignored wholesale, nothing carried forward between
  sessions, and Jelena diagnosed that as a real bug. Moving is not hiding.
- **Do not recreate `docs/`.** What remains there is hers and untracked:
  `docs/jelena/` (off-limits) and `docs/ops/` (private, readable). Your own
  records go in `.claude/rules/` now — including the *"the plan is to have X,
  not built, reasons for / against"* deferrals that `~/.claude/CLAUDE.md` asks
  for in `docs/`.
- **The Space now gets README and code only.** `deploy-space.yml` deletes
  `.claude/` wholesale, which is one line doing what a list of `rm`s used to.

`README.md` is the public documentation and was rewritten for that: it now
carries the Docker workflow and points at `.claude/rules/` for the reasoning.

## Read in this order

1. `CLAUDE.md` — rules and the **Decided** list. Enough to start.
2. `.claude/rules/DECISIONS.md` — what was deliberately **not** built, and why. Read it
   before adding anything; it exists so the same arguments are not had twice.
3. `.claude/rules/TODO.md` — what's next, and what's waiting on Jelena.
4. Only if you need them: `.claude/rules/PLAN.md` (architecture, deployment, the model
   format), `.claude/rules/DEPLOY-HF.md` (the Space), `.claude/rules/other_agent.md` (what was broken),
   `.claude/rules/MANUAL.md` (how to run and extend).

> `docs/ops/` is private but **yours to read** — infrastructure plans for
> Jelena's own machines, written for a session to execute.

> `docs/jelena/` is **off-limits** — Jelena's own
> reminders, not session input. Everything that governs the code has been lifted out
> of them already.

## What works

Upload a document → embedded locally by Ollama → ask → answer streams back grounded
in your text with `[1]` citations, from **Ollama or Claude, your pick**.

`/tutor` in the web app: Claude (or Ollama) teaches, every exchange is indexed, and
"My model" answers by semantic retrieval over the learner's own lessons. Verified
live — word overlap scored 0.111 on a real question (below its own 0.2 cutoff, so it
would refuse), while retrieval put the right lesson first at 0.519.

MCP: four tools over the learner's own material, a client that speaks the real
protocol, and `GET /mcp/tools` · `POST /mcp/call` to see and drive them.

Tools: Claude decides what to search, the loop runs it over MCP, and every call
appears in the trace panel.

- `uv run fastapi dev app/main.py` + `cd web && npm run dev`
- **177 tests** (~44 s, no network), `pyright` strict clean, `tsc` clean
- Verified against live Ollama, direct and through the Next.js proxy

Not built yet: Ollama tool calling, rate limiting (Milestone 4), deployment,
registration + federated login.

## Latest: the model export format — tier 1 ✅

"The model" is the learner's corpus: the lessons they were taught, plus metadata.
Confirmed with Jelena. The reasoning — including why GGUF is a *different object*
rather than another way of writing the same thing — is in `PLAN.md` §7.

- `app/services/tutor_model.py` — record / export / import. **One code path**:
  `record_lesson` is the only way a lesson enters the corpus, whether it arrives from
  `POST /interactions`, from an imported file, or from a seed fixture.
- `TutorLesson` keeps each exchange verbatim. The indexed chunks overlap, so the
  original cannot be reassembled by joining them — hence a second copy. A new *table*
  rather than new columns on `Document`, because `create_all` adds missing tables but
  never missing columns, and there are no migrations here.
- `GET /tutor/model/export` → `tutor-model.json`. No vectors, no learner identity.
- `POST /tutor/model/import` → re-embeds; **`owner_id` from the token, never the file**.

**Gap to know about:** lessons recorded before this change have no `TutorLesson` row
and will not export. They still recall normally.

## Latest: the MCP layer ✅

Full design in `.claude/rules/MCP.md`. `app/mcp/` is four files: `context.py` (the tenant
boundary), `tools.py` (the tool bodies, with no MCP import), `server.py` (FastMCP
plus the descriptions, which are prompt text), `client.py` (a real client session).

Three things worth carrying forward, all of them in the hard rules now:

- **No tool takes an owner.** A tool's arguments are chosen by the model, so an
  `owner_id` parameter is untrusted input, not identity. The caller is read from a
  context variable only an authenticated route can set. Two tests assert on the
  *shape* — no owner-ish property in any tool's JSON Schema, no `session`/`owner_id`
  in any tool signature — because a regression here would be silent.
- **Never open an MCP session outside `client.tool_session`.** The caller must be
  bound before the server task spawns, or anyio's context copy misses it and every
  call reads whichever user arrived first.
- **Nothing raises inside a session block** — an anyio task group wraps it in an
  `ExceptionGroup`, so `except UnknownToolError` in a route never fires. Cost us one
  debugging round already.

## Latest: identity, and who pays for Claude ✅

Full record and the AWS/Auth0 checklist: **`.claude/rules/AUTH.md`** — and read *The
plan this serves* at the top of it before describing this app to anyone.

**The app is meant to issue identity.** A user registers with an email, the app
computes their id from it (`public_id` is the first piece of this, not a
URL-safety detail), they get their own page by route, and they are tied to
*this* app as their identity provider rather than to Google. The tutor,
retrieval and the exportable model are what that identity accumulates. The
direction is that the app charges for itself, because it costs money to run and
most visitors will never create an Anthropic account.

**BYOK is a stage on that road, not the destination.** Users bring their own
Anthropic key, so their Claude usage is billed to them — which is what makes a
free public deploy affordable, since Spaces has no Ollama and `PLAN.md` §6's
"open invoice" was otherwise unavoidable. Earlier sessions called this the
app's strongest feature. **That was a narrowing**, corrected 2026-07-31; see
the rule in `~/.claude/CLAUDE.md` about not shrinking the idea silently.

**The correction that shaped it:** a hash is one-way, so "store it hashed" and
"bill the user with it" cannot both be true. What is stored is `sha256` + a
fingerprint, neither usable; the real key lives in an httpOnly *session* cookie
and travels per request as `X-Anthropic-Key`. Encrypting at rest was rejected —
reversible means the app can read every user's key, which is the thing being
avoided.

**Three identifiers now exist and must not be mixed** (table in `CLAUDE.md`):
`User.id` is `owner_id` everywhere, `public_id` is the one-way HMAC handle for
URLs only, email is for login. `public_id` matches no row, so using it as an
owner fails *silently*. `ToolContext.owner_id` is typed `uuid.UUID` so the
handle cannot slip in, and the MCP shape test now rejects `public_id` and
`handle` as tool arguments.

## Latest: the vector layer ✅ — both proposals built, `.claude/rules/VECTORS.md`

**Streaming ingestion.** Your `send()`/`close()` idea, in the form that can
`await`: PEP 342 generators are synchronous, so the pipeline uses PEP 525's
`asend()`/`aclose()`. `app/services/ingest_stream.py` — prime with
`anext(sink)`, feed chunks, `aclose()` flushes the partial batch and commits.
Peak memory is one batch instead of one document. Upload uses it; the tutor
does not, because one short lesson gains nothing.

The trap that would have cost a day is handled and documented: `upsert_chunks`
begins with a delete, so calling it per batch would keep only the last batch
with no error. The delete is hoisted into `vectors.begin_document`.

**Pluggable `EmbeddingProvider`.** One `vec0` index per width;
`vec_chunks` keeps its name, so nothing migrated. `EMBEDDING_PROVIDER` chooses
Ollama or sentence-transformers (behind `uv sync --extra local-embed`, never a
default — torch is ~2 GB).

**Your decision, applied:** mark what the active model cannot search, and offer
a re-embed command. Never merge results across embedding spaces — the scores
are not on a common scale, so the ranking would look fine and mean nothing.
`indexed_with` + `searchable` on `GET /documents/`, a badge in the UI,
`uv run python -m app.scripts.reembed --dry-run`.

**One thing found while building:** vec0 creates its own shadow tables sharing
the prefix (`vec_chunks_rowids`, `vec_chunks_info`, …), so the per-width suffix
carries a `d` — `vec_chunks_d384` — and "list every index" filters on
`sql LIKE '%USING vec0%'` as well as the name. Two tests pin it.

**Not verified:** the sentence-transformers provider has never actually run —
the extra is not installed here. Treat it as untested.

## Latest: the agent primer ✅ — your answer to "the agent costs more"

`agent.build_primer`. An agent's cost is measured in **rounds**, and the
cheapest round is the one that never happens. A cold agent spends one on
`tutor_stats` or `list_documents` learning facts this app reads from its own
database in milliseconds — so they now go into the system prompt up front:
lessons, uploads, indexed passages, topic names.

**The boundary that matters:** the primer is facts, never instructions. Topic
names come from documents a user uploaded, so a document titled *"ignore
previous instructions and…"* must arrive as a title. They are capped, framed
inside one sentence, and labelled as data; a test uses a hostile title.

It fails soft — if the read errors the agent runs unprimed — and a caller that
passes an explicit `system` is not primed at all.

## Tool calling ✅ — the panel is no longer empty

`app/services/agent.py` + `POST /query/agent`, with a "let the model use tools"
toggle on `/`. Claude picks the tools, the loop runs them over MCP, and every call
appears in `ToolTrace` — the component needed no change, which was the point of
defining the event protocol first.

- **A separate route, not a flag on `/query/stream`.** The agent is slower and costs
  more tokens; making it a mode would tax every plain question.
- **`ToolCallingProvider` is a second, optional Protocol.** Tool use depends on the
  model, not the provider, so requiring it on `ChatProvider` would break Ollama or
  fill it with raising stubs. `/query/agent` returns a clean 422 naming the
  alternative.
- The loop's types are provider-neutral; Anthropic's block format lives in
  `claude_provider._to_anthropic`. A third provider changes nothing in the loop.
- `MAX_TOOL_ROUNDS = 5` is a ceiling against a model that searches forever on the
  user's balance. A failed tool goes back to the **model**, not the user.

## Latest: the status page ✅ — the app reporting on itself

`GET /api/v1/status/`, `app/services/capabilities.py`, and `/status` in the UI.
Design notes in `.claude/rules/API.md` under *status*.

Jelena's ask: give "built but never run" a real home, with four states —
**running, built, building**, and a fourth for things examined and deliberately
refused because they *"ruin the logic, the sense of existence of ML, AI and
model protocols, and make the app meaningless"*. That fourth status is
`exploring`, and it is the reason the page is worth having.

Two rules hold it together, both tested:

- **A probe may promote, never overrule.** A successful probe lifts `built` to
  `running`. It can never touch `building` or `exploring`, because those are
  *decisions* and no runtime observation can argue with one. Without this, a
  refused feature that happens to be reachable would quietly turn green and the
  reasoning would vanish.
- **`running` is measured, never declared.** A test enforces that no capability
  claims `running` without a probe — with one deliberate exception
  (`streaming-ingest`, which cannot be probed without uploading a document), and
  the UI says out loud when a row was not measured.

A probe that fails or times out becomes *evidence*, not a 500. Live, against
real Ollama: **6 running, 5 built, 4 building, 7 refused, in 360 ms** including
an embedding round trip and a real MCP session.

**One bug the tests found:** `report()` originally used `asyncio.gather`.
`AsyncSession` is not safe for concurrent use, so two probes lost their results
to *"this session is provisioning a new connection"*. It is sequential now, and
the docstring says why — the obvious optimisation is the wrong one here.

## Latest: the deployment path ✅ built, never run

Full plan and a candid assessment of it: **`.claude/rules/DEPLOY-HF.md`**.

**One private repo, filtered at deploy time.** An earlier draft argued for a
second generated repo; the reason given was wrong — `related/`, `docs/jelena/`
and `rag.db` were all gitignored and never in git. One repo removes the real
risk, which was divergence. The Space is public regardless of the repo's
visibility, so `.github/workflows/deploy-space.yml` strips `.claude/`,
`.CLAUDE.md`, `.claude/rules/other_agent.md`, `docs/jelena/` and `docs/ops/` before pushing.

**The Ollama base image is separate** (`deploy/ollama-base/`), on GHCR, built
manually plus monthly. Ollama's Linux release is 1.36 GB — mostly GPU runners
that cannot execute on a CPU Space — so it is pruned, and the build prints the
before and after rather than asserting a number. The same base serves the Space
and the laptop.

**Nothing has been built.** There is no Docker on this machine. Two dry runs
were possible and both earned their keep: the `.dockerignore` was simulated
against the real tree (738 MB working tree → 1.0 MB build context, with `.env`,
`rag.db` and `related/` confirmed excluded), and the process supervision in
`start.sh` was smoke-tested with fake processes, which found a real bug —
under `set -e`, a bare `wait -n` returning non-zero kills the script *at that
line*, so the log explaining which process died never printed.

**Two things Jelena must do before anything deploys:** run the base-image
workflow and make the GHCR package **public** (private is the default and
Hugging Face pulls anonymously), then create the Space and set `HF_TOKEN` and
`HF_SPACE`.
jelena: hf space is https://huggingface.co/spaces/kjelenak/my_tutor, trusted publisher on hf space set to 
https://github.com/kocicjelena/tutor-rag-embedings

**Half of that is now done — 2026-07-31.** The Space exists
(`kjelenak/my_tutor`) and it trusts this repository directly, so **`HF_TOKEN`
never happens**: `deploy-space.yml` gets a one-hour, one-Space token from
GitHub's OIDC identity instead, and stores nothing. `HF_SPACE` is set. Three
things now hold that together and each fails the run silently if it drifts:
`permissions: id-token: write`, the `spaces/` prefix on `HF_OIDC_RESOURCE`, and
the Hub-side claims — which are matched **exactly**, so renaming
`deploy-space.yml` stops the deploy.

**`main` is pushed — 2026-07-31.** Everything through
`0105378 Add the browser store, and make the Space deploy keyless` is on GitHub,
fast-forwarded from `milestone-3-mcp-agent-deploy` (also pushed). That push
fires `deploy-space.yml`, so **the first deploy has run at least once**; whether
the *Space* then built depends on the GHCR package being public. Next session:
branch before committing again — the local checkout is on `main` now.

Still Jelena's, and now the only blockers: **run the base-image
workflow**, and **make the GHCR package public**. Written out step by step, with
the failure table and both `CR_PAT` and CI routes for the Ollama image, in
**`.claude/rules/MANUAL-GITHUB.md`** — new, and the answer to her notes 4–7 in `TODO.md`.

## Latest: the browser store ✅ — chunks live in context now

Full record, including the NextAuth plan that has **not** been built:
**`.claude/rules/CONTEXT-AUTH.md`**. The conventions behind it, read out of Jelena's
three other Next.js projects (read-only, nothing touched):
**`.claude/skills/nextjs-context-auth/SKILL.md`**.

Her template, her file names: `web/types/interfaces/`, `web/reducers/`,
`web/context/GlobalContext.tsx`, split `{ state, actions }`, two contexts so a
component that only dispatches does not re-render. One slice so far, `stream`.

**What it is for.** A chunk is what this app processes, not a document — so
`lastChunk` is in the store, raw, beside the running `text` and `chunkCount`.
`STREAM_BEGIN` wipes the slice: current stream only, her decision. There is no
transcript and no localStorage, because the corpus already lives server-side in
`TutorLesson` and a second copy would drift.

**The part worth carrying forward** is `runStream`. `readEventStream` is an
async generator, so consuming it is a coroutine and whoever holds it owns the
stream — in a component the pipe dies with the component. In the provider it
does not, and because the action is `useCallback(…, [])` its identity never
changes, so it is a safe dependency anywhere downstream. That is what Jelena
meant by *"memoise can be kept in context and it won't hang or disappear"*.
Two producers already run through it: `useLearningTutor.teach` and `ChatStream`.

`reducers/WalletReducer.ts` — the file she copied in as a template — was
deleted, not adapted: it imports `viem`, and this app has no wallet. The
original in `~/multichain-main/my` is untouched.

`tsc` clean and `npm run build` green, standalone output intact. **Never
clicked.** Nobody has watched a stream finish in a browser since the change.

## Latest: Docker moved onto the laptop — 2026-07-31

**Why:** a Hugging Face Docker Space needs PRO ($9/month); only Static Spaces
are free and this app cannot be static. The full record, with the three routes
and their costs, is at the top of `.claude/rules/DEPLOY-HF.md`. Jelena's decision: build
and run it **here**, which costs nothing and is where the first real
`docker build` was always going to teach the most.

**Written:** `compose.yaml` at the repo root, and `.claude/rules/MANUAL.md` →
*Running it in Docker on your own machine* (install, build, **stop/start**,
logs, where the database lives, how to back it up while running).

**The one code change it needed:** `deploy/start.sh` no longer assumes it owns
the model server. `MANAGE_OLLAMA=0` tells it to use the Ollama already on this
laptop — the one with `llama3.1:8b`, so generation is local and free and nothing
is downloaded twice — while still waiting for it and still checking
`nomic-embed-text` is present. Unset, it decides from `OLLAMA_HOST`: loopback
means it is ours. A server or a Space is therefore unchanged.

`compose.yaml` has a second service behind `--profile isolated` that is
self-contained (its own Ollama, `nomic` only, generation via Claude) — that is
the one that reproduces what a server does.

**Nothing has been built yet.** Docker is *not installed on this machine*; the
first line of the manual section is the install command. `start.sh` is
syntax-checked and its ownership logic smoke-tested against five
`MANAGE_OLLAMA`/`OLLAMA_HOST` combinations, but no image has been built and no
container has run.

## Built and alive — but not yet run

**None of this is abandoned or optional.** Each item is committed, wired in and
needed. The only thing they have in common is that nobody has executed them
yet, and "written, typed and reviewed" is not the same claim as "working".
Treat them as verification debt, not as open questions.

| | Status | What a first run needs |
|---|---|---|
| **The sentence-transformers embedding provider** (`app/services/providers/sentence_transformers_provider.py`) | Shipped, registered, selectable with `EMBEDDING_PROVIDER=sentence_transformers`. It is the second `EmbeddingProvider` — the one that proves the seam in `providers/base.py` is real rather than asserted, and the only way this app embeds **without Ollama at all**, which is what a host with no Ollama would need | `uv sync --extra local-embed` (~2 GB of torch, which is why it is an extra and is not installed here), then upload a document and check the chunk count |
| **The whole Docker path** — `Dockerfile`, `.dockerignore`, `deploy/start.sh`, `deploy/ollama-base/`, both workflows | Shipped, and **the only way the Space runs at all**. Nothing about it is discretionary | Docker, which this machine does not have. The first build happens on GitHub's runners (the base-image workflow) or on the laptop in `docs/ops/LAPTOP8.md` |
| **`docs/ops/LAPTOP8.md`, `LAPTOP4.md`** | Plans, ready to execute | Physical access to those machines. Both open with a "facts to establish" step because they assume things that cannot be checked from here |

What *was* checked, because a dry run was possible:

- `.dockerignore` simulated against the real tree — 738 MB working tree → 1.0 MB
  build context, with `.env`, `rag.db`, `related/`, `docs/jelena/` and
  `docs/ops/` all confirmed excluded;
- the process supervision in `start.sh` smoke-tested with fake processes, which
  found a real bug: under `set -e` a bare `wait -n` returning non-zero kills the
  script *at that line*, so the log saying which process died never printed.

Expect the first real `docker build` to find something anyway. That is normal,
not a failure of the plan.

## Next step

Jelena postponed the whole *"what is next"* list in `MCP.md` — her note there
reads **"not in milestone"**. So Ollama tool calling, the `/api/mcp/*` proxy and
the outward transport are queued, not next.

**Next is the first real build**, and it is Jelena's move, not a coding task:
run the base-image workflow, make the GHCR package public, create the Space,
push. The unknowns all live there, and everything else is easier once a Space
exists — see `DEPLOY-HF.md` "Order of work" steps 4 and 5.

After that, in her stated order of interest: **tier 1 has no UI** (a download
button and a drop-target on `/tutor`), then tier 2 (`Modelfile` export),
seed-on-startup, and rate limiting before the URL is shared.

**One cheap CI change worth making early:** `deploy-space.yml` pushes on any
commit to `main` with no test gate. 177 tests run in ~44 s with no network.
They should run first and block the push. Recorded in `DECISIONS.md` as an
omission rather than a decision.

**`ToolCallingProvider` is not a dead end** — worth stating, because it read
that way. It is the interface the agent loop is written against and the only
reason `POST /query/agent` works: Claude implements `stream_turn`, `agent.run`
takes one, and every tool call in the trace arrives through it. It is
*optional* only in the sense that a provider need not implement it — which is
what keeps Ollama working instead of stubbed. Adding Ollama tool calling means
implementing this interface and nothing else.

## Two tutor bugs Jelena reported — both fixed 2026-07-30

**The streaming answer scrolled out of view.** `/` had no auto-scroll at all;
`/tutor` had one, but with `behavior: "smooth"`, which cannot keep up with a token
stream — each token restarted the animation and the view fell further behind. Now
both use `web/hooks/useStickToBottom.ts`: instant while streaming, smooth once
settled, and it stops following the moment the reader scrolls up.

**Locked out of "My model" with 2 lessons indexed.** `RECALL_UNLOCK_INTERACTIONS`
was 3. That was my call and it was wrong — a learner with two lessons has a working
model, and the gate told them they could not use it. It is 1 now: the corpus is the
gate. There was never anything to protect them from, because `POST /tutor/recall`
already answers honestly on a thin corpus (it says what it has not been taught and
names what it has). Proficiency now uses its own `BEGINNER_INTERACTIONS = 3`; the two
had been sharing one constant, which is why they were coupled at all.

## Deployment — decided, not built

`PLAN.md` "Deployment" has the reasoning. The short form:

- **One Docker image**: Next.js on the public port, FastAPI and Ollama on localhost.
  Free on Hugging Face Spaces now; the *same image* on one ~€5/month VPS later.
- **Not Vercel** for this project (it solves the easy half — Ollama is the hard half),
  **not EC2** for any project here (same work as a VPS, 2–4× the cost, expiring free
  tier, and none of what AWS charges its premium for is in use).
- **Why a model server is unavoidable:** embedding is Ollama-only and runs on the
  *write* path — the tutor embeds every lesson as it is recorded.
- **SQLite in deployment is a filesystem question, not a database one.** One writer,
  so never scale past one replica; `sqlite3 .backup` while running, not `cp`;
  `vec_chunks` lives in the same file, so the vectors travel with the data.
- **Rate limiting must land before the deploy**, not after — a public URL with uploads
  and paid Claude calls behind it is an open invoice.

## Two traps, already paid for

- **The sqlite-vec loading in `app/core/db.py` looks over-complicated. It isn't.**
  Two simpler forms fail: the SQLAlchemy adapter has no `enable_load_extension`, and
  calling it on the raw connection raises `ProgrammingError` because aiosqlite owns
  that object in a private worker thread. `test_sqlite_vec_loaded` pins it. Don't
  "simplify" it.
- **A green test suite is not enough for the RAG pipeline.** A chunking bug turned a
  286-character document into 201 chunks and passed every test. It showed up only in
  the numbers from a real upload. After touching chunking or ingestion, upload
  something and check chunk count against document length.

## Things not to re-derive

- Anthropic has **no embeddings API** — that is why there are two provider Protocols,
  not one. Not an oversight.
- **Claude generates; retrieval enhances.** Claude is what the learner uses to build
  their model; embedding came afterwards, as the layer that makes the corpus
  retrievable. "The model" is that corpus — not an ML model trained in the browser.
  The app's job is to let a user make their model, build it up, and download it.
- `vec0` specifics, verified: multi-value `IN` on metadata works; the primary key *is*
  enforced, so re-ingestion deletes before inserting.
- **No NVIDIA GPU on this machine** (Intel iGPU, 12 cores, 23 GB RAM) — which is why
  `llama3.1:8b` takes ~180 s for one sentence, and why any fine-tuning (tier 3) has to
  run on a free Colab/Kaggle T4, never here and never on the free Space.
  jelena: live sqlite issues for later. Focus is on building context for the app and making first, dummy publishing

  **Recorded, 2026-07-31:** `.claude/rules/TODO.md` → *SQLite — postponed on purpose, and
  the first thing to trace back*. It lists what already exists (WAL,
  `busy_timeout`, `/data`, vectors in the same file — do not rebuild those),
  what still has to be written (backup + restore, the persistence decision, the
  migration gap, ingestion progress), and the order: context → NextAuth →
  database. Her reason is a good one: without a channel to the browser, database
  fixes get invented in the wrong layer.

## How `/tutor` is wired — the answer to your question

Three server moves, and a client that decides which one to make.

**Teach** (`POST /tutor/teach`) is generation only. No retrieval: the tutor is
supposed to explain something new, and searching your corpus first would just
prime it with what you already know. It streams SSE, so text appears as it is
written.

**Record** (`POST /tutor/interactions`) takes the finished exchange and indexes it:
chunk → embed → store the vector under your `owner_id`, plus one `TutorLesson` row
keeping the exchange verbatim. Done **synchronously**, unlike file upload, because
you might switch to recall immediately afterwards and a background job would make
the model look forgetful.

**Recall** (`POST /tutor/recall`) is the opposite shape: retrieval first, then
generation constrained to what came back. It searches everything you own — lessons
*and* uploads, since both are things you have been exposed to — and the prompt tells
the model to answer only from those, cite them, and admit a gap rather than guess.

The counters are read from the index (`GET /tutor/stats`), not tallied in the
browser, which is why they survive a new browser profile. The learning model in
`localStorage` — proficiency, topic mastery, the vocabulary chart — is the dashboard
layer and is cosmetic; the real corpus is server-side.

The lock you hit was a fourth thing, purely client-side, and it is gone: see the bug
note above.
