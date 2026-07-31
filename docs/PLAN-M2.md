# Milestone 2 — the learner's model, improved over the long run

Planned 2026-07-28 after reading `~/ollama8jul/components/tutor/` (the modular
version) and `related/AITutor/*.tsx` (the two monolithic variants it came from).

## What the tutor already does

A learner picks an AI/ML term and chats with Claude as a tutor. Every Claude
exchange is folded into a `LearningModel`: interaction count, proficiency level,
vocabulary-growth chart, per-topic mastery, and a `sessionHistory` of
`{term, userMsg, aiResponse}`.

Then the good idea: a second **model source**. Flip from `claude` to `trained`
and the app stops calling Claude and answers from the learner's *own* accumulated
history instead.

> Claude teaches → the transcript becomes the learner's model → the learner can
> query their own model.

That arc is the showcase. It doesn't need changing — it needs its weak half made
real.

## Where it's weak — and why mcp-py is the exact fix

The `trained` half is `answerWithTrainedModel()`: word-overlap similarity over
`sessionHistory`, returning the single closest past answer verbatim.

| Today | Consequence | mcp-py already has |
|---|---|---|
| `commonWords / max(len)` over raw strings | Purely lexical. *"what are vector representations"* will not match *"explain embeddings"* — the exact miss a learner makes. Stopwords dominate, so *"what is the"* matches everything. | 768-dim semantic embeddings |
| History in browser storage | Dies with the browser profile; no second device; an unbounded array in `localStorage` | SQLite + sqlite-vec, persistent, owner-scoped |
| Replays one past answer | No synthesis — *"Based on my training (34% confidence)"* then an old paragraph | retrieval over top-k + generation, with citations |
| Unlocks at N interactions, then flat | Accumulates but never improves | improves as the corpus grows |

**The long-run improvement is one substitution: lexical replay → semantic
retrieval plus synthesis.** The learner's history becomes a RAG corpus. Nothing
else about the tutor has to change.

## The integration

`trained` mode becomes a query against the learner's own indexed history.

```
claude  mode → ask Claude fresh, teach, AND index the exchange
trained mode → RAG over everything this learner has been taught
```

Both already exist in mcp-py. `trained` is `POST /query/` with a tutor system
prompt; the only new thing is an ingestion shape for interactions rather than
files.

### New backend surface (small)

- `POST /api/v1/tutor/interactions` — `{term, question, answer}` → chunk, embed,
  index under the caller's `owner_id`. Reuses `rag.ingest_document` unchanged.
- `POST /api/v1/tutor/recall` — thin wrapper over the existing query path with a
  recall-shaped system prompt (*"answer from what this learner has already been
  taught; if it isn't there, say so and name what they have covered"*).
- `GET /api/v1/tutor/stats` — chunk count, distinct topics, coverage. Makes the
  progress cards report **real numbers from the corpus** instead of an
  incrementing counter.

### What stays in the tutor, untouched

Topic mastery, vocabulary growth, proficiency, goals, the charts, the download.
They're cheap, they're the dashboard, and they're already good.

### Why this also gives us MCP for free

Milestone 2 was already going to expose `search_documents` over MCP. For this
app that tool **is** `tutor/recall` — same function, second transport. So the MCP
server and the tutor integration are one piece of work, not two. That is the
main reason to do them together.

## Three fixes worth making while we're in there

1. **The Claude call is on the client path.** `claudeTutor.ts` has no
   `"use server"` and is imported by the `"use client"` hook, with
   `dangerouslyAllowBrowser: true`. Right now the key is *not* leaking, because
   Next only inlines `NEXT_PUBLIC_*` vars — so `process.env.ANTHROPIC_API_KEY`
   is `undefined` in the browser and the call simply fails.
   **The hazard is the obvious fix:** renaming it to
   `NEXT_PUBLIC_ANTHROPIC_API_KEY` would "work" and ship the key to every
   visitor. Route it through a server route handler instead —
   `web/app/api/chat/route.ts` in this repo is the working template.
2. **`claude-sonnet-4-20250514` is used in 5 places** and was scheduled for
   retirement on 2026-06-15 — already past. Move to a current model.
3. **`TRAINED_MODEL_UNLOCK_INTERACTIONS = 1`** looks like a debug value; the
   unlock banner is a nice beat and fires immediately at 1.

## One decision needed

Where does the tutor UI live?

**A. Keep it in `ollama8jul`; mcp-py is just its memory.**
Least disruption. Two apps to run and deploy.

**B. Bring the tutor into `mcp-py/web`.** ← recommended
One app. It immediately inherits the provider picker (so the learner can choose
whether Claude or a local model does the synthesis — which makes the picker
*mean* something pedagogically), the source panel (showing *which past lessons*
produced an answer — exactly the right thing for a tutor), streaming, and the
tool-trace panel once MCP lands. It also keeps the "rest from complexity"
property: one repo, one thing to run.

The tutor components are already cleanly modular — 13 components and 7 lib files,
none over ~150 lines — so porting is mechanical, not a rewrite.

## Suggested order

1. `tutor/interactions` + `tutor/recall` in mcp-py — the substitution that makes
   the learner's model actually improve
2. Port the tutor UI (if **B**), wiring `trained` mode to `recall`
3. Expose `recall` over MCP — the tool-trace panel lights up, and the tutor gains
   a second transport for free
