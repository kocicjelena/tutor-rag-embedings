# MCP — the tool layer

Built 2026-07-30. Milestone 3, first half.

MCP gives the app a **catalogue** — a machine-readable list of what it can do,
with descriptions written for a model to read. Before this, "what can the app
do" only existed as HTTP routes a human had wired up by hand. Now a model can
ask.

Both halves are now built: the server with four tools and an in-process client
(2026-07-30), and the agent loop that actually calls them (same day). **The
tool-trace panel on `/` is no longer empty** — tick *Let the model use tools*
and each search the model runs appears there with its arguments and result.

## Shape

```
app/mcp/
  context.py   who the tool acts for — set by the route, never by the model
  tools.py     the tool bodies: plain async functions, no MCP imports
  server.py    FastMCP, registering those functions with descriptions
  client.py    an MCP client that talks to that server over a real session
```

`tools.py` has no MCP import on purpose. The tools are ordinary functions over
the same services the HTTP routes use, so MCP is a *transport* over existing
behaviour rather than a second implementation that can drift from it. It also
means they test as functions.

## The four tools

| Tool | Returns | Notes |
|---|---|---|
| `search_documents(query, top_k=5)` | Nearest passages with scores and titles | The retrieval half of `POST /tutor/recall`, second transport |
| `list_documents()` | Metadata for everything you own | Each marked `lesson` or `upload` |
| `get_document(document_id)` | One document as its indexed chunks | Truncated at 8 000 chars |
| `tutor_stats()` | Lesson count, topics, chunk count | Same function as `GET /tutor/stats` |

**No tool generates text.** Retrieval only. An agent already has a model — the
one that decided to call the tool — so a tool making its own LLM call would
nest a second, unattributable generation inside the first, hide its cost, and
make the trace panel a lie about what happened. `POST /tutor/recall` is
`search_documents` plus generation, and that composition belongs to the caller.

## The one rule: `owner_id` never comes from tool input

A tool's arguments are chosen by the **model**. Every parameter in a tool
signature is untrusted input, however authoritative it looks. If
`search_documents` took an `owner_id`, then any prompt that talked the model
into passing a different UUID would read another learner's corpus, and no
amount of prompt hardening would reliably stop it.

So no tool has an owner parameter, and none can grow one: the caller is read
from a context variable that only an authenticated route can set
(`app/mcp/context.py`). Unbound, a tool raises rather than defaulting to
anybody — it fails closed.

This is the same move as hard rule #3, where `vectors.search()` takes
`owner_id` as a required positional argument so that no call shape can omit
it. Both make the boundary structural instead of a convention someone has to
remember.

Three tests guard it, two of them by asserting on *shape* rather than
behaviour, because a regression here would be silent:

- no tool's JSON Schema exposes `owner`/`user`/`tenant`-shaped properties;
- no tool function takes a `session` or `owner_id` parameter;
- `get_document` answers identically for "someone else's id" and "an id that
  does not exist", so it cannot be used as an existence oracle.

## Why a client session per call

The MCP server runs as a task spawned inside `tool_session`, and anyio copies
the current context when a task starts. The caller must therefore be bound
*before* the server task exists — which is why `app/mcp/client.tool_session`
owns both steps and nothing else should open a session.

A single long-lived server task would be spawned once, under whichever user
arrived first, and every later tool call would silently read that user's
corpus. **The per-call session is not a simplification waiting to be optimised
away; it is the isolation.** `test_binding_reaches_the_server_task` fails if
someone hoists it.

The cost is a pair of in-memory streams and an `initialize` handshake —
measured at ~5 ms for `list_documents` against the live server, against
~1 500 ms for `search_documents`, which is dominated by the Ollama embedding
call. The protocol is not where the time goes.

### Nothing raises inside the session block

A session is an anyio task group, and an exception crossing its `__aexit__`
comes out wrapped in an `ExceptionGroup` — so `except UnknownToolError` in a
route would not catch it and the caller would get a 500 instead of a 404.
Collect the outcome first, raise after the block. This bit us once already.

## The HTTP surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/mcp/tools` | The catalogue, fetched over the protocol |
| `POST` | `/api/v1/mcp/call` | Invoke one tool as the signed-in user |

Both go through a real client session rather than calling the functions
directly, so this surface cannot drift from what an agent sees: if
`tools/list` would show a tool, so does `GET /mcp/tools`, with the same
description text and the same JSON Schema.

`MCPCallRequest` has no owner field and must never gain one.

Status codes are deliberate. A tool that **runs and fails** is `200` with
`ok: false` — that is a result, and the trace panel shows it as one; a failed
tool call is something the model should see and recover from, not a 500 that
ends the user's request. Only an **unknown tool name** is a `404`, because that
is the caller getting it wrong rather than the tool, and the message names what
does exist so an agent can correct itself from the error alone.

