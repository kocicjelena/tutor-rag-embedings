# The GitHub manual — what the workflows do, and what you click

Written 2026-07-31, answering your notes 4–7 in `TODO.md`: *"point me to the file
explaining `.github/workflows/`, or make one, and tell me what I have to do
next."*

There are exactly **two** workflows and they do two unrelated jobs. Everything
below is about them.

| File | What it makes | When it runs | Needs Docker on your machine? |
|---|---|---|---|
| `.github/workflows/ollama-base.yml` | **The independent Ollama image** on GHCR — Ollama plus `nomic-embed-text`, nothing of this app | You press *Run workflow*, plus 04:00 on the 1st of each month | **No** |
| `.github/workflows/deploy-space.yml` | Copies this repo (filtered) onto the Hugging Face Space, which then builds it | Every push to `main`, or by hand | **No** |

Neither one needs Docker here. That is the whole point of them: this machine has
no Docker, and GitHub's runners do.

---

## Your note 6 — "how can I publish an independent docker for nomic?"

**That workflow already exists and it is `ollama-base.yml`.** The image it
publishes is exactly what you describe: Ollama and the `nomic-embed-text` model,
built and pushed on its own schedule, with no application code in it. The app's
`Dockerfile` then starts from it:

```dockerfile
ARG OLLAMA_BASE=ghcr.io/kocicjelena/mcp-py-ollama:nomic-embed-text
```

So there are two ways to publish it, and **you only need the first**.

### Route A — GitHub builds and pushes it (do this)

Nothing to install, nothing to log in to.

1. GitHub → **Actions** → *Ollama base image* → **Run workflow**.
   Leave both inputs alone (`v0.32.5`, `nomic-embed-text`) unless you mean to
   change them.
2. Wait. It downloads ~1.4 GB of Ollama, prunes the GPU runners a CPU Space can
   never execute, bakes the 274 MB model in, **runs a real embedding to prove
   the image works**, and only then pushes. Expect 10–20 minutes.
3. When it is green: GitHub → your profile → **Packages** → `mcp-py-ollama` →
   **Package settings** → **Change visibility** → **Public**.

Step 3 is not optional and is the one people forget. GHCR packages are private
by default, and **Hugging Face pulls anonymously** — a private base image makes
the Space build fail with a `denied` that reads like a typo in the image name.
The workflow prints a reminder at the end for this reason.

No `CR_PAT` anywhere in this route. The workflow authenticates to GHCR with the
`GITHUB_TOKEN` that GitHub mints for the run and throws away afterwards, which
is why `permissions: packages: write` is at the top of the file.

### Route B — you build it yourself, with `CR_PAT`

This is the path in your note, and it is correct — it is simply for a machine
that **has Docker**, i.e. the laptop in `docs/ops/LAPTOP8.md`, not this one.
`deploy/ollama-base/build.sh` already wraps it:

```bash
echo "$CR_PAT" | docker login ghcr.io -u kocicjelena --password-stdin
./deploy/ollama-base/build.sh --push
```

The script builds both tags, prints the final size, and **verifies the image can
actually embed before pushing** — never push one that has not. If you would
rather type the raw commands, they are:

```bash
docker build -t ghcr.io/kocicjelena/mcp-py-ollama:nomic-embed-text deploy/ollama-base
docker push  ghcr.io/kocicjelena/mcp-py-ollama:nomic-embed-text
```

`CR_PAT` is a GitHub personal access token (classic) with **`write:packages`**.
It lives in `.env`, which is gitignored, and nowhere else — not in a workflow
file, not in a README. The workflow does not read it and must not: a token you
store is a token you have to rotate, and Route A stores nothing.

Either route produces the same image. Route A is the one to use because it
leaves no credential behind and because the runner has the disk space.

---

## The Space deploy — and why there is no `HF_TOKEN`

You set the Space's **trusted publisher** to this repository. That replaces the
secret entirely, and it is a better arrangement than the one the docs used to
describe:

| | Old plan — `HF_TOKEN` secret | Now — trusted publisher |
|---|---|---|
| Lifetime | until you revoke it | 60 minutes |
| Scope | your whole account | this one Space |
| Stored | in GitHub secrets, forever | nothing is stored |
| If it leaked | valid until noticed | expired before you finish reading the log |

The mechanism: GitHub mints a signed token saying *"this run is
`kocicjelena/tutor-rag-embedings`, branch `main`, workflow `deploy-space.yml`"*,
the `hf` CLI posts it to `huggingface.co/oauth/token`, and the Hub compares it to
the claims you configured. Match → a one-hour token for
`spaces/kjelenak/my_tutor`. No match → `invalid_grant`.

### What a "claim" is — and what it has nothing to do with

