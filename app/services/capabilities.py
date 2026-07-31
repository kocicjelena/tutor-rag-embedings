"""What this app can actually do, right now, checked rather than claimed.

## Why this exists

Every README says "✅ available". Most of them are out of date, and none of
them were checked when you loaded the page. This module answers the same
question by **probing**: it asks Ollama whether it is there, opens a real MCP
session and counts the tools, loads `vec_version()` out of SQLite, and reports
what it found.

Anything it cannot check says so, rather than borrowing the confidence of the
things it can.

## The four statuses

| | |
|---|---|
| `running` | Verified **just now**, in this process, by a probe that succeeded |
| `built` | Committed and tested, but not verified here — either there is no way to probe it from inside, or the probe says it is not switched on |
| `building` | Started, unfinished, deliberately visible |
| `exploring` | Examined closely and **deliberately not served** |

`exploring` is the one worth having. It is not a backlog and not a failure —
these are things this app came near to building and then refused, because
building them would have made the rest of it mean less:

- a tool that generates text hides a second, unattributable model call inside
  the first, and turns the trace panel into a story about something that did
  not happen;
- merging results from two embedding spaces produces a ranking that looks
  perfectly ordered and means nothing;
- treating the browser's `localStorage` dashboard as "the model" would make
  the word *model* mean whatever was convenient.

Each one is a place where the easy version would have left the app looking the
same and being worth less. Recording them next to the working features is the
honest form of a showcase — and, for a project about ML, retrieval and model
protocols, the refusals are as much of the demonstration as the code.

## The rule for probes

A probe is **cheap, read-only, and cannot fail the request.** It gets a timeout
and its exception becomes evidence, never a 500. A status page that falls over
when a service is down is worse than no status page.
"""

import asyncio
import importlib.util
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    CapabilityArea,
    CapabilityPublic,
    CapabilityReport,
    CapabilityStatus,
)

logger = logging.getLogger(__name__)

# No probe may hold the page. Everything here is a local call except the Ollama
# reachability check, and that one is answering from localhost or not at all.
PROBE_TIMEOUT_SECONDS = 4.0


@dataclass(frozen=True)
class ProbeResult:
    """What a probe observed. `ok` decides between `running` and `built`."""

    ok: bool
    evidence: str


# A probe is given a session and the caller, because some of them need to look
# at that caller's own data (the tutor corpus) and none of them may look at
# anybody else's.
Probe = Callable[[AsyncSession, uuid.UUID], Awaitable[ProbeResult]]


@dataclass(frozen=True)
class Capability:
    key: str
    name: str
    area: CapabilityArea
    summary: str
    # Where the status lands when there is no probe, or the probe says no.
    declared: CapabilityStatus
    detail: str | None = None
    doc: str | None = None
    probe: Probe | None = field(default=None, compare=False)


# ──────────────────────────── Probes ────────────────────────────

async def _probe_vectors(session: AsyncSession, _owner: uuid.UUID) -> ProbeResult:
    from app.services import vectors

    version = (await session.execute(sql_text("select vec_version()"))).scalar_one()
    tables = await vectors.vector_tables(session)
    active = vectors.table_for()
    return ProbeResult(
        ok=True,
        evidence=(
            f"sqlite-vec {version}; {len(tables)} index(es), "
            f"active {active} at {vectors.active_dimensions()} dimensions"
        ),
    )


async def _probe_embedding(session: AsyncSession, _owner: uuid.UUID) -> ProbeResult:
    """Embed one short string. The only probe that costs real work — and the
    one worth it, because embedding sits on the *write* path: if it is down,
    every upload and every lesson silently stops being indexed."""
    from app.services.providers import get_embedding_provider

    embedder = get_embedding_provider()
    vector = (await embedder.embed(["status probe"]))[0]
    return ProbeResult(
        ok=len(vector) == embedder.dimensions,
        evidence=(
            f"{embedder.name}/{embedder.model} returned "
            f"{len(vector)} dimensions"
        ),
    )


async def _probe_generation(session: AsyncSession, _owner: uuid.UUID) -> ProbeResult:
    """Which generators are reachable — without generating anything.

    Deliberately does not send a prompt. A status page that spends the user's
    Anthropic balance every time it loads would be a bad joke.
    """
    from app.services.providers import describe_providers

    report = await describe_providers()
    live = [p.name for p in report.data if p.available]
    return ProbeResult(
        ok=bool(live),
        evidence=(
            f"reachable: {', '.join(live)}" if live
            else "no generator reachable — add a key, or start Ollama"
        ),
    )


