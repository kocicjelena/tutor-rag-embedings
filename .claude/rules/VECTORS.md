# The vector layer

Proposed 2026-07-30 at Jelena's request. **Both are built, 2026-07-31.** The
analysis below is kept as written — it is the reasoning the code follows — with
a status note under each. Both are additive: nothing here changed the working
768-dimension path, and with one provider configured every call still resolves
to `vec_chunks` and behaves exactly as before.

## Built — the short version

| | |
|---|---|
| `app/services/ingest_stream.py` | Streaming ingestion. `vector_sink` is a PEP 525 async generator driven by `asend()` / `aclose()`; peak memory is one batch. Used by document upload; the tutor still uses `rag.ingest_document`. |
| `vectors.begin_document` / `append_chunks` | The hoisted delete, so per-batch writing cannot erase the previous batch. |
| `vectors.table_for(dimensions)` | One `vec0` index per embedding width. `vec_chunks` keeps its name; others are `vec_chunks_d384`. |
| `EMBEDDING_PROVIDER` + `sentence_transformers_provider.py` | A second embedding backend behind `uv sync --extra local-embed`. |
| `indexed_with` / `searchable` on `GET /documents/` | What the active model cannot search, marked in the API and in the UI. |
| `app/scripts/reembed.py` | The fix for the above. `--dry-run` first. |

**Jelena's decision on the open question** (recorded 2026-07-31): show it in
the UI *and* offer a re-embed command. Do **not** merge results across
embedding spaces — the scores are not on a common scale, so the ranking would
look fine while being meaningless.

---

# 1. Streaming ingestion with async generators

## Your idea

> Not every chunk gets written to the database directly. A generator produces
> the chunk, it is pushed in with `send()`, `close()` at the end, and what comes
> out of the coroutine is what gets recorded.

## One correction first, because it decides the whole design

The `send()` / `close()` / `@coroutine` pattern you are describing is **PEP 342**,
and it is a **synchronous** generator idiom. It cannot work here, for a reason
that is structural rather than stylistic: a sync generator body cannot `await`.
The consumer has to run

```python
await session.execute(...)      # write the batch
await embedder.embed(batch)     # call Ollama
```

and neither is possible inside `def consumer(): ... x = yield`.

The async equivalent exists and does exactly what you want: **PEP 525 async
generators**, with `asend()` and `aclose()` in place of `send()` and `close()`.
Same shape, same priming, same "push values in, flush at the end" — it just
awaits properly.

(`@types.coroutine` is a third, unrelated thing: it adapts old generator-based
coroutines for `await`. Not what this needs.)

## What ingestion does today

`app/services/rag.py::ingest_document`:

```python
raw_chunks = chunk_text(text)                    # every chunk, in memory
embeddings = await embedder.embed(raw_chunks)    # every vector, in memory
chunks     = [DocumentChunk(...) for ...]        # every row, in memory
await crud.replace_chunks(...)                   # one transaction
await vectors.upsert_chunks(...)                 # one executemany
await session.commit()                           # one commit
```

Everything is resident before a single row is written. At `MAX_UPLOAD_BYTES`
(10 MiB) with `CHUNK_SIZE=1000` / `CHUNK_OVERLAP=200` that is roughly **13 000
chunks**, and at 768 float32 that is **~40 MB of vectors alone**, plus the text
held twice. It works, but it is the shape that stops working first.

## Verdict: worth building, as a second path

Three reasons, in order of how much they matter.

**It bounds memory.** Peak becomes one batch instead of one document. That is a
real property, not a micro-optimisation, and it is the right shape for a 10 MiB
limit.

**It is the coroutine the brief asks for.** The brief wants
"async/coroutines/workers". This app has `async`/`await` everywhere and not one
generator-coroutine. A streaming ingestion pipeline is a place where the idiom
is genuinely the right tool rather than decoration — which is worth far more in
a showcase than a contrived example.

**It makes progress reporting natural.** Upload currently goes
`pending → processing → ready` with nothing in between. Per-batch means
"142/380 chunks" is free, and the SSE event protocol to carry it already exists.

A fourth, smaller one: Ollama's `embed` is natively batched, and we currently
hand it *every* chunk in a single call. For a large document that is one
enormous request. Batching is also the more robust call pattern.

## The trap that would eat a day

`vectors.upsert_chunks` **begins with `delete_document`**:

```python
async def upsert_chunks(session, owner_id, document_id, rows):
    await delete_document(session, document_id)   # ← here
    ...
```

That is correct today, because it is called exactly once per document and makes
re-ingestion idempotent. Call it once per batch and **each batch erases the
previous one** — you end up with only the final batch indexed, no error, and a
`chunk_count` that looks plausible. Almost certainly a silent wrong-answer bug
found weeks later.