A claim is one **fact about the run**, asserted by GitHub and signed by GitHub.
When a workflow asks for an OIDC token, GitHub puts the facts it knows into it:
which repository, which branch (`ref`), which workflow file, which actor, which
environment. Your side of the arrangement is stored on the Hub: *which of those
facts must match before I hand out a token.*

| Claim | Example | Effect if you set it |
|---|---|---|
| `repository` | `kocicjelena/tutor-rag-embedings` | **The only required one.** Any branch and any workflow in that repo may publish |
| `branch` | `main` | Also pins it to one branch. Leave it out and *any* branch publishes |
| `workflow` | `deploy-space.yml` | Also pins it to one workflow file. Rename the file and the deploy stops |

Matching is **exact** — no regex, no prefixes, no wildcards. There is no
`main*`, and `Main` is not `main`. Two ways this bites in practice:

- **`repository` is `owner/name`, not a URL.** `https://github.com/kocicjelena/tutor-rag-embedings`
  will never match; `kocicjelena/tutor-rag-embedings` will. This is the most
  likely cause of `invalid_grant: No trusted publisher configured …`.
- **Start with `repository` alone.** Add `branch` and `workflow` afterwards, one
  at a time, re-running the deploy between each. Then a failure names its own
  cause instead of leaving three suspects. The *What this run claims to be* step
  in `deploy-space.yml` prints exactly what GitHub is asserting, so you can
  compare the two strings rather than guess at them. So if you ever want to deploy from a branch
other than `main`, you either remove the `branch` claim (looser) or add a second
trusted publisher for that branch (tighter, and reversible by deleting it).

Where to read it: **<https://huggingface.co/docs/hub/en/trusted-publishers>** —
the section *"Configure the trusted publisher on the Hub"*, and the table of
supported CI providers below it. GitHub's own side is
<https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect>.

**This is not related to the Ollama image, and not to GHCR.** They are two
different destinations with two different, unconnected authentications, and it
is worth keeping them apart in your head:

| | Ollama base image | The Space |
|---|---|---|
| Goes to | GHCR (`ghcr.io`), GitHub's own registry | Hugging Face |
| Workflow | `ollama-base.yml` | `deploy-space.yml` |
| Authenticated by | `GITHUB_TOKEN`, minted per run, plus `permissions: packages: write` | OIDC token exchanged for a 1-hour Hub token |
| Trusted publishers involved? | **No** | Yes |
| Your `CR_PAT`? | Only if you build on the laptop instead | Never |

The one place they touch is the `FROM` line in the `Dockerfile`: Hugging Face
pulls that GHCR image while building the Space. That is why the package has to
be **public** — and it is a pull, anonymous, with no token of any kind.

**Three ways to break it, all silent until the run fails:**

1. Renaming `deploy-space.yml`, or deploying from a branch other than `main`, if
   you filled in the `workflow` / `branch` claims on the Hub. Claims are matched
   **exactly** — no prefixes, no wildcards.
2. Removing `permissions: id-token: write` from the job. GitHub then mints no
   token and there is nothing to exchange.
3. Dropping the `spaces/` prefix from `HF_OIDC_RESOURCE`. The Hub would look for
   a *model* repo called `kjelenak/my_tutor` and refuse.

What the workflow does, in order: refuses to run if `.env`, `rag.db` or
`related/` appear in the checkout or any file exceeds 10 MB → deletes `.claude/`,
`.github/`, `.CLAUDE.md`, `other_agent.md`, `docs/jelena/`, `docs/ops/` →
swaps in `deploy/space-README.md` as the Space's front page → uploads the tree
with `--delete="*"`, so the Space is a mirror and a file deleted here disappears
there too.

**The Space is public even though the repo is private.** The delete list above is
the only thing standing between the two, so add to it deliberately.

---

## What you have to do next — in this order

Each step is *finished* only when the thing after the dash is true.

- [ ] **1. Push the code.** Right now `origin/main` is a single `init` commit —
      the Space would build nothing. *Done when `git log origin/main` shows this
      work.* (Ask me and I will prepare the push; the last step is yours.)
- [ ] **2. Run *Ollama base image*.** *Done when the run is green and the image
      appears under your Packages.*
- [ ] **3. Make `mcp-py-ollama` public.** *Done when the package page says
      Public.* Without this, step 5 fails.
- [ ] **4. Set the Space secrets** — Space → Settings → Variables and secrets.
      The list is in `DEPLOY-HF.md` → *Secrets*. The two that must not be
      skipped: a real random `SECRET_KEY` and `IDENTITY_PEPPER`, and
      `ENVIRONMENT=production`, which is what makes the app refuse to start on a
      placeholder rather than run with one. Leave `ANTHROPIC_API_KEY` **empty**.
- [ ] **5. Push to `main` (or Actions → *Deploy to Hugging Face Space* → Run
      workflow).** *Done when the Space's Files tab shows this repo and the
      build log starts.*
