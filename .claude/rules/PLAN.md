# PLAN — architecture and the reasoning behind it

Written 2026-07-27. Milestone 1 scope: **make the app run, and replace OpenAI with
user-selectable Ollama / Claude.**

## Where this started

`app/` is a near-identical copy of `related/rag-fastapi-main/app` (only 6 files differ, all
cosmetic — `diff -r` confirms `services/rag.py`, `crud.py`, `api/routes/*` and `core/security.py`
are byte-identical). It could not start on this machine: it needs a pgvector Postgres that isn't
installed, `init_db()` is never called so a fresh database has no tables *and no way to log in*,
and all three LLM call sites go to OpenAI.

Three defects found during exploration shaped the design rather than being cleanup afterwards.
Full inventory in `../other_agent.md`; the load-bearing ones:

1. **Cross-tenant leak** — `crud.similarity_search` only filters when `document_ids` is passed, so
   the default query path returned every user's chunk text.
2. **Privilege escalation** — `UserUpdate` inherited `is_superuser`, so `PATCH /users/me` let any
   user self-promote.
3. **`init_db()` never called** — no tables, no bootstrap superuser.

## Decisions

### Vector store: SQLite + sqlite-vec

Chosen over Neon, local Postgres, and a dual abstraction. The showcase should run anywhere with
`uv sync` and no account, no daemon, no container. Verified before committing: `sqlite-vec==0.1.9`
installs cleanly and its KNN accepts metadata filters.

That last property is the reason this is more than a convenience choice. `DocumentChunk` **loses
its `embedding` column**; vectors live in a virtual table that carries the tenant key:

```sql
CREATE VIRTUAL TABLE vec_chunks USING vec0(
    chunk_id    TEXT PRIMARY KEY,
    owner_id    TEXT,
    document_id TEXT,
    embedding   float[768]
);

SELECT chunk_id, distance FROM vec_chunks
WHERE embedding MATCH :vec AND k = :top_k AND owner_id = :owner_id;
```

`app/services/vectors.py` is the only module allowed to touch this table, and `search()` takes
`owner_id` as a **required positional argument**. There is no call shape that omits it — defect #1
is closed by construction, not by remembering to add a filter.

### Providers: two Protocols, not one

Anthropic ships **no embeddings API**. So "the user picks the provider" can only apply to
generation; embedding must be local and fixed. Modelling that honestly means two Protocols:

- `EmbeddingProvider` — Ollama `nomic-embed-text`, 768-dim, singleton.
- `ChatProvider` — Ollama or Claude, selected per request via `QueryRequest.provider`.

Concrete providers live behind `registry.get_chat_provider(name)`; no route imports a provider
module directly. A `claude` request with no API key configured returns 503, not a stack trace.

Provider-specific notes that cost real debugging time if missed:
- Ollama streaming needs `await` *before* the `async for`: `async for part in await client.chat(..., stream=True)`.
- `ollama.AsyncClient` defaults to **no timeout**.
- On `claude-opus-5`, `temperature`/`top_p`/`top_k`/`budget_tokens` all return 400. Use
  `thinking={"type":"adaptive"}` + `output_config={"effort":...}`, and check
  `stop_reason == "refusal"` before reading content.

### Async throughout

The brief asks for async/coroutines/workers, and the inherited code was entirely sync `def` over
`sqlmodel.Session`. Moving to `sqlite+aiosqlite` + `AsyncSession` makes the provider calls — the
only genuinely slow part — non-blocking. sqlite-vec loads per connection:

```python
@event.listens_for(engine.sync_engine, "connect")
def _load_vec(dbapi_conn, _):
    dbapi_conn.enable_load_extension(True)
    sqlite_vec.load(dbapi_conn)
    dbapi_conn.enable_load_extension(False)
```

*Risk, with a decided fallback:* this depends on aiosqlite proxying `enable_load_extension` to the
underlying `sqlite3.Connection`. Verification step 2 tests exactly this before any routes are built
on top. If it fails, use a sync engine for DB work and stay async only for provider calls — SQLite
queries here are sub-millisecond, so it costs nothing.

### Typed streaming events

The inherited `f"data: {token}\n\n"` corrupts on any token containing a newline. Replaced with one
JSON object per SSE line, discriminated on `type`:

```
{"type":"provider","provider":"ollama","model":"llama3.1:8b"}
{"type":"sources","chunks":[...]}
{"type":"tool_call","id":"...","name":"search_documents","input":{...}}   # M2
{"type":"tool_result","id":"...","ok":true,"preview":"..."}               # M2
{"type":"token","text":"..."}
{"type":"done","usage":{...}}
{"type":"error","message":"..."}
```

`tool_call` / `tool_result` have **no producers in M1** — they are defined now, and the frontend
renders them now, so that adding MCP in M2 is a producer change only, with no transport or UI
reshaping. This is the main thing M1 does to make M2 cheap.

## What was reused rather than rewritten

- `rag.chunk_text` — pure string ops, provider-agnostic, worth keeping. One fix: `start = end -
  chunk_overlap` can move *backwards* when the boundary backoff lands near `start`, looping
  forever. Guarded with `max(end - chunk_overlap, start + 1)`.
- The pypdf extraction block and the `pending→processing→ready|error` status machine.
- `core/security.py` bcrypt + PyJWT helpers — sound as written.

## Frontend

Next.js 16 App Router in `web/`. `route.ts` handlers proxy FastAPI so the JWT stays server-side.
Components: `ProviderPicker` (fed by `GET /api/v1/providers`, which calls `ollama.list()` live),
`ChatStream`, `ToolTrace`, `SourcePanel`, `DocumentUpload`.

`~/Downloads/juradi/klutest` 
carrying forward is its connection-manager shape (`{user_id: [sockets]}`), for M2's websocket
work - but do neglect

## Milestones