So the streaming version needs the delete hoisted out: `begin_document()` once,
then `append_chunks()` per batch. That is a small, safe addition to
`vectors.py` — a new function, not a changed one.

## The other cost: atomicity

Today ingestion is one commit — a document is wholly indexed or not at all.
Committing per batch means a crash can leave a document half-indexed.

This is survivable here, and cheaply, because **re-ingestion is already
idempotent by design**: `begin_document()` clears whatever was there. So the
rule becomes "a document that failed mid-ingest is re-ingested, not repaired",
and `Document.status` / `error_message` become load-bearing rather than
decorative. Worth saying out loud, since it is a real change to a guarantee
that currently holds for free.

There is also a middle option: stream the *building* but keep one commit at the
end. Python memory stays bounded, atomicity is kept, and SQLite buffers the
transaction instead. Less pure, and probably the better first step.

## Sketch

```python
# app/services/ingest_stream.py  (new file — nothing existing changes)

async def vector_sink(
    session: AsyncSession, owner_id: uuid.UUID, document_id: uuid.UUID,
    batch_size: int = 64,
) -> AsyncGenerator[int, str | None]:
    """Consume chunk text, embed and write in batches, yield the running count.

    Primed with `await gen.asend(None)`, fed with `await gen.asend(text)`,
    flushed with `await gen.aclose()` — the async form of the pattern you
    described.
    """
    await vectors.begin_document(session, document_id)   # the hoisted delete
    pending: list[str] = []
    written = 0
    try:
        while True:
            try:
                chunk = yield written
            except GeneratorExit:
                break                       # aclose() — fall through and flush
            pending.append(chunk)
            if len(pending) >= batch_size:
                written += await _flush(session, owner_id, document_id, pending, written)
                pending.clear()
    finally:
        if pending:
            written += await _flush(session, owner_id, document_id, pending, written)
        await session.commit()
```

`chunk_text` becomes a generator (`yield` instead of building a list) so the
producer side streams too. Its current signature stays — a new
`iter_chunks(text)` beside it, with `chunk_text` kept as
`list(iter_chunks(text))` so every existing caller and test is untouched.

## Recommendation

Build it as `app/services/ingest_stream.py`, used **only by the document-upload
path**. Leave `rag.ingest_document` exactly as it is for the tutor, where a
lesson is one short text indexed synchronously and streaming buys nothing.

Two ingestion paths is a fair price for not touching a working one.

## Built — what changed from the sketch

Three things, all small:

**`anext(sink)` instead of `sink.asend(None)`.** Identical at runtime — priming
is priming — but the generator's send type is `str`, so `asend(None)` is a type
error under pyright strict. The spelling that type-checks is the one that
survives.

**The commit stays at the end**, as the "middle option" above recommended.
Python memory is bounded, which was the point; SQLite buffers the transaction,
so a document is still wholly indexed or not at all. `crud.clear_chunks` was
split out of `replace_chunks` for this — the same delete, without the commit.

**`ingest_streaming` counts what it feeds, not what the sink yields.** The
final partial batch is written during `aclose()`, after the last `yield` has
already happened, so the yielded number is progress and the fed count is the
answer. Every chunk fed is a chunk written, so they agree at the end.

`test_streaming_matches_the_whole_document_path` runs both paths over the same
text and asserts the same chunks in the same order — two implementations of one
thing is exactly the shape that drifts, so that is pinned rather than trusted.

---

# 2. Making `EmbeddingProvider` pluggable

Building on `docs/jelena/future3.md`, which you pointed me to.

## Where it already fits

The Protocol in `app/services/providers/base.py` needs no change — it declares
`model`, `dimensions`, `embed(texts)`, `health()`. And `DocumentChunk` already
stores `embedding_model` per row. That column exists for exactly this.

So the code shape is ready. **The obstacle is the index, not the interface.**

## The obstacle, precisely

`vec_chunks` is declared `float[768]` and `vec0` fixes the width at
creation-time. This is hard rule #5. A 384-dimension provider
(`all-MiniLM-L6-v2`) cannot share that table — not "should not", *cannot*.

Three ways out, and future3 already picked the right one:

| | |
|---|---|
| One table per dimension | ✅ recommended |
| One table, zero-padded to the widest | wasteful, and it changes the distances — a silent correctness bug |
| Re-embed everything on switch | honest, but throws away work and needs a migration command |

## The additive shape

The thing that makes this safe: **`vec_chunks` stays exactly as it is.** It
becomes "the index for 768-dimension models" by definition rather than by
migration. Existing rows never move, existing queries never change.