- [ ] **6. Watch the Space build**, not the GitHub run. GitHub's job finishes in
      about a minute — it only *uploads*. Hugging Face then builds the image,
      and that is where a first build usually fails. Space → **Logs** →
      *Build*.

Expect step 6 to fail at least once. That is normal for a first Docker build
that has never run anywhere; `docs/CONTINUE.md` says plainly that nothing in the
Docker path has been executed yet.

---

## Creating the Space — it must be **Docker**, and nothing else

Learned the hard way on 2026-07-31: the first Space was created from a React
template, and a *Static* Space refuses to build with **"Static space builds
require credits."** Docker on CPU Basic is free; Static is not. There is no
adapting one into the other — delete it and make a new one.

**Delete the wrong one:** Space → **Settings** → bottom of the page → *Delete
this space* → type its full name (`kjelenak/my_tutor`) to confirm.

**Create the right one** at <https://huggingface.co/new-space>:

| Field | Value |
|---|---|
| Owner | `kjelenak` |
| Space name | `my_tutor` — **keep this exact name**, or `HF_SPACE` in `deploy-space.yml` has to change with it |
| License | anything (`mit`) |
| **Space SDK** | **Docker** → template **Blank**. Not Static, not React, not Gradio, not Streamlit |
| Hardware | **CPU basic · 2 vCPU · 16 GB · FREE** |
| Visibility | **Public** |

Then **add no files by hand.** The Space stays empty until the deploy workflow
pushes to it, and that push includes the `README.md` built from
`deploy/space-README.md`, whose front matter (`sdk: docker`, `app_port: 7860`)
is what tells Hugging Face how to run the container.

**Configure it, in this order:**

1. **Trusted publisher** — Space → Settings → *Trusted Publishers* → Add →
   provider **GitHub Actions**, `repository` = `kocicjelena/tutor-rag-embedings`
   (owner/name, one `d` in `embedings`), leave `branch` and `workflow` empty.
2. **Secrets** — Space → Settings → *Variables and secrets*. These four, because
   the container refuses to start without them:

   | Secret | Value |
   |---|---|
   | `SECRET_KEY` | new random — `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
   | `IDENTITY_PEPPER` | a second, different random string from the same command |
   | `FIRST_SUPERUSER` | the email you will sign in with |
   | `FIRST_SUPERUSER_PASSWORD` | a real password, not `changethis` |

   Do **not** add `ANTHROPIC_API_KEY`. `ENVIRONMENT=production`,
   `ALLOW_APP_KEY_FALLBACK=false` and `USER_ANTHROPIC_KEYS=true` are already
   baked into the `Dockerfile` — visitors bring their own key.
3. **Deploy** — GitHub → Actions → *Deploy to Hugging Face Space* → Run
   workflow.
4. **Watch the Space's own build log**, not GitHub's: Space → **Logs** →
   *Build*.

## The first deployment — 2026-07-31, step by step

Written while doing it, because it happens once and the next time may be years
away. Each step says **what you do**, **what proves it worked**, and **what it
looks like when it hasn't**. Nothing here is clever; it is a list to follow.

**Where things live** — worth writing down once, because half of "how did I do
this" is remembering where you were:

| | |
|---|---|
| Code | <https://github.com/kocicjelena/tutor-rag-embedings> (private) |
| Space | <https://huggingface.co/spaces/kjelenak/my_tutor> (public, SDK Docker) |
| Base image | `ghcr.io/kocicjelena/mcp-py-ollama:nomic-embed-text` |
| Local checkout | `~/mcp-py` — the same code; the repo name differs, that is fine |

---

**Step 0 — the code reaches GitHub.**
Done for you in this session: the session's work committed, the branch merged
into `main`, `main` pushed.
*Proves it:* `git log origin/main --oneline` shows real commits, not one `init`.
*Note:* a push to `main` **starts a deploy immediately**. That is intended, and
step 3 explains what happens if the base image is not public yet.

**Step 1 — build the Ollama base image.**
Open this link — it *is* the workflow page, no hunting through tabs:

<https://github.com/kocicjelena/tutor-rag-embedings/actions/workflows/ollama-base.yml>

On the right of the blue *"This workflow has a workflow_dispatch event
trigger"* bar there is a grey **Run workflow** button. Click it → a small panel
opens with `Branch: main` and two text boxes already filled
(`v0.32.5`, `nomic-embed-text`) → **leave them alone** → click the green **Run
workflow** inside the panel. Reload the page after a few seconds and a new run
appears at the top. Takes 10–20 minutes.

*If the button is not there:* you are on the Actions **landing** page rather
than this workflow's page — the button only exists on the workflow's own page.
*If the whole Actions tab says workflows are disabled:* Settings → Actions →
General → *Allow all actions*, then reload.
*Proves it:* the run is green, and the log line `final image: … MB` appeared.
The last step also verified the image can really embed — if that failed, nothing
was pushed, which is deliberate.
*If it fails:* almost always disk on the runner or a changed Ollama release tag.
Re-run with the previous tag in the input box.

**Step 2 — make the package public.**
The package only exists once step 1 is green. Then:

<https://github.com/users/kocicjelena/packages/container/package/mcp-py-ollama>

→ **Package settings** (right-hand column) → scroll to *Danger Zone* →
**Change visibility** → **Public** → type the package name to confirm.
*Proves it:* opening
`https://github.com/kocicjelena/tutor-rag-embedings/pkgs/container/mcp-py-ollama`
in a private browser window shows the package.
*Why it matters:* Hugging Face pulls it **anonymously**. Private is the default
and this is the single most likely thing to forget.