```bash
curl -s $API/api/v1/mcp/tools -H "Authorization: Bearer $T"
curl -s -X POST $API/api/v1/mcp/call -H "Authorization: Bearer $T" \
     -H 'Content-Type: application/json' \
     -d '{"name":"search_documents","arguments":{"query":"embeddings"}}'
```

## Descriptions are prompt text

The strings in `server.py` are the only thing standing between a model and
calling `get_document` in a loop, so they say what each tool costs and when to
prefer another. Treat edits there as prompt changes, not documentation.

## Tool calling — built 2026-07-30

`app/services/agent.py`, reached by `POST /query/agent`. The loop:

```
question → model → "search for X" → results → model → answer
```

against plain RAG, which retrieves once, always, before the model sees
anything. That inversion is worth having for questions one-shot retrieval
answers badly: *"what have I been taught?"* has no good embedding — it is about
the shape of the corpus, not its content — so retrieval returns five arbitrary
lessons, while the agent calls `tutor_stats` and answers correctly.

**A separate route, not a flag.** The agent is slower and costs more tokens.
Making it a mode of `/query/stream` would have made every plain question pay
for a capability it did not ask for.

**`ToolCallingProvider` is a second, optional Protocol** rather than three more
methods on `ChatProvider`. It is not a spare part — it is the interface the
agent loop is written against, and the only reason `POST /query/agent` works
today: `ClaudeChatProvider.stream_turn` implements it, `agent.run` takes one as
its `provider` argument, and every tool call in the trace panel arrives through
it.

Why *optional* rather than folded into `ChatProvider`: tool use depends on the
model, not just the provider, so requiring it everywhere would either break
Ollama or fill it with stubs that raise.
`isinstance(provider, ToolCallingProvider)` is then a real question with a real
answer, and `/query/agent` returns a clean 422 naming the alternative rather
than failing mid-stream. Ollama tool calling is one `stream_turn` away
precisely because this Protocol already exists — adding it means implementing
this interface and nothing else.

The types in `base.py` are provider-neutral — Anthropic's content-block format
never reaches the loop, because translating is `claude_provider._to_anthropic`'s
job. Add a third provider and the loop does not change.

**`MAX_TOOL_ROUNDS = 5`** is a ceiling, not a target. A model that loops —
search, weak result, search again with a synonym — would otherwise spend the
user's Anthropic balance without end.

## The primer — making the agent cheaper, built 2026-07-31

Jelena's observation: *the agent is slower and costs more tokens*, and her
suggestion — derive the agent's instructions from the learner's own model,
up front. Built as `agent.build_primer`.

An agent's cost is measured in **rounds**. Every tool call is another request
carrying the whole conversation so far, and on Claude that is the user's own
money. The cheapest round is the one that never happens.

A cold agent has to discover the shape of the corpus before it can search it —
one round spent on `tutor_stats` or `list_documents`, learning facts this app
can read from its own database in a few milliseconds, for nothing. So the
system prompt now carries them: lesson count, upload count, indexed passages,
and the topic names. Typical saving is one full round on most questions, and
*every* round on a question the primer answers outright — "what have I been
taught?", "how much do I know about X?".

**The primer is facts, never instructions.** Topic names come from documents a
user uploaded or a tutor wrote, which makes them untrusted text. A document
titled *"ignore previous instructions and…"* must arrive as a **title**, not as
a directive. So the list is capped, enumerated inside one sentence that says
what it is, and explicitly labelled as data. A test asserts the label is there
and that a hostile title never reaches a line of its own.

It does not replace the tools, and it must not grow into doing so. The primer
says what the corpus *contains*; only `search_documents` says what it *says*.
An empty corpus gets a shorter primer that tells the model to say so rather
than spend a round confirming it.

Reading it fails soft: if the query errors, the agent runs unprimed and spends
the round it would have saved. A caller that passes an explicit `system` is
overriding the prompt deliberately and is not primed.

**A failed tool goes back to the model, not to the user.** Wrong arguments, a
hallucinated tool name, a document that is not there: each returns as a result
the model can read and recover from. `UnknownToolError`'s message names every
tool that does exist, so a model that guessed can correct itself from the error
alone. 19 tests, driven by a scripted provider over the real MCP tools.

## What is next - not in milestone

1. **Ollama tool calling.** `llama3.1` supports it, so this is one more
   `stream_turn` implementation — no change to the loop, which is the point of
   the neutral types.
2. **An outward transport** — mounting the Streamable HTTP app so an external
   client (Claude Desktop, the console) can reach these tools. Needs an
   authentication story first: today the caller is a bearer token resolved by
   FastAPI, and an externally mounted MCP endpoint has no such thing until
   `app/mcp/context.py` is fed from something equivalent.
