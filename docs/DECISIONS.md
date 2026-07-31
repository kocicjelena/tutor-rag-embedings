# Decided not to build

Written 2026-07-31 at Jelena's request: a record of the things we chose **not**
to code, not to expose as an API, and not to put in CI — with the reason, and
whether it is closed for good or merely postponed.

The point of this file is to stop future sessions rediscovering the same
arguments. If you are about to add something listed here, read the row first;
if the reasoning no longer holds, change it deliberately and say so.

Three columns of status:

| | |
|---|---|
| 🔒 **Closed** | Decided against. Changing it needs a new reason, not a new mood |
| ⏸ **Later** | Wanted, deliberately deferred, with a trigger for when |
| ⚠️ **Gap** | Nobody decided. It is simply missing, and probably should not be |

---

## Architecture — closed

| Decision | Why | |
|---|---|---|
| **No OpenAI, `pgvector`, or `psycopg`** | Removed deliberately at Milestone 1. Ollama and Claude are the only permitted providers | 🔒 |
| **No "Claude embeddings" provider** | Anthropic ships no embeddings API. It does not exist to add | 🔒 |
| **Embedding is never user-selectable per request** | Vectors from two models are not comparable, so a per-request choice corrupts the index rather than offering one. Configurable at deploy, not at request | 🔒 |
| **Never union two vector indexes to "find more"** | Distances from different embedding models are not on a common scale. The ranking would look fine and mean nothing. Mark unsearchable documents instead — Jelena's decision, 2026-07-31 | 🔒 |
| **No MCP tool takes an owner** | A tool's arguments are chosen by the model, so `owner_id` as a parameter is attacker-influenced input, not identity | 🔒 |
| **No MCP tool generates text** | An agent already has a model. A tool making its own LLM call nests an unattributable generation inside the first, hides its cost, and makes the trace panel a lie | 🔒 |
| **`vectors.search()` never gets an optional-owner overload** | That signature *is* the tenant boundary. An overload reopens the cross-tenant leak | 🔒 |
| **`UserUpdate` never inherits `UserBase`** | Inheriting exposes `is_superuser` to `PATCH /users/me` and lets any user self-promote | 🔒 |
| **No structured / tabular ingestion** | Document-oriented only, agreed at the start. A second data path doubles the surface for no demo value | 🔒 |
| **No Alembic migrations** | Schema comes from `create_all`. Fine at showcase scale. The consequence is real and lived with: new *tables* appear on restart, new *columns* never do — which is why `TutorLesson` is its own table and `indexed_with` is read from chunk rows | 🔒 |
| **No ANN index on the vectors** | Brute-force scan is fine below ~100k chunks. Nowhere near | 🔒 |
| **Never more than one API replica** | SQLite has one writer. This is a hard constraint, not a tuning choice | 🔒 |
| **Fine-tuning never runs inside the app** | No NVIDIA GPU here, and the free Space has none either. The app produces training input; a Colab/Kaggle T4 does the run | 🔒 |

## API surface — deliberately not added

Each of these was considered and rejected. They are the ones most likely to be
"helpfully" added back.

| Not built | Why not | |
|---|---|---|
| **Any route that returns an Anthropic key** | The whole guarantee is that the app cannot produce a usable key. A read route would end it — including a "masked" one, which invites a real one later | 🔒 |
| **An encrypted-key column** | Reversible means the server can read every user's key. That is precisely what BYOK avoids | 🔒 |
| **`owner` field on `MCPCallRequest`** | Same reasoning as tool arguments: it arrives from outside and cannot be trusted as identity | 🔒 |
| **`POST /documents/{id}/reembed`** | Re-embedding is an *operator* action across all users, run maybe once a year after changing the embedding model. As a route it would need admin auth, a job queue and progress reporting to do badly what `uv run python -m app.scripts.reembed` does well | 🔒 |
| **A merged-search endpoint across embedding spaces** | See "never union two indexes" | 🔒 |
| **`GET /providers/` exposing whether *another* user has a key** | Availability is per-caller. Leaking other users' key status is an unnecessary side channel | 🔒 |
| **Tool-calling methods on `ChatProvider`** | Tool use depends on the model, not just the provider. Requiring it everywhere would break Ollama or fill it with stubs that raise. Hence the second, optional `ToolCallingProvider` protocol — which is live and is what `/query/agent` runs on, not a dead end | 🔒 |

## CI/CD — what stays out, and why

The two workflows are `deploy-space.yml` and `ollama-base.yml`. Everything below
was considered for them and left out.