async def _probe_mcp(session: AsyncSession, owner: uuid.UUID) -> ProbeResult:
    """Open a real client session and list the tools.

    Not a hard-coded four. If someone breaks the server, this goes red — which
    is the entire reason the check goes over the protocol rather than importing
    `app.mcp.tools` and counting functions.
    """
    from app.mcp import client as mcp_client

    tools = await mcp_client.list_tools(session=session, owner_id=owner)
    names = sorted(t.name for t in tools)
    return ProbeResult(
        ok=bool(names),
        evidence=f"{len(names)} tool(s) over a live session: {', '.join(names)}",
    )


async def _probe_agent(session: AsyncSession, owner: uuid.UUID) -> ProbeResult:
    """Is a tool-calling provider actually available to this caller?

    The loop is built and tested; whether it can *run* depends on there being a
    provider that implements `ToolCallingProvider` and is reachable. That is a
    per-caller question now that keys are per-user.
    """
    from app.services.providers import get_chat_provider
    from app.services.providers.base import (
        ProviderUnavailableError,
        ToolCallingProvider,
    )

    try:
        provider = get_chat_provider("claude")
    except ProviderUnavailableError as exc:
        return ProbeResult(
            ok=False, evidence=f"claude unavailable — {exc.detail}"
        )
    if not isinstance(provider, ToolCallingProvider):
        return ProbeResult(ok=False, evidence=f"{provider.name} cannot call tools")
    return ProbeResult(ok=True, evidence=f"{provider.name} implements stream_turn")


async def _probe_tutor(session: AsyncSession, owner: uuid.UUID) -> ProbeResult:
    """Does this learner's model hold anything? Owner-scoped, like everything."""
    from app.services import tutor_model

    stats = await tutor_model.corpus_stats(session=session, owner_id=owner)
    return ProbeResult(
        ok=stats.indexed_chunks > 0,
        evidence=(
            f"{stats.interactions} lesson(s), {stats.indexed_chunks} indexed passage(s)"
            if stats.indexed_chunks
            else "nothing indexed yet — teach it something"
        ),
    )


async def _probe_sentence_transformers(
    session: AsyncSession, _owner: uuid.UUID
) -> ProbeResult:
    """Is the optional second embedding backend installed?

    Import only — never loads a model. `built` here means exactly what it says:
    the code ships, the extra does not.
    """
    active = settings.EMBEDDING_PROVIDER == "sentence_transformers"
    # find_spec, not `import`: importing sentence_transformers pulls torch into
    # memory, which is seconds and hundreds of megabytes for a question that is
    # only "is it on disk". It returns None rather than raising when absent.
    if importlib.util.find_spec("sentence_transformers") is None:
        return ProbeResult(
            ok=False,
            evidence="not installed — `uv sync --extra local-embed` (~2 GB of torch)",
        )
    return ProbeResult(
        ok=active,
        evidence=(
            "installed and selected"
            if active
            else "installed, but EMBEDDING_PROVIDER=ollama"
        ),
    )


async def _probe_byok(session: AsyncSession, owner: uuid.UUID) -> ProbeResult:
    from app.services import user_keys

    record = await user_keys.get_record(
        session=session, owner_id=owner, provider=user_keys.ANTHROPIC
    )
    if record is None:
        return ProbeResult(ok=False, evidence="no key on file for this account")
    return ProbeResult(ok=True, evidence=f"key on file ({record.fingerprint})")


# ──────────────────────────── The registry ────────────────────────────

