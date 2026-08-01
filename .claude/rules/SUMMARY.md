# The working documents — what they are, and where they went

This is the only document in `.claude/rules/` that the repository tracks.
Everything else named below sits in this folder on Jelena's machine and is
gitignored, together with `docs/`, because a repository is not the place for the
record of how it was built. `README.md` is the documentation; this page is the
map for anyone who wonders what the rest of the folder holds. The cost is stated
plainly: a fresh clone gets the code and the README and none of the reasoning,
so the machine holding these files is the one that can continue the work.

## What moved out of `docs/` on 2026-07-31

Fourteen documents, moved with their history and then untracked. `CONTINUE.md`
is the session handoff, and the file a new session reads first. `TODO.md` is
what is next, including Jelena's own numbered notes. `DECISIONS.md` records what
was deliberately *not* built, so the same arguments are not had twice.
`PLAN.md` holds the architecture, the deployment reasoning and the model export
format; `PLAN-M2.md` is the tutor milestone that preceded it. `API.md` lists
every route with its authentication level, `MCP.md` explains the tool layer and
the tenant boundary that keeps one user's material away from another's, and
`VECTORS.md` covers streaming ingestion and why each embedding width gets its
own index. `AUTH.md` is identity and who pays for Claude, `CONTEXT-AUTH.md` is
the browser store and the NextAuth plan, `DEPLOY-HF.md` is the deployment
assessment, `MANUAL.md` is the user and developer guide, `MANUAL-GITHUB.md` is
the click-by-click deployment manual, and `other_agent.md` is the original
defect inventory. `docs/SESSIONS.md`, outside the repo entirely, is the short
readable summary of where the project stands.

Added since: `QUESTION-UNIT.md`, four options with for and against for the one
decision the learning channel still needs from Jelena — what unit of learning
travels up it.

## Done

The retrieval pipeline works end to end and is verified against a live Ollama:
upload, chunk, embed locally, search, answer with citations. The tutor teaches,
indexes every exchange synchronously so recall works immediately, and answers
from the learner's own corpus while admitting what it has not been taught. The
MCP layer is real — a server with five tools, a client speaking the protocol,
and an agent loop where the model picks the tools while every call appears in the
trace — on **Ollama as well as Claude** since 2026-08-01, so the agent costs
nothing and works offline. Whether a model can call tools is asked of the model
rather than assumed, because eighteen of the thirty installed here can and twelve
cannot. The fifth tool is the learner's own model rather than a document store,
and it is the only one entitled to say a topic was never taught. Embedding is
reachable directly too: a route that batch-embeds a list and shows what came
back, and one that derives a pinned model name — honest that the vectors are
byte-identical to the base, because that was measured rather than assumed.
Identity has its first pieces: a derived public handle, per-user
Anthropic keys of which only a hash and a fingerprint are stored, and three
identifiers kept strictly apart. The vector layer gained streaming ingestion
through an async generator and a second, pluggable embedding provider. `/status`
reports what the app can do by probing rather than by claiming. The browser now
has a React context store on Jelena's own pattern, with the streaming answer
drained by one action inside the provider. The channel from the browser to the model is
built: pieces of learning travel up as they happen, are embedded on arrival and
persist in SQLite, and the state comes back into a context slice — with the
search index deliberately untouched — and **the tutor now drives it**, pushing
each fragment up as the answer streams, with a sidebar panel that shows the model
being built. The vectors are kept in an index of their own, which buys
piece-to-piece similarity over the learner's material without re-embedding it.
The Docker path, both GitHub workflows and a `compose.yaml` for this laptop are
written. There are 227 tests, no network needed, with `pyright` and `tsc` clean.

## To do

Click through it in a browser — three sessions of work have been typechecked,
tested and driven by `curl`, and none of that is the same claim. Then Jelena's
one open decision, in `QUESTION-UNIT.md`: what unit of learning travels up the
channel. Then run it in Docker here and watch it work; nothing in that path has
ever been executed. Then NextAuth in front of the existing FastAPI login, with
Cognito as a second provider once the pool exists. Then the database work in one
pass: backup and restore, the persistence decision, and progress reporting for
ingestion, which was waiting on exactly the browser channel that now exists.
Then a decision about where the app should live permanently, since a Hugging
Face Docker Space turned out to need a paid plan. Smaller and still open: a
download button for the exported model, seed content on startup, an outward MCP
transport once federated identity exists, and rate limiting before any public URL.
