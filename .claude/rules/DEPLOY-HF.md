# Deploying to Hugging Face — plan, and an honest assessment

Written 2026-07-31 at Jelena's request: *"I will have the clue what is
crucially wrong, what is almost stupid and what is good."*

**Decided 2026-07-31: one repo, kept private, pushed to a public Space by a
GitHub Action.** An earlier draft of this file argued for a second, generated
repo. That argument was weaker than it looked and is retired — see *Why not two
repos* below.

**Built:** `Dockerfile`, `.dockerignore`, `deploy/start.sh`,
`deploy/ollama-base/` (the base image + its workflow),
`deploy/space-README.md`, and `.github/workflows/deploy-space.yml`.
`output: "standalone"` is set in `web/next.config.js`.

**Not verified: none of it has been built.** There is no Docker on this
machine. Everything here is reasoned, cross-checked and dry-run where a dry run
was possible — the `.dockerignore` was simulated against the real tree, the
process supervision in `start.sh` was smoke-tested with fake processes and a
bug was found and fixed — but the first real `docker build` will find something,
and that is expected rather than a failure. Run the base-image workflow first,
then the Space.

---

## ⚠️ The premise of this file broke — 2026-07-31

**A Docker Space is no longer free.** Hugging Face's own documentation now says
it plainly:

> *"Static Spaces are free for everyone. Gradio and Docker Spaces run on compute
> and require a paid plan to create: PRO for personal accounts, Team or
> Enterprise for organizations."*
> — <https://huggingface.co/docs/hub/en/spaces-overview>

