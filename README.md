# AI tutor answers, embedded and indexed — a model built from your lessons and your own documents, registered as a tool through an internal MCP server and client

### Why this repository might interest you

| If you are… | What to look at |
|---|---|
| **learning RAG** | a complete pipeline with nothing hidden — chunking, embedding, a `vec0` vector index, retrieval, citations, and the honest limits of each |
| **learning MCP** | a real server with five tools, a client speaking the actual protocol, and an agent loop where the *model* chooses what to call — visible in the UI as it happens |
| **building agents** | tool calling on **both** Claude and Ollama, behind one provider-neutral interface, with the trap that took longest documented |
| **writing async Python** | PEP 525 async generators as an ingestion pipeline, streaming SSE, and one place where coroutines genuinely earn their keep rather than decorate |
| **doing full-stack** | FastAPI + SQLModel behind Next.js 16 App Router, with the JWT never reaching the browser |
| **evaluating engineering** | 272 tests, `pyright` strict, and a `/status` page where the app *probes* its own capabilities instead of claiming them |

**The stack, in one line:** FastAPI · SQLModel · SQLite + `sqlite-vec` · Ollama ·
Anthropic Claude · Model Context Protocol · Next.js 16 · TypeScript strict · Docker ·
async Python throughout.

---

> ## ⚠️ Honest status
>
> A personal learning and showcase project, built in the open. It runs, it is tested,
> and everything described as working genuinely works — but it is **not finished and not
> production software.**
>
> **What works end to end:** the RAG pipeline, the tutor, the learning channel, an MCP
> server with five tools and an agent loop on Claude *and* Ollama, registration and
> login, a free tier, model export as JSON and as a runnable Ollama `Modelfile`, backup
> and restore, and the whole thing in Docker.
>
> **What does not:** it is not hosted anywhere public, there is **no rate limiting**,
> there are **no database migrations**, and nobody has clicked several of the newest
> screens. See *Not working yet* and *Known limits* — nothing is hidden there.

---