| Not in CI | Why not | |
|---|---|---|
| **Building the Ollama base image on every push** | 1.36 GB download plus a 274 MB model, for a layer that changes when Ollama or the embedding model changes — which is roughly never. Manual dispatch plus a monthly schedule instead | 🔒 |
| **Multi-arch (arm64) image builds** | Hugging Face CPU Basic is x86_64 and both of Jelena's laptops are x86_64. Emulated arm64 builds are slow and would be built for nobody. Revisit only if an ARM VPS (Hetzner CAX) is actually bought | 🔒 |
| **Dependabot / Renovate** | Four projects and one maintainer. Automated version-bump PRs on a showcase repo are noise that trains you to ignore PRs. Versions are pinned by hand; the monthly base-image build picks up Ollama fixes | 🔒 |
| **A supervisor (supervisord / s6) in the container** | Three processes with one rule between them — if any dies, all die — is forty lines of bash. A supervisor that restarts a crash-looping API *in place* is worse here: the platform's own restart should handle it, and it only can if the container actually exits | 🔒 |
| **Kubernetes, a service mesh, autoscaling** | One SQLite writer. There is nothing to scale to | 🔒 |
| **A reverse proxy and TLS certificates on the laptop** | Cloudflare Tunnel terminates TLS at the edge and needs no inbound port. Caddy would be a second thing to renew and expose | 🔒 |
| **Pushing to the Space from a local machine** | One direction only, from CI. A hand-push from a laptop is how the Space and the repo drift | 🔒 |
| **`docs/` inside the Docker image** | Not needed to run the app, and it would invalidate the layer cache on every documentation edit. Docs still reach the Space — the workflow pushes the *repo*, and Hugging Face builds the image from it. Two different things | 🔒 |
| **Running the test suite before deploy** | **Not a decision — an omission.** `deploy-space.yml` pushes on any commit to `main` with no gate. 159 tests run in ~40 s with no network; they should run first and block the push. Cheap to add, and it is the next CI change worth making | ⚠️ |
| **Type-checking and `tsc` in CI** | Same. Both are clean locally and neither is enforced anywhere | ⚠️ |

## Postponed, with a trigger

| Item | Waiting on | |
|---|---|---|
| **Ollama tool calling** | Nothing technical — `llama3.1` supports it and `ToolCallingProvider` is the interface it would implement. Jelena marked the MCP "what's next" list *not in milestone* | ⏸ |
| **Outward Streamable HTTP MCP transport** | An authentication story. Today the caller is a bearer token resolved by FastAPI; an externally mounted endpoint has nothing equivalent to feed `app/mcp/context.py`. Blocked on federated login | ⏸ |
| **Next.js proxy at `/api/mcp/*`** | Only needed when the browser reads the catalogue directly. Nothing does yet | ⏸ |
| **Rate limiting** | **Must land before the public URL**, not after. A public Space with uploads and a route that calls Anthropic per attempt is the trigger | ⏸ |
| **Public signup** | A decision, not code: published demo account, open signup, or a read-only tour. See `DEPLOY-HF.md`. Open signup needs rate limiting first | ⏸ |
| **Federated login (Cognito or Auth0)** | Jelena's IdP credentials. She confirmed 2026-07-31 that Cognito is not set up and this waits for a later session | ⏸ |
| **Tier 1 UI — download/upload the model** | Nothing. The API works and is tested; the frontend does not reach it | ⏸ |
| **Tier 2 `Modelfile`, tier 3 `?format=jsonl`** | Tier 1 UI first | ⏸ |
| **Ingestion progress reporting** | The sink already yields a running count. Upload is a background task with no channel to the browser, so nothing reads it. Needs an SSE or polling route | ⏸ |
| **`note_use` / `last_used_at`** | One line, never called. Harmless, and currently a lie in the schema | ⏸ |
| **Per-user document privacy** | Deliberate: authorisation is a later session. Do not build speculatively | ⏸ |
| **Seed-on-startup** | Needed before the Space is worth visiting — an empty demo shows nothing | ⏸ |

## Things built but never run

Worth their own section, because "written and typed" reads like "working" in a
list of completed items, and it is not the same thing.

| | |
|---|---|
| **The sentence-transformers embedding provider** | Written, typed, reviewed. The extra is ~2 GB of torch and is not installed here, so it has never executed. Treat as untested until someone runs `uv sync --extra local-embed` and uploads a document |
| **The Dockerfile, `start.sh`, both workflows, the base image** | No Docker on this machine. Reasoned and dry-run where possible — the `.dockerignore` was simulated against the real tree, and the `start.sh` smoke test found a genuine `set -e` bug — but nothing has been built. The first `docker build` will find something |
| **`docs/ops/LAPTOP8.md`, `LAPTOP4.md`** | Plans, not runs. Both open with a "facts to establish" step because they assume things about those machines that cannot be checked from here |

## Reversed decisions

Kept so nobody re-argues them from the wrong side.

| Was | Is | Why it changed |
|---|---|---|
| Two repos: a private working one and a generated public one | **One private repo, filtered at deploy time** | The stated reason — `related/`, `docs/jelena/`, `rag.db` — was wrong: all three were gitignored and never in git. One repo removes the real risk, which was divergence |
| `RECALL_UNLOCK_INTERACTIONS = 3` | **1** | A learner with two lessons has a working model. The gate told them they could not use it. Proficiency got its own constant instead |
| "Keep Ollama because torch is ~2 GB against Ollama's 274 MB" | **Keep Ollama for model parity** | The comparison was wrong — 274 MB is the *model*; Ollama itself is 1.36 GB, and the CPU-only torch wheel is far smaller than 2 GB. The choice stands; the reason does not |
| `docs/` gitignored entirely | **Only `docs/jelena/` and `docs/ops/`** | It hid every file `README.md` links to. On a project where documentation is half the deliverable, that was the most damaging line in the repo |
