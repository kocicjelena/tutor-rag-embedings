# mcp-py

A small app for learning, built to show three things working together: **LLM, RAG and MCP.**

You upload a document, or you learn something with the tutor. The text is turned into
vectors locally and stored. When you ask a question, the app finds the most relevant
pieces of *your own* material and asks a language model to answer using only those,
with citations. You choose who answers — a local Ollama model, or Claude — per request.

The tutor is the interesting half. You ask it to explain something, it teaches you, and
every exchange is indexed. Over time that becomes **your model**: a corpus of what you
have been taught, which the app can answer from and which you can export and download.

---

> ## ⚠️ Work in progress
>
> This is a personal learning and showcase project, built in the open. It runs, it is
> tested, and the parts marked *available* below genuinely work — but it is **not
> finished and not production software.**
>
> The **MCP layer works end to end**: an MCP server with four tools, a Python
> client that speaks the real protocol, and an agent loop where Claude decides
> which tools to run — with every call shown in the app as it happens.
>
> What is not finished: Ollama cannot call tools yet (Claude can), there is no
> sign-up screen, and it is not hosted anywhere public — it runs locally, and in
> Docker, on your own machine. See *Not working yet* below — nothing there is
> hidden.
>
> Expect things to change. There are no migrations and no rate limiting yet.

---

## What you need

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/)
- **Node 20+**
- **[Ollama](https://ollama.com)**, running locally — this does the embedding, and it is
  required. Anthropic does not offer an embeddings API, so this part is always local.
- An **Anthropic API key**, optional — only if you want Claude as the answering model.

```bash
ollama pull nomic-embed-text        # required: the embedding model

cp .env.example .env                # then edit it — see the comments inside
uv sync --extra dev
uv run fastapi dev app/main.py      # API on http://localhost:8000

cd web && npm install && npm run dev # UI on http://localhost:3000
```

There is no public sign-up. The accounts are created on first startup from `.env` —
see `.env.example` for what to set.

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
| `POST` | `/api/v1/tutor/interactions` | ✓ | Save one lesson into your model |
| `POST` | `/api/v1/tutor/recall` | ✓ | Answer from your own lessons only |
| `GET` | `/api/v1/tutor/stats` | ✓ | How many lessons and topics your model holds |
| `GET` | `/api/v1/tutor/model/export` | ✓ | Download your model as a JSON file |
| `POST` | `/api/v1/tutor/model/import` | ✓ | Load a model file back in |
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
| `POST` | `/api/tutor/interactions` | `/tutor/interactions` |
| `POST` | `/api/tutor/recall` | `/tutor/recall` |
| `GET` | `/api/tutor/stats` | `/tutor/stats` |

---

## Not working yet

Stated plainly, because some of it is visible in the app and would otherwise look broken.

| Feature | What you see | Why |
|---|---|---|
| **Tools with Ollama** | The checkbox works only with Claude | Claude can call tools; the Ollama path is not written yet. Picking Ollama with tools on returns a clear message rather than failing quietly. |
| **Download / upload your model** | No button anywhere | The API works and is tested, but the frontend does not reach it yet. For now it is usable only with the API directly. |
| **Delete a document** | No button anywhere | Same: `DELETE /api/v1/documents/{id}` works, the UI does not offer it. |
| **Managing users** | No screen at all | User accounts are created from `.env` at startup. There is no sign-up page and no admin screen. |

Also missing, and planned: Ollama tool calling, a sign-up screen with federated
login, rate limiting, and deployment.

**The largest gap is not on that list, because you cannot see it.** The browser
store and the backend pipeline are not joined up yet. The design is that the
front end drives the work rather than merely displaying it: results are produced
by asynchronous generators, piped into coroutines that process them, and the
outcome is held in React context — so the context is where a learning model is
assembled and refined, and where the parts that turn out not to matter are
dropped rather than kept forever. Today each half exists on its own: the backend
streams and the store records, but the loop between them is not closed.

**And the corpus is not yet a tool.** What you are taught is searchable material
now; the intention is that your own model becomes something a model can *call* —
a tool in its own right, offered over MCP alongside the four that exist, so an
agent can consult what you have learned rather than only what you have uploaded.
That is the point where the tutor stops being a feature of this app and starts
being something you own and can take elsewhere.

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

Embedding is always local — Anthropic has no embeddings API — but *which* local
model is yours to choose: Ollama by default, or sentence-transformers with
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
uv run pytest      # 177 tests, no network needed
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

Three things in here are further along than a learning project usually gets. The
**MCP layer is real** — a server, a client speaking the actual protocol, and an
agent loop where the model chooses its own tools while every call is shown in
the interface as it happens — and no tool can be handed a user, so a model
choosing badly still cannot reach anyone else's material. The **retrieval layer
is honest about its own limits**: each vector index holds exactly one embedding
space, results from two models are never mixed to make a search look richer, and
anything the current model cannot reach is marked unreachable instead of quietly
returning nothing. And the app **reports on itself by measuring**, not by
listing features — `/status` probes what it claims, and keeps a category for
things that were examined and deliberately refused.

A fourth thing is quieter but it is the reason this runs on ordinary hardware:
**both ends of the pipeline are coroutines, and both are bounded.** Ingestion is
an asynchronous generator that is fed chunks, embeds them a batch at a time and
flushes what is left when it is closed, so a large upload costs one batch of
memory instead of a whole document — and the delete that clears a document's old
vectors was lifted out of it, because doing that per batch would have kept only
the last one, silently and with no error. In the browser the streaming answer is
drained by a single action inside the React provider rather than by whichever
component happens to be on screen, so the stream has one owner and cannot be
half-consumed by a component that unmounts. What the browser keeps is bounded on
purpose: the current answer and nothing else — a new question clears the last
one, nothing is copied into local storage, and the durable copy stays on the
server, where it was already indexed.

The direction underneath all of it is the part I care about most: the tutor is
built so that what you are taught accumulates into a corpus that is *yours*,
exportable and portable, on the way to a model that keeps learning from its own
use rather than being fixed at the moment it was trained.

## A note on the data

Everything in the demo content is invented. Please don't put real, personal, or
sensitive documents into it — it is a learning project, and it has no privacy
guarantees beyond keeping each account's documents separate.