## What you need

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/)
- **Node 20+**
- **[Ollama](https://ollama.com)**, running locally — this does the embedding, and it is
  required. Embedding always runs on your own machine.
- An **Anthropic API key**, optional — only if you want Claude as the answering model.

```bash
ollama pull nomic-embed-text        # required: the embedding model

cp .env.example .env                # then edit it — see the comments inside
uv sync --extra dev
uv run fastapi dev app/main.py      # API on http://localhost:8000

cd web && npm install && npm run dev # UI on http://localhost:3000
```

**Create an account on the sign-in page**, or use the admin account created on first
startup from `.env` — see `.env.example` for what to set. Registration can be closed with
`OPEN_REGISTRATION=false` on a deployment that has no rate limiting yet.

A fresh install seeds itself with six lessons on embeddings, RAG, chunking, vector search,
tool calling and MCP — so recall, the tool trace and both downloads work on the first
visit rather than showing an empty room.

### Or run the whole thing in Docker

One command instead of two terminals, and it survives a reboot. It uses the
Ollama already running on your machine, so nothing is downloaded twice and
generation stays local.

```bash
docker compose up -d --build     # build and start — http://localhost:7860
docker compose logs -f           # watch it
docker compose stop              # stop it, keep the data
docker compose start             # start it again, in seconds
```

The database lives in a named Docker volume, so `docker compose down` keeps it
and only `docker compose down -v` deletes it. A second service,
`docker compose --profile isolated up -d --build app-isolated`, runs the same
image completely self-contained — its own Ollama inside the container — which
is what a server would run.

---

## Pages

| Page | Status | What it does |
|---|---|---|
| `/` | ✅ available | Sign in, upload documents, ask questions. The answer streams in word by word, with a panel showing which pieces of your text it came from. |
| `/status` | ✅ available | What this app can do, checked as the page loads — plus the things it examined and deliberately refused to build. |
| `/tutor` | ✅ available | Ask the tutor to explain a topic. Every lesson is saved and indexed. "My model" then answers new questions from your own lessons only, and tells you honestly when it hasn't been taught something. |

Both pages work. Some *features* on them do not — listed below.

## Backend API — FastAPI

Runs on `http://localhost:8000`. Interactive docs at `/docs`.
`Auth` means a bearer token is required; get one from `POST /login/access-token`.

| Method | Path | Auth | What it does |
|---|---|:--:|---|
| `GET` | `/health` | – | Is the app alive, and did the vector extension load |
| `POST` | `/api/v1/users/signup` | – | **Create an account.** The only unauthenticated write |
| `GET` | `/api/v1/public/signin-info` | – | What the sign-in page shows before anyone is signed in |
| `POST` | `/api/v1/login/access-token` | – | Sign in (the `username` field is your email) |
| `GET` | `/api/v1/login/test-token` | ✓ | Check a token is still valid |
| `GET` | `/api/v1/users/` | admin | List users |
| `POST` | `/api/v1/users/` | admin | Create a user |
| `GET` | `/api/v1/users/me` | ✓ | Your own profile |
| `PATCH` | `/api/v1/users/me` | ✓ | Edit your own profile — cannot change permissions |
| `GET` | `/api/v1/users/{id}` | ✓ | Read a user |
| `PATCH` | `/api/v1/users/{id}` | admin | Edit a user, including permissions |
| `DELETE` | `/api/v1/users/{id}` | admin | Delete a user |
| `GET` | `/api/v1/documents/` | ✓ | Your documents, newest first |
| `POST` | `/api/v1/documents/upload` | ✓ | Upload `.txt` `.md` `.csv` `.pdf`; indexing runs in the background |
| `GET` | `/api/v1/documents/{id}` | ✓ | One document |
| `DELETE` | `/api/v1/documents/{id}` | ✓ | Delete a document and everything indexed from it |
| `POST` | `/api/v1/query/` | ✓ | Ask a question, get the whole answer at once |
| `POST` | `/api/v1/query/stream` | ✓ | Ask a question, get the answer as it is written |
| `POST` | `/api/v1/query/agent` | ✓ | Let the model choose which tools to run, and watch it work |
| `POST` | `/api/v1/tutor/teach` | ✓ | The tutor explains a topic, streamed |
| `POST` | `/api/v1/tutor/learn` | ✓ | Push pieces of learning as they happen — embedded on arrival, returns the model's state |
| `GET` | `/api/v1/tutor/learn` | ✓ | The model for one session, read back from the database |
| `POST` | `/api/v1/tutor/interactions` | ✓ | Save one lesson into your model |
| `POST` | `/api/v1/tutor/recall` | ✓ | Answer from your own lessons only |
| `GET` | `/api/v1/tutor/stats` | ✓ | How many lessons and topics your model holds |
| `GET` | `/api/v1/tutor/model/export` | ✓ | Download your model as a JSON file |
| `GET` | `/api/v1/tutor/model/modelfile` | ✓ | Download a **runnable** Ollama `Modelfile` built from your lessons |
| `POST` | `/api/v1/tutor/model/import` | ✓ | Load a model file back in |
| `POST` | `/api/v1/tutor/learn/similar` | ✓ | What in your own model resembles a passage — over the learning index |
| `POST` | `/api/v1/embeddings/` | ✓ | Embed a list of strings and see the vectors |
| `GET` | `/api/v1/embeddings/models` | ✓ | Local models that can embed — asked by **capability**, not guessed from the name |
| `GET` | `/api/v1/quota/` | ✓ | What you have used of the free tier, and what is left |
| `GET` | `/api/v1/admin/activity` | admin | Sign-ups, sign-ins, uploads and lessons — per account |
| `GET` | `/api/v1/providers/` | ✓ | Which models you can currently choose from |
| `GET` | `/api/v1/keys/anthropic` | ✓ | Do you have a key on file, and does the app have one of its own |
| `PUT` | `/api/v1/keys/anthropic` | ✓ | Hand over your own Anthropic key — checked, hashed, plaintext dropped |
| `DELETE` | `/api/v1/keys/anthropic` | ✓ | Forget it |
| `GET` | `/api/v1/status/` | ✓ | What the app can do — probed live, not read from a list |
| `GET` | `/api/v1/mcp/tools` | ✓ | The MCP tool catalogue — what a model would be offered |
| `POST` | `/api/v1/mcp/call` | ✓ | Run one MCP tool yourself, as you |

`GET /api/v1/documents/` also tells you `indexed_with` (which embedding model
produced a document's vectors) and `searchable` — see *Changing the embedding
model* below.

## Frontend API — Next.js

Runs on `http://localhost:3000`. These sit between the browser and FastAPI so your
login token stays on the server and never reaches the browser.

| Method | Path | Talks to |
|---|---|---|
| `POST` `DELETE` `GET` | `/api/auth` | sign in · sign out · am I signed in |
| `POST` | `/api/chat` | `/query/stream`, or `/query/agent` when tools are on |
| `GET` `PUT` `DELETE` | `/api/keys` | your own Anthropic key |
| `GET` `POST` | `/api/documents` | list documents · upload |
| `GET` | `/api/providers` | `/providers/` |
| `GET` | `/api/status` | `/status/` — what works, checked at request time |
| `POST` | `/api/tutor/teach` | `/tutor/teach` |
| `GET` `POST` | `/api/tutor/learn` | `/tutor/learn` — read the model back · the upward channel |
| `POST` | `/api/tutor/interactions` | `/tutor/interactions` |
| `POST` | `/api/tutor/recall` | `/tutor/recall` |
| `GET` | `/api/tutor/stats` | `/tutor/stats` |

---

## Not working yet

Stated plainly, because some of it is visible in the app and would otherwise look broken.

| Feature | What you see | Why |
|---|---|---|
| **Delete a document** | No button | `DELETE /api/v1/documents/{id}` works; the UI does not offer it. |
| **Admin screens** | None | There is registration and login, but no screen for managing other people's accounts. `GET /admin/activity` answers *"is anyone using this"* over HTTP or from a script. |
| **Rate limiting** | Nothing stops you | The most important gap on this page. A free tier limits what **one account** can do; nothing limits how many accounts appear. |
| **Migrations** | — | Schema comes from `create_all`, which adds missing *tables* and never missing *columns*. Fine at this scale, and the reason `User` has no timestamp. |
| **Hosting** | Runs on your machine | Nothing is deployed publicly. It runs locally and in Docker; a Cloudflare tunnel makes it reachable when wanted. |

Things listed here in earlier versions that **now work**: Ollama tool calling, the
sign-up screen, both model downloads, and the browser-to-model learning channel.

### Using your own Anthropic key

Claude usage can be billed to **your** Anthropic account rather than the app's.
Paste a key into *Claude access* on the main page and:

- only a one-way hash and the last four characters are stored — neither can call
  Anthropic;
- the key itself stays in your browser session, is sent with each request, and is
  dropped when you close the browser or sign out;
- because it is never written down, you add it again next session.

To be exact: the key passes through the server's memory when it makes the call —
it has to, that is what making the call means. What the app never does is *keep*
it.

### Changing the embedding model

Embedding is always local, and *which* local model is yours to choose:
Ollama by default, or sentence-transformers with
`uv sync --extra local-embed` (~2 GB of torch, which is why it is optional).

Switching does not corrupt anything. Each vector width gets its own index, so
nothing is overwritten. What it does do is make everything indexed under the
old model **unsearchable** — vectors from two models are not comparable, so
search cannot reach them. The app says so rather than quietly returning
nothing: those documents are marked *not searchable* in the list. To put them
back:

```bash
uv run python -m app.scripts.reembed --dry-run   # what would change
uv run python -m app.scripts.reembed             # do it
```

It re-embeds the passages already stored, so it works even though this app
keeps no copy of your original file.

### What the MCP tools do

These are what Claude calls when you tick *Let the model use tools*, and you can
run them by hand through `POST /api/v1/mcp/call`. Everything they return is
scoped to you — no tool takes a user or owner argument, and none can be given
one.

| Tool | What it does |
|---|---|
| `search_documents` | Semantic search across your documents and lessons |
| `list_documents` | What you own, each marked *lesson* or *upload* |
| `get_document` | One document, as the chunks it was indexed into |
| `tutor_stats` | How much your model holds: lessons, topics, chunks |

## Known limits

- **Local models are slow on ordinary hardware.** On a machine without a GPU, an 8B
  model can take minutes for one answer. Choose a smaller model, or use Claude.
- **"Grounded" means "something was found", not "the answer is correct."** The search
  always returns the nearest matches, however far away they are. In practice the model
  handles this well and says when your lessons don't cover a question — but the flag
  itself is weaker than it sounds.
- **No database migrations.** The schema is created on startup. Fine at this size.

---

## Where this could go next

Not a wishlist — each of these is a real gap with a known first step. They are roughly
ordered by how much they would teach someone working through them.

**Retrieval quality, which is where most RAG projects stop too early**

1. **A relevance threshold, or a reranker.** Nearest-neighbour search always returns *k*
   results, however irrelevant. A cross-encoder reranking the top 20 down to 5 is the
   standard fix and would make the `grounded` flag mean something.
2. **Hybrid search.** Vectors miss exact strings — product codes, error numbers, names.
   BM25 alongside the vector index, fused, is measurably better than either alone.
3. **Chunking that respects structure.** Fixed 1000-character windows cut through
   headings and tables. Splitting on document structure changes retrieval more than
   swapping the embedding model does.
4. **An evaluation set.** Twenty questions with known-correct passages, scored on every
   change. Without it, every "improvement" here is a guess — including the ones already
   made.

**The model layer**

5. **A second embedding provider actually exercised.** `sentence-transformers` is written
   and has never run; per-width indexes exist to make the swap safe.
6. **Fine-tuning, honestly framed.** The app already exports training pairs. A LoRA run
   on a free Colab T4 would produce a real adapter — and the interesting part is
   measuring how little it helps with *facts*, which is the point.
7. **Quantisation and local speed.** Why an 8B model takes minutes on a CPU, and what
   actually changes it.

**Agents and MCP**

8. **The outward transport.** The MCP server is in-process. Mounting Streamable HTTP
   would let Claude Desktop consult your corpus — blocked on federated identity, which is
   the honest reason it is not built.
9. **Multi-step tool planning.** The loop is capped at five rounds and has no memory
   between questions.
10. **Tool-use evaluation.** Eighteen of thirty local models here can call tools. Which
    call them *well* is a different question, and nobody measured it.

**Engineering**

11. **Rate limiting.** The largest real gap.
12. **Migrations**, the moment any table needs a new column.
13. **Ingestion progress.** The streaming sink already yields a running count that nothing
    reads; the browser channel that would carry it now exists.
14. **Scheduled backups.** The script and a verified restore exist; nothing calls them.
15. **Federated login**, which unblocks 8.

---

## Where ML writing bends the truth — and what this repo does instead

A learning project is a good place to be exact about things the field is currently
casual about. Each of these was measured here, not repeated from somewhere else.

**A prompt on an embedding model changes nothing. Changing the model changes everything.**

Deriving an embedding model with a `SYSTEM` prompt was measured against its base here:
*identical vectors, maximum absolute difference 0.0.* An embedding model has no
generation step to read a prompt, so the prompt is stored and read by nothing. The route
says exactly that in its reply — `note_affects_vectors: false` — rather than letting a
"custom model" badge imply a difference that is not there.

The opposite is where the real risk sits, and it is a property of **embedding models
themselves, not of this app**. Swap the embedding model and your results change: different
vectors, different nearest neighbours, different passages retrieved, a different answer to
the same question. No application can paper over that — vectors from two models are not
comparable, so material indexed under the old one becomes *unreachable* rather than merely
worse.

Which is why the version matters as much as the name. `nomic-embed-text:v1.5` is a
promise; `nomic-embed-text` is whatever that tag points at today. Pinning it means an
upstream release cannot silently change the numbers underneath an index that has no way
to survive the change — and if you do change it deliberately,
`uv run python -m app.scripts.reembed` is the way back.

The downloadable `Modelfile` carries your lessons in the base model's *context*. It runs,
it answers in your material, and it changes no weights. The file's own header says this in
the first paragraph. *Fine-tuning teaches style; retrieval teaches knowledge* — and
conflating them is how demos overpromise.

**"Grounded" usually means "the search returned something."** It does here too, and the
README says so. A `vec0` KNN returns the *k* nearest vectors whether or not any of them
are relevant. Distance is not relevance, and a green badge that only means "a query ran"
is a badge worth distrusting.

Change the embedding model and old documents become unreachable — not worse, unreachable.
This app marks them rather than quietly returning them, because a ranking mixed across two
models is meaningless *and* plausible, which is the worst combination available.

**Benchmarks are usually run once.** The numbers here — 475 MB peak while embedding, 18
of 30 local models able to call tools, 0.51 retrieval distance on a seeded question — were
each produced by running the thing and reading the output, and the command is in the
repository.

`/status` **probes** capabilities rather than listing them, and where something is claimed
but unverified, it says so.

**Refusals are usually hidden.** `/status` has a fourth state — *explored, refused* — for
capabilities examined and deliberately not built, with the reason. A tool that makes its
own LLM call, a search that merges embedding spaces, an `owner_id` parameter a model could
choose. Building the easy version of any of them would have made the rest mean less.

---

## How it is built

| Part | Choice |
|---|---|
| API | FastAPI + SQLModel, async throughout |
| Database | SQLite — no server, no Docker, runs anywhere |
| Vectors | `sqlite-vec`, stored in the same file as the data |
| Embeddings | Ollama `nomic-embed-text` by default, always local, swappable |
| Answers | Ollama **or** Claude, chosen per request |
| Frontend | Next.js 16 (App Router) |
| Types | `pyright` strict, TypeScript strict |

```bash
uv run pytest      # 272 tests, no network needed
uv run pyright     # strict type checking
```

**This README is the documentation.** Everything a user or a developer needs to
run, use and extend the app is on this page.

There is a second layer — the plans, the reasoning, the decisions taken and the
ones deliberately refused — and it is deliberately **not** in this repository. A
repository carries the code and the guide to running it; the record of how the
work was done is a working document, not a published one.
`.claude/rules/SUMMARY.md` is the map of it, and the only part kept here.

## What I am proud of

**The MCP layer is real.** A server, a client speaking the actual protocol, and
an agent loop where the model picks its own tools — with every call shown in the
interface as it happens. No tool can be handed a user, so a model choosing badly
still cannot reach anyone else's material.

**Retrieval is honest about its limits.** One embedding space per index, results
from two models never mixed to make a search look richer, and anything the
current model cannot reach is marked unreachable rather than quietly returning
nothing.

**The app measures itself.** `/status` probes what it claims instead of listing
features, and keeps a category for things examined and deliberately refused.

**Both ends of the pipeline are coroutines, and both are bounded.** A large
upload costs one batch of memory, not a whole document. In the browser the
stream has one owner, so it cannot be half-consumed by a component that
unmounts — and what is kept is the current answer and nothing else.

**The direction underneath it:** what you are taught accumulates into a corpus
that is *yours*, exportable and portable, on the way to a model that keeps
learning from its own use rather than being fixed when it was trained.

## A note on the data

Everything in the demo content is invented. Please don't put real, personal, or
sensitive documents into it — it is a learning project, and it has no privacy
guarantees beyond keeping each account's documents separate.