CAPABILITIES: list[Capability] = [
    # ── RAG ──────────────────────────────────────────────────
    Capability(
        key="vectors",
        name="Vector index",
        area="rag",
        summary="sqlite-vec, one index per embedding width, owner-scoped inside the index",
        declared="built",
        doc=".claude/rules/VECTORS.md",
        probe=_probe_vectors,
    ),
    Capability(
        key="embedding",
        name="Embedding",
        area="rag",
        summary="Local, always. Anthropic ships no embeddings API",
        declared="built",
        doc=".claude/rules/VECTORS.md",
        probe=_probe_embedding,
    ),
    Capability(
        key="streaming-ingest",
        name="Streaming ingestion",
        area="rag",
        summary="An async generator consumes chunks; peak memory is one batch, not one document",
        detail=(
            "asend()/aclose(), PEP 525. The delete is hoisted out of the batch "
            "loop — calling upsert_chunks per batch would erase every batch but "
            "the last, with no error and a plausible chunk count."
        ),
        declared="running",
        doc=".claude/rules/VECTORS.md",
    ),
    Capability(
        key="reembed",
        name="Re-embed command",
        area="rag",
        summary="Restores documents the active embedding model cannot search",
        detail=(
            "An operator action across every user, run maybe once a year. "
            "Deliberately a CLI command and not a route: as an endpoint it "
            "would need admin auth, a job queue and progress reporting to do "
            "badly what `uv run python -m app.scripts.reembed` does well."
        ),
        declared="built",
        doc=".claude/rules/DECISIONS.md",
    ),
    Capability(
        key="sentence-transformers",
        name="Second embedding backend",
        area="rag",
        summary="sentence-transformers, in-process, no Ollama daemon at all",
        detail=(
            "The proof that EmbeddingProvider is a real seam rather than an "
            "assertion — one provider is a claim, two is a demonstration. "
            "Behind an optional extra because torch must never become a "
            "default dependency for a project whose selling point is "
            "`uv sync` and go."
        ),
        declared="built",
        doc=".claude/rules/VECTORS.md",
        probe=_probe_sentence_transformers,
    ),

    # ── LLM ──────────────────────────────────────────────────
    Capability(
        key="generation",
        name="Generation",
        area="llm",
        summary="Ollama or Claude, chosen per request",
        declared="built",
        doc=".claude/rules/API.md",
        probe=_probe_generation,
    ),
    Capability(
        key="tutor",
        name="The tutor, and your model",
        area="llm",
        summary="Lessons are indexed as they are taught; recall answers from them only",
        detail=(
            "\"The model\" here is the learner's corpus — what they were "
            "taught — which exports as JSON and imports back. Not an ML model "
            "trained in the browser."
        ),
        declared="built",
        doc=".claude/rules/PLAN.md",
        probe=_probe_tutor,
    ),
    Capability(
        key="ollama-tools",
        name="Tool calling on Ollama",
        area="llm",
        summary="llama3.1 supports it; the provider method is not written",
        detail=(
            "One more stream_turn implementation and no change to the loop — "
            "which is what the provider-neutral types in providers/base.py "
            "were for. Postponed, not blocked."
        ),
        declared="building",
        doc=".claude/rules/MCP.md",
    ),

    # ── MCP ──────────────────────────────────────────────────
    Capability(
        key="mcp",
        name="MCP server and client",
        area="mcp",
        summary="Four tools over your own material, spoken over the real protocol",
        declared="built",
        doc=".claude/rules/MCP.md",
        probe=_probe_mcp,
    ),
    Capability(
        key="agent",
        name="Tool-calling agent",
        area="mcp",
        summary="The model picks the searches; every call shows in the trace",
        detail=(
            "A separate route rather than a flag on /query/stream: the agent is "
            "slower and costs more tokens, and making it a mode would tax every "
            "plain question. Its prompt is primed from your corpus so it does "
            "not spend a paid round discovering what the database answers in "
            "milliseconds."
        ),
        declared="built",
        doc=".claude/rules/MCP.md",
        probe=_probe_agent,
    ),
    Capability(
        key="mcp-outward",
        name="Outward MCP transport",
        area="mcp",
        summary="Letting an external client reach these tools",
        detail=(
            "Needs an authentication story first. Today the caller is a bearer "
            "token resolved by FastAPI; an externally mounted endpoint has "
            "nothing equivalent to feed app/mcp/context.py, and without that "
            "the tenant boundary is a suggestion."
        ),
        declared="building",
        doc=".claude/rules/MCP.md",
    ),

    # ── Identity ─────────────────────────────────────────────
    Capability(
        key="identity",
        name="The app as your identity provider",
        area="identity",
        summary="Register with an email; this app computes your id and issues it onward",
        detail=(
            "The point of the project, and mostly not built. You register with "
            "an email, the app derives your identity from it, and you are tied "
            "to this app rather than to Google — you keep that identity "
            "private and hand over only an address. What exists today is the "
            "derivation itself (`public_id`, a one-way HMAC, stable and safe "
            "in a URL). Registration, a page of your own by route, and issuing "
            "identity onward to DIDs are planned and unbuilt. The tutor and "
            "retrieval are what that identity accumulates and owns."
        ),
        declared="building",
        doc=".claude/rules/AUTH.md",
    ),
    Capability(
        key="byok",
        name="Bring your own key",
        area="identity",
        summary="Your Claude usage is billed to your Anthropic account, not this app's",
        detail=(
            "Only a sha256 and a fingerprint are stored, neither of which can "
            "call Anthropic. The working key lives in a browser session and is "
            "dropped when you close it. This is what makes a free public deploy "
            "affordable — and it is a stage, not the destination: asking every "
            "visitor to own an Anthropic account is a barrier most will not "
            "cross. The direction is that the app charges for itself and pays "
            "for its own models."
        ),
        declared="built",
        doc=".claude/rules/AUTH.md",
        probe=_probe_byok,
    ),
    Capability(
        key="paid-app",
        name="Paying for the app itself",
        area="identity",
        summary="The app earning, instead of requiring everyone to bring a key",
        detail=(
            "Nothing about billing exists in this codebase. For: the app stops "
            "being a cost centre, and a visitor no longer needs an Anthropic "
            "console account to try it. Against: payments mean an account "
            "model, a provider, invoices, tax and a support obligation — real "
            "work with no learning value for the LLM/RAG/MCP goals, and not "
            "undoable once someone has paid. Recorded so the simplification "
            "that got us to a first deploy stays a deferral rather than "
            "becoming the definition of the app."
        ),
        declared="building",
        doc=".claude/rules/AUTH.md",
    ),
    Capability(
        key="federated-login",
        name="Federated login",
        area="identity",
        summary="OIDC sign-in, and a public sign-up screen",
        detail="Waiting on identity-provider credentials. Nothing else is blocked by it.",
        declared="building",
        doc=".claude/rules/AUTH.md",
    ),

    # ── Deploy ───────────────────────────────────────────────
    Capability(
        key="docker",
        name="Container image",
        area="deploy",
        summary="One image for the Space, a laptop, and a VPS",
        detail=(
            "Written, committed and required — but never built: there is no "
            "Docker on the machine it was written on. The .dockerignore was "
            "simulated against the real tree (738 MB → 1.0 MB context) and the "
            "process supervision was smoke-tested, which found a real bug. "
            "Expect the first real build to find another."
        ),
        declared="built",
        doc=".claude/rules/DEPLOY-HF.md",
    ),
    Capability(
        key="rate-limiting",
        name="Rate limiting",
        area="deploy",
        summary="Must land before the public URL is shared",
        detail=(
            "A public URL with uploads, a login route, and a route that calls "
            "Anthropic once per attempt should not stay unmetered."
        ),
        declared="building",
        doc=".claude/rules/DECISIONS.md",
    ),

    # ── Explored, and deliberately refused ───────────────────
    #
    # The section this whole module exists for. Each of these would have left
    # the app looking the same and meaning less.
    Capability(
        key="x-generating-tools",
        name="MCP tools that generate text",
        area="mcp",
        summary="Refused — it would make the tool trace a story about something that did not happen",
        detail=(
            "An agent already has a model: the one that decided to call the "
            "tool. A tool that made its own LLM call would nest a second, "
            "unattributable generation inside the first and hide its cost. The "
            "trace panel would still look right, which is worse than looking "
            "wrong. Retrieval only; composition belongs to the caller — "
            "/tutor/recall is search_documents plus generation, done in the "
            "open."
        ),
        declared="exploring",
        doc=".claude/rules/MCP.md",
    ),
    Capability(
        key="x-merged-search",
        name="Searching across embedding spaces",
        area="rag",
        summary="Refused — the ranking would look perfectly ordered and mean nothing",
        detail=(
            "Vectors from two models are not comparable, so distances from two "
            "indexes are not on a common scale. Merging them returns a "
            "confident, sorted, meaningless list. Documents the active model "
            "cannot reach are marked unsearchable instead, and re-embedding is "
            "offered as a command. Honest and cheap."
        ),
        declared="exploring",
        doc=".claude/rules/VECTORS.md",
    ),
    Capability(
        key="x-tool-owner",
        name="An owner_id argument on tools",
        area="mcp",
        summary="Refused — it would turn the tenant boundary into a suggestion",
        detail=(
            "A tool's arguments are chosen by the model, so every parameter is "
            "untrusted input however authoritative it looks. One prompt that "
            "talked the model into a different UUID would read another "
            "learner's corpus. The caller comes from a context variable only an "
            "authenticated route can set, and two tests assert on the *shape* "
            "of every tool signature, because this regression would be silent."
        ),
        declared="exploring",
        doc=".claude/rules/MCP.md",
    ),
    Capability(
        key="x-word-overlap",
        name="Word-overlap similarity",
        area="rag",
        summary="Refused — measured against real retrieval and it simply does not work",
        detail=(
            "The inherited tutor compared questions to lessons by counting "
            "shared words. On a real question it scored 0.111 — below its own "
            "0.2 threshold, so it gave up and said it had not been taught, "
            "while semantic retrieval put the correct lesson first at 0.519. "
            "Keeping it would have made an app about embeddings not use them."
        ),
        declared="exploring",
        doc=".claude/rules/PLAN.md",
    ),
    Capability(
        key="x-localstorage-model",
        name="The browser dashboard as \"the model\"",
        area="llm",
        summary="Refused — it would make the word *model* mean whatever was convenient",
        detail=(
            "The proficiency bars and topic mastery in localStorage are a "
            "dashboard: cosmetic, per-browser, gone when you clear it. Calling "
            "that \"your model\" would be the easiest feature in the project "
            "and would hollow out the real one. The model is the indexed corpus "
            "on the server — it survives a new browser, it exports as a file, "
            "and it is what recall actually answers from."
        ),
        declared="exploring",
        doc=".claude/rules/PLAN.md",
    ),
    Capability(
        key="x-encrypted-keys",
        name="Encrypting API keys at rest",
        area="identity",
        summary="Refused — reversible means this app can read every user's key",
        detail=(
            "It sounds stronger than a hash and is weaker, because it is "
            "exactly the property being avoided. A hash is one-way, so "
            "\"stored hashed\" and \"bills the user\" cannot both be true of "
            "one stored value — which is why the plaintext lives in the "
            "caller's session and never on this server."
        ),
        declared="exploring",
        doc=".claude/rules/AUTH.md",
    ),
    Capability(
        key="x-claude-embeddings",
        name="A \"Claude embeddings\" provider",
        area="llm",
        summary="Refused — it does not exist",
        detail=(
            "Anthropic ships no embeddings endpoint. This is why there are two "
            "provider protocols rather than one, and why only *generation* is "
            "user-selectable. Recorded because it is the single most reasonable-"
            "sounding thing to add, and it cannot be added."
        ),
        declared="exploring",
        doc=".claude/rules/DECISIONS.md",
    ),
]