| # | Scope | Status |
|---|---|---|
| 1 | Run locally; Ollama + Claude selectable; security fixes; pyright; tests; Next.js UI | in progress |
| 2 | MCP server + MCP client as internal APIs; tool-calling; tool trace populated | `docs/jelena/future4.md` |
| 3 | Rate limiting, audit log, suspicious-activity policies (the brief's "firewall" ask) | not started |

Deferred by explicit decision: `docs/jelena/future3.md` (sentence-transformers embeddings),
`docs/jelena/future4.md` (MCP-first ordering). Jelena's own longer-term notes are in
`docs/jelena/future.md` and `future2.md` and remain untouched.

---

# Deployment


## 1. The fact that decides everything else

**Embedding is Ollama-only, and this app embeds on the write path.** Not just at upload —
`POST /tutor/interactions` embeds every completed lesson so recall works immediately after.
So the deployed backend cannot be "just Claude in the cloud". It needs a live embedder in
the same request, forever, or the tutor stops learning.

That single constraint eliminates most of the free-tier menu, because the free tiers that
are genuinely free are the ones that won't run a model server for you.

| Way out | Cost | Verdict |
|---|---|---|
| **Run Ollama beside the API** | `nomic-embed-text` is ~275 MB and embedding-only; comfortably under 1.5 GB RSS on 2 vCPU | **chosen** |
| sentence-transformers in-process | +~1 GB of torch. `nomic-ai/nomic-embed-text-v1.5` is the same model at the same 768 dims, so in principle no re-embedding — but the GGUF build Ollama serves is quantised, so the vectors are *close*, not identical. Mixing both in one index needs measuring first | fallback — `jelena/future3.md` |
| Hosted embedding API (Voyage, Cohere) | a fourth provider, a fourth key, and it breaks the shape of hard rule #2 | no |

Generation is the easy half: on any deploy, `DEFAULT_CHAT_PROVIDER=claude`. `llama3.1:8b`
took ~180 s for one sentence on your own machine; it has no place on a 2-vCPU host. Ollama
stays deployed **for embeddings only**, and the provider picker offers Claude alone.

## 2. Next.js integration — your stated concern

It is already solved, and this is worth knowing before comparing hosts.

The browser never talks to FastAPI. It talks to Next.js route handlers, which attach the
JWT from an httpOnly cookie server-side and forward to `API_BASE_URL` (`web/lib/api.ts:11`).
Consequences:

- **There is no CORS problem in production.** `BACKEND_CORS_ORIGINS` can stay empty.
- **There is no cross-origin cookie problem** — the only cookie is set by Next.js on its own
  origin, and `secure` is already derived from the request protocol, so HTTPS just works.
- **The entire frontend/backend wiring is one environment variable.** Change `API_BASE_URL`
  and the app moves.

So the integration question is not "how do I make them talk", it's only "how many boxes am
I paying for". Three shapes:

| Shape | Origins | Verdict |
|---|---|---|
| **One container: Next.js on the public port, FastAPI + Ollama on localhost** | 1 | **chosen.** One URL, one deploy, one log stream, zero network hops. Hugging Face Spaces exposes exactly one port (7860) — which fits this shape and no other |
| Next.js on Vercel, FastAPI elsewhere | 2 | works, but two deploys, two dashboards, and a public round-trip on every proxied call |
| FastAPI serving a static Next.js export | 1 | no — the route handlers are server-side by design; a static export deletes the thing keeping the JWT out of the browser |

### Why not Vercel, given you offered it

Vercel would work — the Hobby tier allows a 300 s function duration, which covers SSE
streaming from Claude comfortably. Three reasons it isn't the pick *for this project*:

- It solves the half you don't have a problem with. Next.js is the cheap, easy half; the
  awkward half is Ollama, which Vercel will never host.
- It splits one deploy into two for no gain, since nothing is cross-origin anyway.
- Hobby is **non-commercial use only** under Vercel's terms. A portfolio piece is a grey
  area you don't need to stand in.

Keep Vercel in mind for a project that is *only* Next.js. This one isn't.

## 3. Track A — free, now: one Docker image on Hugging Face Spaces

```text
  Space (CPU Basic — 2 vCPU, 16 GB RAM, free)
  ┌───────────────────────────────────────────────┐
  │  :7860  Next.js  (next start, standalone)     │ ← the only public port
  │           │ API_BASE_URL=http://127.0.0.1:8000│
  │  :8000  FastAPI + SQLite + sqlite-vec         │
  │           │                                   │
  │  :11434 Ollama — nomic-embed-text only        │
  └───────────────────────────────────────────────┘
                    │
              Anthropic API  ← generation
```

Why Spaces rather than a free PaaS: it is the one free tier that is *built* to run a model
next to a web app, it is where people expect an ML showcase to live, and CPU Basic
(2 vCPU / 16 GB) has no hourly cost. The catch, which you already anticipated in `TODO.md`:
**the 50 GB disk is ephemeral** — content is lost on restart or rebuild. Persistent storage
starts at $5/month for 20 GB. Hence seed-on-startup (§6).

### SQLite in deployment — the part you said was unclear

**SQLite in deployment is not a database question. It is a filesystem question.** There is no
server to run, no port to open, no credentials to rotate. `rag.db` is a file. So there are only
three things to decide, and all three have short answers here.

**1. Does the file survive a restart?**

| Where | Answer | What you do about it |
|---|---|---|
| Spaces, free tier | **No** — wiped on restart or rebuild | Seed on startup. Visitor uploads are deliberately temporary |
| Spaces + persistent storage | Yes | $5/month for 20 GB, if you want uploads to stick |
| VPS | Yes — an ordinary file on a volume | Nothing |

The ephemeral case sounds worse than it is, and **tier 1 is what defuses it**: once the corpus
exports and re-imports, the durable artifact is `model.json`, not `rag.db`. The database
becomes a cache you can rebuild, which is a much more comfortable thing to lose.

**2. Who is allowed to write to it?**

**One process. Never two.** WAL mode is already on (`app/core/db.py`), which gives many
concurrent readers alongside one writer — ample at showcase scale. What SQLite cannot do is be
shared between containers or replicas over a network. The practical rule:

> **Never scale the API past one replica.** That is the whole constraint.

On the Track B VPS this is a non-issue rather than a compromise — each project keeps its own
file and they never contend. The one resource worth sharing between projects is Ollama, and
that shares fine because it's an HTTP service.

**3. How do you back it up?**

```bash
sqlite3 rag.db ".backup /backups/rag-$(date +%F).db"
```

`.backup` is safe while the app is running; a plain `cp` of a live WAL database is not. Cron
that on the VPS. On the free Space there is nothing to back up by design.

**One property that pays off repeatedly:** `vec_chunks` lives *inside the same file*. The
vectors travel with the rows — copy `rag.db` and you have moved the entire application state,
embeddings included. That is also why the export format in §7 is cheap to build.

**When this stops being enough:** past roughly 100k chunks (brute-force scan, no ANN index) or
genuinely concurrent writers. Neither is close. The exit is Postgres + pgvector, which is
deliberately out of scope — see hard rule #1.

## 4. Track B — durable, ~€5/month: one VPS for all your projects

The same Dockerfile, later, when the showcase is not the only thing running:

```text
  One VPS
  ┌──────────────────────────────────────────────┐
  │  Caddy — automatic TLS, one subdomain each   │
  │    mcp-py.you.dev    → mcp-py_web:3000       │
  │    project2.you.dev  → project2_web:3000     │
  │    project3.you.dev  → …                     │
  ├──────────────────────────────────────────────┤
  │  ollama  ← ONE instance, shared by all of    │
  │            them on the internal network      │
  └──────────────────────────────────────────────┘
```

That shared Ollama is the whole argument. You run Ollama in several projects. Hosting it
once and pointing every backend at `http://ollama:11434` amortises the single most expensive
component across all of them. No PaaS lets you do that without paying per project.

Prices as of July 2026 — note Hetzner raised cloud prices during 2026, so re-check before
buying: **CX22** (2 vCPU, 4 GB, 40 GB NVMe) ≈ €4.49/month; **CAX11** (ARM) from ≈ €5.99/month,
Germany/Finland only. 4 GB is enough for embedding-only Ollama plus two or three small apps;
if you want several projects each with a chat model, size up rather than adding boxes.

## 5. The comparison you asked for — EC2 vs VPS vs PaaS vs free

Judged for *your* situation: several FastAPI + Next.js projects, Ollama in most of them,
no managed-cloud services in use.

| Option | ~Monthly | Fits Ollama? | Honest verdict |
|---|---|---|---|
| **Hetzner / similar VPS** | €4.50–6 | yes, shared across projects | **The right answer for the portfolio as a whole.** Cheapest per GB of RAM by a wide margin, and the only option where one Ollama serves every project |
| **HF Spaces, CPU Basic** | €0 | yes, per Space | **The right answer for this project today.** Free, ML-native, one port — but ephemeral disk, and one Space per project |
| Vercel Hobby | €0 | no | Excellent for Next.js alone. Non-commercial terms. Doesn't address your hard half |
| Render / Railway / Fly | €5–20 *per project* | awkward and separately billed | Fine for one project, multiplies badly at four |
| Oracle Cloud Always Free | €0 | yes, if you get capacity | Was the obvious free pick. **Oracle cut Always Free from 4 OCPU/24 GB to 2 OCPU/12 GB on 15 June 2026 with no announcement** — instances were shut down and users found out afterwards. Still generous; not something to put a portfolio on |
| **AWS EC2** | $12–20+ | yes | **Don't.** See below |

### Why EC2 is the wrong pick here — the conclusion you asked for

EC2 is not a bad product; it is the wrong product for this shape of work.

- **You pay AWS's premium for services you don't use.** AWS earns its price through RDS,
  SQS, Cognito, IAM, autoscaling. You use none of them. Strip those away and EC2 is a VPS
  with a worse price and more paperwork — VPC, subnets, security groups, EBS volumes, and
  an IAM model you must learn before the first deploy.
- **The cost is 2–4× for less machine.** A t4g.small is roughly $12/month before EBS and
  before egress. The €4.49 Hetzner box has more RAM and includes generous traffic. Egress
  in particular is where AWS bills quietly grow.
- **The free tier expires.** Twelve months, then full price — the opposite of what you want
  for portfolio projects that sit up for years.
- **It buys you nothing you asked for.** You wanted free-to-begin and simple. EC2 is neither.

The only thing that would change this: an employer requiring AWS on the CV. If that is the
real goal, say so and deploy *one* project there deliberately, as a demonstrated skill —
not all of them, and not this one first.

### The property that makes this low-risk

**Track A and Track B run the same image.** Spaces takes a `Dockerfile`; Docker Compose takes
the same `Dockerfile`. Moving from free to paid is a `docker compose up` and a DNS record —
no rewrite, no lock-in, no decision you have to get right today.

## 6. What must be built before any of this ships

Nothing here exists yet. Roughly in dependency order:

- [ ] **`Dockerfile`**, multi-stage: `node:22` builds `web/` → `python:3.11-slim` runtime with
      `uv sync --no-dev`, the Ollama binary, and the Node runtime for `next start`.
- [ ] **`output: "standalone"`** in `web/next.config.ts` — without it the image carries all of
      `node_modules`.
- [ ] **`start.sh`** — `ollama serve &`, wait for `:11434`, `ollama pull nomic-embed-text`
      (or bake it in at build time — 275 MB, and it removes a slow first boot), then uvicorn
      on `:8000` and `next start` on `:7860`.
- [ ] **Bake or pull, decide by measuring.** Ephemeral disk means a pulled model re-downloads
      on every restart. Baking costs image size; pulling costs cold-start seconds.
- [ ] **Production secrets.** `ENVIRONMENT=production` makes `config.py:_check_secrets` fail
      fast on placeholders — that is deliberate. Space secrets needed: `SECRET_KEY`,
      `FIRST_SUPERUSER_PASSWORD`, `ANTHROPIC_API_KEY`. Plus `DEFAULT_CHAT_PROVIDER=claude`,
      `API_BASE_URL=http://127.0.0.1:8000`.
- [ ] **`/health` must report embedding readiness**, not just sqlite-vec. On a cold Space the
      API can be up seconds before Ollama can embed, and the current check won't notice.
- [ ] **Providers route on a chat-model-less Ollama.** `GET /providers/` calls `ollama.list()`
      live; deployed, that list is one embedding model. Confirm the picker degrades to
      Claude-only cleanly rather than offering an unusable option.
- [ ] **Rate limiting — promoted, not optional.** A public URL with document upload and paid
      Claude calls behind it is an open invoice. This is the piece of Milestone 4 that must
      land *before* the deploy, not after.

## 7. The model — what it is, and what the learner can download

Confirmed with Jelena 2026-07-28: **"the model" is the learner's corpus** — the lessons Claude
generated, plus metadata, indexed for retrieval. "Training" is the act of building it up
through the tutor. JSON is the export format, and it is the source of truth.

She also asked for **GGUF as a download option**, and asked me to say so here if I disagree or
see a better shape. I do not disagree with wanting it. But it needs one distinction made
plainly, because it decides how much complexity enters the app:

> **JSON is data. GGUF is weights.** They are not two serialisations of one thing. You cannot
> convert lessons into GGUF by writing them out differently — the only road from a corpus to a
> `.gguf` runs through **training a neural network**. That is a different machine, a different
> hour, and a different discipline.

So rather than one format or two, the honest design is **three tiers**, each cheap, each
truthful about what it is. Only tier 1 is required; tiers 2 and 3 are small additions on top
of it, and neither puts training inside the app.

| Tier | Artifact | What it actually is | Cost to build | Runs where |
|---|---|---|---|---|
| **1** | `model.json` | **The model.** Lessons + metadata, lossless, re-importable | small | this app — import, seed, share |
| **2** | `Modelfile` | A **runnable** Ollama model: a base model carrying the learner's lessons | small | `ollama create` on any machine |
| **3** | `train.jsonl` + recipe | **Training input**, not a model | small | free Colab GPU → a real `.gguf` |

### Tier 1 — `model.json`, the source of truth (build this regardless)

- [ ] Define the export: lessons, their terms/topics, timestamps, which provider taught each,
      and the app + embedding-model versions. **Not** the vectors — they are reproducible from
      the text and would bloat the file, and hard rule #5 means they are only valid for one
      embedding space anyway.
- [ ] `GET /api/v1/tutor/model/export` → the file. Owner-scoped, same rule as everything else.
- [ ] `POST /api/v1/tutor/model/import` → re-embeds on the way in. This is what makes the
      format real rather than decorative: **export and import are one code path in opposite
      directions**, and seeding is just import with fixture files. A visitor can download the
      thing they watched being built, and load it back.

### Tier 2 — `Modelfile`, my recommended addition

This is the piece I'd add, and the reason is that it costs almost nothing and produces
something that **actually runs**:

```text
FROM llama3.1:8b
SYSTEM """You are the learner's model. You have studied: …
[the lessons, assembled from model.json]"""
MESSAGE user      how does a computer compare meaning between two sentences?
MESSAGE assistant [the lesson that was taught]
```

`ollama create my-model -f Modelfile` and it exists — `ollama run my-model`. Seconds, no GPU,
no training. `SYSTEM`, `MESSAGE`, `FROM` and `ADAPTER` are all current Modelfile instructions.

It is honest about what it is: a **prompted** model over a base, not a fine-tuned one. That
honesty is worth more in a showcase than a button that overclaims. It also gives the download
somewhere to go that isn't a JSON file the user cannot do anything with.

### Tier 3 — the GGUF path, kept real but staged outside the app

The app should produce the **input** and the **recipe**, and never run the training:

- [ ] `GET …/model/export?format=jsonl` — the same lessons as chat-format training pairs.
      Perhaps twenty lines on top of tier 1.
- [ ] A documented notebook recipe in `.claude/rules/MANUAL.md`.

The numbers, checked 2026-07-28: Unsloth fits a LoRA fine-tune of Llama 3.1 8B **in 8 GB of
VRAM** at 2K context, and its export merges the adapter, converts through llama.cpp and
quantises — an 8B Q4\_K\_M lands around **4.6 GB**. The resulting GGUF, or a LoRA adapter,
comes *back* into tier 2 as `FROM ./my-model.gguf` or `ADAPTER ./adapter`. The loop closes.

**Hardware reality, measured on this machine:** Intel integrated graphics, no NVIDIA GPU,
12 cores, 23 GB RAM. That is why `llama3.1:8b` took ~180 s for one sentence, and it means
**fine-tuning cannot run here at all**. The path is a free Colab or Kaggle T4 (16 GB), which
clears the 8 GB requirement comfortably. Plan around that rather than discovering it mid-run.

**And keep GGUF off the deployed Space.** A 4.6 GB artifact on a free tier with an ephemeral
50 GB disk and shared bandwidth is a bad trade. Tier 3 is a local workflow; tiers 1 and 2 are
what the public demo hands out.

### The thing worth saying out loud in the UI

There is a real idea underneath this, and stating it is what turns a download button into a
demonstration of understanding:

> **Fine-tuning teaches style. Retrieval teaches knowledge.**

Twenty lessons will not reliably put facts into 8B weights — it will teach the model to
*sound* like the learner's material. So the GGUF is the learner's model's **voice**, and the
JSON corpus behind the vector index is its **memory**. They are complementary, not rival
formats, and that is exactly why tier 1 stays the source of truth no matter how far tier 3
goes. Same place as the semantic-similarity note in §8 — planned UI copy, not built yet.

### Seeding and accounts on a public deploy

- [ ] Seed on startup **only when the corpus is empty**, so a restart on ephemeral disk
      restores a non-empty demo without duplicating on a persistent one.
- [ ] Fixtures are `model.json` files run through the import path — no separate seeding code.
- [ ] Visitors need accounts, and there is **no public signup route** by design. Either a
      shared read-only demo login, or signup gated behind the rate limiting from §6. Decide
      before launch, not during.

## 8. Two notes recorded here on your instruction

**Semantic similarity, said plainly in the UI.** You want the app to tell the user, in an
appealing format on the web, that recall works by *semantic* similarity rather than by a
mathematical string comparison. Recorded as planned UI copy, not built: cosine similarity is
the more common implementation and can come later, but not before ~20 further sessions. Worth
saying accurately when it is built — the retrieval *does* use vector distance; the contrast
that matters is against the **word-overlap** scoring this replaced, which scored 0.111 on a
real question and gave up below its own 0.2 threshold, where retrieval put the right lesson
first at 0.519.

**The `PATCH /users/me` privilege escalation belongs to the hardening milestone.** Per your
note in `TODO.md`. The defect itself is fixed (`.claude/rules/other_agent.md` #2 — `UserUpdateMe` no longer
inherits `UserBase`), so what belongs in Milestone 4 is the *class* of problem: authorisation
review, audit logging of privilege changes, and the anonymous/abuse policies — which the
public deploy in §6 makes concrete rather than theoretical.

IMPORTANT
jelena: - UI for making new user (registration). I want to have oidc (docs/jelena/OIDC.md)-federation. Please  make UI and one user.