CPU Basic still has **no hourly cost**; what changed is that *creating* a Space
that runs on compute needs **PRO, $9/month**
(<https://huggingface.co/pricing>). Jelena hit this twice in one session: a
Static Space refused to build with *"Static space builds require credits"*, and
the Docker template is behind the paid plan.

So the sentence this whole file was built on — *free on Hugging Face Spaces
now, the same image on a ~€5/month VPS later* — is no longer true, and the
"later" half has become the only half.

**What is unaffected, and it is nearly everything:** the `Dockerfile`, the
Ollama base image on GHCR, `deploy/start.sh`, `.dockerignore`, the standalone
Next build. None of it was Spaces-specific — that was a deliberate property
(*"one image, three destinations"*) and it is the reason this costs a decision
rather than a rewrite. Only `deploy-space.yml` and `deploy/space-README.md` are
Hugging Face's, and they stay: they are correct, and they work the day a PRO
account exists.

**The three ways forward**, with the money stated:

| | Cost | What it gives | What it costs beyond money |
|---|---|---|---|
| **Laptop + Cloudflare Tunnel** — `docs/ops/LAPTOP8.md` | €0 | the full app, persistent disk, Ollama generating *and* embedding, a public URL with no inbound port | it is up only when the laptop is up |
| **One small VPS** (~€4–5/month) | ~€4–5 | always up, persistent disk, the same image, no platform lock-in — and it dissolves the ephemeral-SQLite problem rather than working around it | a machine to keep patched |
| **Hugging Face PRO** | $9/month | exactly what is already built and wired: push to `main`, the Space builds | the most expensive option, and the least transferable |

**Not a route:** a Static Space. This app is FastAPI + a model server; static
hosting cannot run either.

**The one piece of work any non-Space route needs** is a workflow that builds
and pushes the *app* image to GHCR — today Hugging Face builds it from source,
which is the only thing a Space was doing for us. `ollama-base.yml` is the
template for it, and it is a short file.

**Recorded rather than decided.** Jelena's call: the deployment target is a
choice about money and her own machines, and the project is not defined by
whichever host is cheapest this month.

---

# Part 1 — the assessment

## What is good

**Bring-your-own-key is what makes a public deploy affordable today.** There is
no Ollama on Spaces, so Claude generates everything, and every visitor's
question would otherwise cost *you* money with no ceiling. BYOK — the visitor
pastes their own Anthropic key and their usage bills their account — removes
that at the root rather than capping it. Most people building a public LLM demo
discover this need after the bill.

> **It is not the point of the app, and earlier drafts of this file said it
> was.** The app is meant to issue identity; the tutor and retrieval are what
> that identity is for, and the direction is that the app charges for itself
> rather than requiring every visitor to own an Anthropic account. BYOK is the
> stage that makes a free public deploy possible in the meantime. Full record:
> `.claude/rules/AUTH.md` → *The plan this serves*.
>
> **Reframing it is not removing it.** Adding your own Anthropic key stays a
> live feature on the Space — distant from the identity plan, independent of
> it, and working. A visitor who already has an Anthropic account should always
> be able to bring their key and pay nothing. `.claude/rules/AUTH.md` → *BYOK stays*.

**One Docker image for every destination.** Spaces takes a `Dockerfile`; so does
Docker Compose on a VPS or on the laptop in `docs/ops/LAPTOP8.md`. There is no
decision here you have to get right today, which is unusual.

**The export format defuses the ephemeral disk.** Once the corpus exports and
re-imports, the durable artifact is `model.json`, not `rag.db`. The database
becomes a cache you can rebuild — a much more comfortable thing to lose.

**SQLite means moving the app is copying one file.** `vec_chunks` lives inside
it, so the vectors travel with the rows.

**The git history is clean.** Verified: the single `init` commit contains no
`.env`, no `related/`, no database, no private docs and no credential-shaped
strings. That is what makes "private now, public later" a toggle rather than an
archaeology project.

## What is crucially wrong

**1. `docs/` was gitignored in its entirety — fixed 2026-07-31.** Line 45 of
`.gitignore` was `docs/`, so *nothing* under it was ever tracked: PLAN, API,
MCP, AUTH, VECTORS, MANUAL, TODO, CONTINUE — every file `README.md` links to.
Anyone cloning got the code and broken links, and none of the reasoning
travelled with it. On a project where the documentation is half the deliverable,
this was the most damaging line in the repo.

**2. `ALLOW_APP_KEY_FALLBACK` defaults to `true`.** On a public URL that means
every visitor spends your balance — the exact thing BYOK exists to prevent. It
must be `false` on the Space. One line, and it is the difference between a demo
and a bill.

**3. There is no rate limiting, and `PUT /keys/anthropic` calls Anthropic on
every attempt.** A public URL with uploads, a login route, and a route that
makes an outbound API call per request should not stay unmetered.

**4. A visitor cannot do anything, because there is no public signup.** The
biggest *product* gap, and it has no code written for it. A Space where the only
accounts come from `.env` is a Space nobody can try. **Needs a decision** —
below.

**5. `IDENTITY_PEPPER` is empty, so it falls back to `SECRET_KEY`.** Publish a
link containing a `public_id`, then rotate `SECRET_KEY` — which a token leak
would force — and every published URL silently breaks. Set it before the first
public link.

**6. Uploads vanish on rebuild** and nothing in the UI says so. A visitor who
uploads something and returns tomorrow finds an empty app and concludes it is
broken. `deploy/space-README.md` says it; the app itself still does not.

## What is almost stupid — and worth doing anyway

Both of these were Jelena's own observations, and she was right about both.

**Realising upload on an ephemeral Space.** Uploads that disappear on restart
are not a storage feature. But that is not what they are for: they demonstrate
the *mechanism* — extract, chunk, embed, index, retrieve — which is the thing
being shown. It is only foolish if presented as persistence. Present it as what
it is and a defect becomes a stated design.

**The waterfall plan.** Waterfall fails when requirements are discovered late,
by stakeholders who were not in the room. Here there is one stakeholder and the
requirements have not moved since day one — *show LLM, RAG and MCP working
together*. The usual objection genuinely does not apply, and planning it whole
is how you learn an architecture rather than accrete one.

A different risk does apply: **nothing deployed until the end means Docker,
Spaces networking, cold starts, the model download and secrets all arrive in the
same afternoon.** None of them are hard; all of them are unpleasant together.

**So the one strong recommendation: deploy an ugly Space early, before the app
is finished.** Even one that only serves `/health`. That converts the entire
deployment class of problem into something already solved by the time it
matters. Not a compromise on the plan — the plan, with the riskiest step moved
first.

---

# Part 2 — the design

## One repo, private, one direction out

```
  github.com/kocicjelena/tutor-rag-embedings   (private)
  ─────────────────────────────
  the source of truth                 push to main
  everything, including docs/    ──────────────────▶  GitHub Action
  gitignored: .env, related/,                              │
              rag.db, docs/jelena/                         │ filters, then
                                                           │ force-pushes
                                                           ▼
                                    huggingface.co/spaces/<you>/mcp-py  (public)
```

**One direction only.** The Space's own git repo is a destination, never a place
to edit — the next run overwrites it.

### Why not two repos

The earlier draft said a separate deploy repo was needed because the working
repo holds `related/`, `docs/jelena/` and `rag.db`. All three are **gitignored**
— they were never in git at all — so that reasoning was wrong, and one repo
removes the real risk it was creating: two repos diverge, and then every bug is
fixed twice.

What genuinely remained was small: Spaces need YAML front matter in `README.md`,
which would look like rubbish at the top of the GitHub README. That is handled
inside one repo by `deploy/space-README.md`, copied over `README.md` at deploy
time — reviewable in a diff rather than generated by string surgery.

### Private does not mean the code is private

**The Space is public. Whatever the Action pushes is published**, regardless of
this repo's visibility. So filtering still happens — it just happens in the
workflow rather than at a repo boundary. Private buys comfort, not protection:
gitignore already did the protecting.

The cost is worth stating: this is a showcase, and the code and docs are the
strongest part of it — stronger than the demo will feel on a free CPU Space.
Private hides the best evidence from the people it is for. The recommendation is
**private now, public when it is ready to be pointed at**, which the clean
history keeps available.

The rule that keeps it available: **never commit `.env`, `related/`, or a real
`rag.db`.** Once something is in history, "public later" means rewriting history
or starting over.

## What the Action excludes

Each line in the workflow's *Build the Space tree* step is a decision:

| Removed | Why |
|---|---|
| `.claude/` | local tooling config, and Jelena's own working rules |
| `.CLAUDE.md` | the original brief — hers |
| `.claude/rules/other_agent.md` | the defect inventory. All fixed, still not a public document |
| `.github/` | CI belongs to GitHub, not to the Space |
| `docs/jelena/` | Jelena's own notes — gitignored, removed again defensively |
| `docs/ops/` | the laptop plans: her home network and what is exposed on it. Gitignored, and the removal that matters most if a gitignore rule is ever lost |

**Kept, deliberately:** `README.md` and `CLAUDE.md`. `CLAUDE.md` showing how the
work was directed is interesting rather than embarrassing, and `tests/` too —
177 of them is evidence.

**Changed 2026-07-31:** the working documents used to be `docs/` and were
published with the Space. They now live in `.claude/rules/`, which this workflow
deletes wholesale, so the Space carries its README and the code and nothing
else. Jelena's decision: a repository should read the way any GitHub repository
reads — README for whoever arrives — and the reasoning belongs beside the
tooling that consumes it. The documentation is still the strongest part of the
project; it is simply not the front page.

The workflow also **refuses to run** if `.env`, `rag.db` or `related/` somehow
appear in a checkout, or if any file exceeds 10 MB (Hugging Face needs Git LFS
above that, and a rejected half-push is worse than a failed check).

## Setting it up — done, 2026-07-31

The Space exists: **<https://huggingface.co/spaces/kjelenak/my_tutor>**, and
`HF_SPACE` in the workflow now names it.

**There is no `HF_TOKEN`, and there should not be.** Jelena configured the Space
with this repository as a **trusted publisher**, which is the same mechanism as
PyPI's: the job proves its identity with GitHub's OIDC token and receives a Hub
token that lasts one hour and can write to that one Space. Nothing is stored in
GitHub secrets, nothing is rotated, and a leaked log is worthless an hour later.

What the workflow needs for that to keep working — all three are in its header
too, because each one fails the run silently if it drifts:

- `permissions: id-token: write` on the job;
- `HF_OIDC_RESOURCE: spaces/kjelenak/my_tutor` — **the `spaces/` prefix is
  load-bearing**; without it the Hub looks for a model repo of that name;
- the claims on the Hub side matched **exactly**: repository
  `kocicjelena/tutor-rag-embedings`, and — if they were filled in — branch
  `main` and workflow `deploy-space.yml`. Renaming the file breaks the deploy.

The push itself is `hf upload … --repo-type=space --delete="*"`, a mirror rather
than an accretion, so a file removed here leaves the public Space as well.

The step-by-step, including the GHCR side and what to do when it fails:
**`.claude/rules/MANUAL-GITHUB.md`**.

## The Space image — still to build

```text
  Space (CPU Basic — 2 vCPU, 16 GB RAM, free)
  ┌───────────────────────────────────────────────┐
  │  :7860  Next.js standalone   ← the only port  │
  │  :8000  FastAPI + SQLite + sqlite-vec         │
  │  :11434 Ollama — nomic-embed-text only        │
  └───────────────────────────────────────────────┘
                     │
               Anthropic  ← generation, on the visitor's key
```

Three things about this that are not obvious:

**Port 7860**, declared as `app_port` in the Space README front matter — already
set in `deploy/space-README.md`.

**Bake `nomic-embed-text` into the image, don't pull it at boot.** It is 274 MB.
Pulled at startup, every cold start pays for it before the first upload works.
Baking needs the daemon up during the build (`ollama serve & … ollama pull`),
which is ugly but contained in one `RUN`.

**Keep Ollama rather than switching the Space to sentence-transformers.** The
alternative removes a daemon, but `torch` is ~2 GB of wheels against Ollama's
274 MB model, and the Space would then embed with a different model from the
laptop — so a database from one is unsearchable on the other. Same model
everywhere is worth more than one fewer process.

`web/next.config.ts` also needs `output: "standalone"` before any of this
builds.

## Secrets — Space settings, never files

| Name | Value |
|---|---|
| `SECRET_KEY` | new, random, not the local one |
| `IDENTITY_PEPPER` | new, random, **set before the first public link** |
| `FIRST_SUPERUSER` / `_PASSWORD` | a real admin you keep |
| `DEMO_USER` / `_PASSWORD` | see the signup decision |
| `ANTHROPIC_API_KEY` | **leave empty** |
| `ALLOW_APP_KEY_FALLBACK` | `false` |
| `USER_ANTHROPIC_KEYS` | `true` — already set in the `Dockerfile`. **Do not turn it off:** with the fallback disabled beside it, the Space would have no route to Claude at all |
| `ENVIRONMENT` | `production` — this is what makes `config.py` reject placeholder secrets |

## Needs a decision — how does a visitor get in?

| | Costs | Risks |
|---|---|---|
| **Published demo account** — credentials on the sign-in page | nothing; works today | everyone shares one corpus and sees each other's uploads. Fine for a demo, genuinely bad if anyone treats it as private |
| **Open signup** — email + password, no verification | a route and a form | throwaway accounts; a spam vector without rate limiting |
| **No accounts** — a read-only tour over seeded content | a UI mode | shows retrieval, hides the tutor, which is the interesting half |

Recommendation: **published demo account with an explicit banner** that the
corpus is shared and temporary. It is the only one that shows the whole app this
week, and the honesty costs one sentence. Open signup is right later, after rate
limiting.

## The image, stage by stage

```
  node:22-slim ──▶ npm ci, npm run build        (~400 MB of tooling, discarded)
                        │
                        │  .next/standalone/web  +  .next/static
                        ▼
  debian:12-slim ─▶ uv sync --frozen             (the venv, at /opt/venv)
                        │
                        ▼
  ghcr.io/…/mcp-py-ollama:nomic-embed-text  ← ollama + the model, prebuilt
        + python3 (apt)          the venv's interpreter, same distro, same path
        + node (one binary)      copied from node:22-slim — same glibc
        + /opt/venv              from the deps stage
        + app/ and web/          the source and the traced bundle
        + deploy/start.sh        the entrypoint
```

Three decisions in there worth keeping:

**The deps stage is `debian:12-slim`, not `python:3.11-slim`.** A venv records
an absolute path to the interpreter that made it. The runtime is Debian 12, so
building the venv on Debian 12 means `/usr/bin/python3.11` is real in both
places. Building it on `python:3.11-slim` would record `/usr/local/bin/...` and
require smuggling an interpreter across — which works right up until a shared
library is missing, and then fails at boot rather than at build.

**Only the `node` binary crosses, not the node image.** `node:22-slim` is
bookworm too, so it links against the same glibc and libstdc++. That match is
the reason this is sound rather than a trick that happens to work.

**`ALLOW_APP_KEY_FALLBACK=false` and `DEFAULT_CHAT_PROVIDER=claude` are baked
in.** There is no chat model in this image — only `nomic-embed-text`, because a
generation model is gigabytes and unusable on two shared vCPUs. So embedding is
local and generation is Claude, on the visitor's own key. Both defaults are
deployment decisions, not conveniences.

`SECRET_KEY` and `IDENTITY_PEPPER` are deliberately absent.
`ENVIRONMENT=production` makes `config.py` refuse to start on a placeholder, and
`start.sh` checks first so the failure is one clear line instead of a traceback
three processes deep.

**Build context: 1.0 MB, from a 738 MB working tree** — verified by simulating
`.dockerignore` against the real file list. `.env`, `rag.db`, `related/`,
`docs/jelena/`, `docs/ops/` and `node_modules` all confirmed excluded. That
check matters more than the size: without it, `.env` would be uploaded to the
daemon and could land in a layer.

## Order of work

1. `.gitignore` fix — **done**
2. Deploy workflow + Space README — **done**
3. `Dockerfile`, `.dockerignore`, `start.sh`, base image, `output: "standalone"`
   — **done, never built**
4. Run the **Ollama base image** workflow, and make the GHCR package **public**
   — Hugging Face pulls it anonymously
5. ~~Create the Space~~ — **done 2026-07-31**, `kjelenak/my_tutor`, with this
   repo as its trusted publisher. What remains of this step is: push `main`
   (`origin/main` is still a single `init` commit), then watch the *Space* build
   log, which is a different log from the GitHub one — **the ugly Space**
6. `/health` reports embedding readiness, not just sqlite-vec
7. Rate limiting
8. Seed-on-startup when the corpus is empty
9. The signup decision
10. "Documents here are temporary" in the UI itself, not only in the README

Steps 4 and 5 are the ones to do next, and deliberately before 6–10: they are
where the unknowns are.