# ──────────────────────────── The report ────────────────────────────

async def _run(
    capability: Capability, session: AsyncSession, owner_id: uuid.UUID
) -> CapabilityPublic:
    """Resolve one capability. Never raises."""
    status: CapabilityStatus = capability.declared
    evidence: str | None = None
    probed = False

    if capability.probe is not None:
        probed = True
        try:
            result = await asyncio.wait_for(
                capability.probe(session, owner_id), PROBE_TIMEOUT_SECONDS
            )
            evidence = result.evidence
            # A probe can only promote to `running`. It never overrides
            # `building` or `exploring` — those are decisions, not observations,
            # and no runtime check can talk you out of one.
            if result.ok and capability.declared in ("built", "running"):
                status = "running"
            elif not result.ok and capability.declared == "running":
                status = "built"
        except TimeoutError:
            evidence = f"probe timed out after {PROBE_TIMEOUT_SECONDS:.0f}s"
            status = "built" if capability.declared == "running" else status
        except Exception as exc:
            # A status page that falls over when a service is down is worse
            # than no status page. The failure becomes the evidence.
            logger.warning("probe %s failed: %s", capability.key, exc)
            evidence = f"{type(exc).__name__}: {exc}"
            status = "built" if capability.declared == "running" else status

    return CapabilityPublic(
        key=capability.key,
        name=capability.name,
        area=capability.area,
        status=status,
        summary=capability.summary,
        detail=capability.detail,
        doc=capability.doc,
        evidence=evidence,
        probed=probed,
    )


async def report(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> CapabilityReport:
    """Probe everything and report what was found.

    **Sequentially, and that is not an oversight.** The obvious version of this
    function is `asyncio.gather` over the probes — they are independent, and
    the slowest is an Ollama round trip. It does not work: most of these probes
    touch the database, an `AsyncSession` is **not safe for concurrent use**,
    and gathering them raises *"this session is provisioning a new connection;
    concurrent operations are not permitted"*. Caught by
    `test_the_tutor_probe_is_owner_scoped`, which saw two probes lose their
    results to it.

    The alternative — a fresh session per probe — would restore concurrency,
    and it is not worth it here: every probe but one is a local call in the
    single-digit milliseconds, so the total is the embedding round trip either
    way. Sequential is the same wall-clock time and one less thing that can go
    subtly wrong.

    Each probe still has its own timeout, so one hung service cannot hold the
    page behind it.
    """
    results = [await _run(c, session, owner_id) for c in CAPABILITIES]

    totals: dict[str, int] = {}
    for item in results:
        totals[item.status] = totals.get(item.status, 0) + 1

    return CapabilityReport(
        data=list(results),
        generated_at=datetime.now(timezone.utc),
        totals=totals,
    )