```python
# app/services/vectors.py — additive
def table_for(dimensions: int) -> str:
    # The original table keeps its name. Renaming it would be a migration,
    # and there are no migrations here.
    return VECTOR_TABLE if dimensions == 768 else f"{VECTOR_TABLE}_{dimensions}"
```

Every existing function takes the table from the active provider's
`dimensions`. With one provider configured, every call resolves to
`vec_chunks` and behaves identically — which is what makes this a change you
can ship without holding your breath.

Then:

1. `app/services/providers/sentence_transformers_provider.py` implementing the
   Protocol. `model.encode()` is blocking, so
   `await anyio.to_thread.run_sync(...)` — otherwise it stalls the event loop
   for every other request, which on a single-worker demo means the whole app.
2. `EMBEDDING_PROVIDER: Literal["ollama", "sentence_transformers"]` in config.
3. An optional extra — `uv sync --extra local-embed` — so the default install
   stays light. **`torch` is ~2 GB of wheels** against a project whose selling
   point is `uv sync` and go. It must not become a default dependency.

## The part that needs a decision, not just code

**Searching cannot mix embedding spaces.** Vectors from two models are not
comparable, so a query embedded with model A must only search A's table. Which
means: switch the provider, and every document indexed under the old one
**silently becomes unfindable**. Retrieval will not error — it will just quietly
return nothing from those documents.

That is the real cost, and it is a product question rather than a technical
one. Three honest answers:

- **Re-embed on switch** — a `uv run python -m app.scripts.reembed` command.
  Slow, explicit, correct.
- **Show it** — `GET /documents/` reports `indexed_with`, and the UI marks
  documents that the active provider cannot search. Honest and cheap.
- **Search both and merge** — do not. Scores from different spaces are not on a
  common scale, so the ranking would be meaningless while looking fine.

My recommendation is **show it, and offer re-embed as a command**. It matches
how this app handles the `grounded` flag: state the limitation plainly rather
than paper over it.

## What it buys the showcase

Honestly? Not better retrieval — `nomic-embed-text` at 768 is the stronger
model. What it buys is the *demonstration*: an app where the embedding provider
is genuinely swappable, with a second implementation proving the seam is real
rather than asserted. For a portfolio piece that is the point, and it is worth
saying that plainly rather than pretending 384 dimensions is an upgrade.

## Suggested order

1. `table_for(dimensions)` + threading it through `vectors.py`, with one
   provider configured. Pure refactor, no behaviour change, fully testable.
2. The sentence-transformers provider behind the optional extra.
3. `indexed_with` on the documents list, and the UI marker.
4. The re-embed script.

Steps 1 and 3 are worth doing even if the second provider never ships.

## Built — all four, in that order

**One name trap, found while building.** `vec0` creates its own ordinary
shadow tables sharing the prefix — `vec_chunks_info`, `vec_chunks_rowids`,
`vec_chunks_vector_chunks00`, and more. A suffix scheme of `vec_chunks_384`
would sit in the same namespace as tables the extension owns, and "list every
index" by name prefix would return tables that are not indexes and cannot be
queried as one. So the suffix carries a `d` (`vec_chunks_d384`), and
`vectors.vector_tables()` filters on `sql LIKE '%USING vec0%'` as well as the
name. Two tests pin it.

**`delete_document` spans every width, `search` spans exactly one.** Deleting
has to reach vectors left in a previous model's index, or switching providers
back would resurrect a deleted document. Searching must not, for the reason in
the section above.

**`indexed_with` is read from the chunk rows, not stored on `Document`.**
`create_all` adds missing tables but never missing columns and there are no
migrations here, so a new `Document` column simply would not exist on an
existing database. `DocumentChunk.embedding_model` has been recorded per row
since Milestone 1 and is already the answer — one `GROUP BY` per page.

**The sentence-transformers provider is written but not exercised.** It is
behind `uv sync --extra local-embed`, which is ~2 GB of torch wheels and is not
installed here, so it is typed and reviewed but has never run. Treat it as
untested until someone installs the extra and uploads a document. Two things it
already gets right and must keep: `encode()` runs in a worker thread
(`anyio.to_thread.run_sync`) because it is blocking CPU work that would
otherwise freeze the whole single-worker app, and the model loads on first use
rather than at construction, so a cold start does not download weights before
`/health` can answer.

## Still open

- **Progress reporting.** The sink yields a running count, which was one of the
  three reasons for building it, but upload is a background task with no SSE
  channel to the browser, so nothing reads it yet. `Document.chunk_count` still
  goes `pending → processing → ready` with nothing in between.
- **`reembed` re-embeds, it does not re-chunk.** `CHUNK_SIZE` changes are not
  covered by it. That is deliberate — chunk boundaries are what the stored
  passages *are* — but it means a chunking change still needs a re-upload.
- **The second provider needs one real run** before anything here claims it
  works.