**Step 3 — the deploy runs.**
It already started at step 0. If the base image was not public yet, redo it now:
GitHub → **Actions** → *Deploy to Hugging Face Space* → **Run workflow**.
*Proves it:* the GitHub run is green in about a minute, ending with the Space
URL. Then the Space's **Files** tab shows this repo's files, and its front page
is the text from `deploy/space-README.md`.
*What green does NOT mean:* that the app works. This job only **uploads**.

**Step 4 — set the Space secrets.**
Space → **Settings** → *Variables and secrets*. The list is in `DEPLOY-HF.md`.
The ones that stop it booting if missing: `SECRET_KEY`, `IDENTITY_PEPPER` (both
new and random — **not** the local ones), `ENVIRONMENT=production`. Leave
`ANTHROPIC_API_KEY` **empty**: visitors bring their own key.
*Proves it:* the Space restarts by itself after a secret changes.

**Step 5 — watch the Space build.**
Space → **Logs** → *Build*. This is a different log from GitHub's, in a
different place, and it is where a first build actually fails. Ten to twenty
minutes for a cold one.
*Proves it:* the Space status turns **Running** and the page loads.
*Expect at least one failure here.* Nothing in the Docker path had ever been
executed anywhere before today — the files were written and reviewed, never
built. A first failure is information, not a setback.

**Step 6 — try it as a visitor.** Sign in, ask one question, upload one small
document, watch the tutor stream an answer.
*Known and intended on the free tier:* uploads and lessons disappear when the
Space restarts, and generation needs **your own Anthropic key** pasted into
*Claude access*. Both are stated on the Space's front page.

---

**If you are reading this years later:** the order is the whole content of this
page. Code to GitHub → base image built → **package public** → deploy workflow →
Space secrets → Space build. Only the last three can fail in a way that needs
thinking, and the failure table below covers what each one looks like.

## When something fails, read this first

| Symptom | Where | What it means |
|---|---|---|
| `Node.js 20 is deprecated … forced to run on Node.js 24` | GitHub run log | A **warning**, not a failure — the run still worked. An action you *use* was built for an older runtime. Fix by bumping its version (`actions/checkout@v4` → `@v5`), never by editing YAML into this repo: the `runs: using: node24` snippet in GitHub's docs belongs to an action's own `action.yml`, and you do not own `actions/checkout` |
| `invalid_grant` in *Push to the Space* | GitHub run log | The trusted-publisher claims do not match. Check branch, workflow filename, and the `spaces/` prefix |
| `Error: Resource not accessible by integration` | GitHub run log | `permissions:` block missing or trimmed |
| `denied` / `unauthorized` pulling `mcp-py-ollama` | **Space** build log | The GHCR package is still private — step 3 |
| `.env is in the checkout — refusing to publish` | GitHub run log | A gitignore rule was lost. Do not "fix" it by deleting the check |
| Build succeeds, Space shows *Runtime error* | Space **Container** log | The app started and died. Almost always a missing secret — `start.sh` checks first so it says which |
| Space stuck on *Building* for 20+ minutes | Space build log | Normal for the first build: it is pulling the base image and building the Next.js bundle |

Two logs, not one, and they are in different places. Most confusion about "did
it deploy" is really about looking at the GitHub one, which is only ever the
upload.

## Money and minutes

GitHub Actions is free without limit on **public** repositories. On a private
one you get 2,000 minutes a month, and the base-image build is the only
expensive job here — 10–20 minutes, run by hand, plus once a month on the
schedule. Even monthly for a year is a rounding error against the allowance.

The Hugging Face Space on CPU Basic is free. Nothing in this manual spends
anything, and neither workflow ever calls Anthropic.

## What is deliberately not in CI

Recorded in `DECISIONS.md` → *CI/CD*. The one worth knowing: **the tests do not
run before a deploy.** 175 of them run in 44 seconds with no network, and they
should gate the push. That is logged there as an omission, not a decision — it
is the next CI change worth making.
