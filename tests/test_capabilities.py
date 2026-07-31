"""The status report — the app describing itself.

The thing actually being protected here is honesty. A status page whose green
rows are hard-coded is worse than no status page, so the tests care about
*where a status came from* at least as much as what it says:

  * a probe may promote to `running`, and may never talk you out of a decision;
  * a probe that explodes becomes evidence, not a 500;
  * `exploring` entries must carry the reasoning, because a refusal without a
    reason is indistinguishable from an omission.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CapabilityPublic
from app.services import capabilities
from app.services.capabilities import Capability, ProbeResult
from tests.conftest import auth_headers, make_user


# ──────────────────────── The registry itself ────────────────────────

def test_every_key_is_unique() -> None:
    keys = [c.key for c in capabilities.CAPABILITIES]
    assert len(keys) == len(set(keys))


def test_every_refusal_explains_itself() -> None:
    """A refusal without a reason is indistinguishable from an oversight.

    This is the assertion that keeps `exploring` meaningful. Anyone adding one
    has to say what would have gone wrong, and where it is written down.
    """
    refused = [c for c in capabilities.CAPABILITIES if c.declared == "exploring"]
    assert len(refused) >= 5, "the refusals are half the point of this page"
    for item in refused:
        assert item.detail, f"{item.key} refuses without saying why"
        assert len(item.detail) > 120, f"{item.key}'s reason is too thin to be one"
        assert item.doc, f"{item.key} does not say where the decision is recorded"


def test_no_capability_claims_running_without_a_probe() -> None:
    """`running` means measured. A declared `running` would be a lie by default.

    One exception, and it is deliberate: `streaming-ingest` cannot be probed
    without uploading a document, and it runs on every upload this app has ever
    done. It is declared, and the UI says out loud that it was not measured.
    """
    declared_running = {
        c.key for c in capabilities.CAPABILITIES
        if c.declared == "running" and c.probe is None
    }
    assert declared_running == {"streaming-ingest"}


def test_every_capability_has_a_summary_short_enough_to_scan() -> None:
    for c in capabilities.CAPABILITIES:
        assert c.summary
        assert len(c.summary) < 110, f"{c.key} summary is too long for a row"


# ──────────────────────── How a status is decided ────────────────────────

async def _resolve(
    capability: Capability, session: AsyncSession, owner: uuid.UUID
) -> CapabilityPublic:
    return await capabilities._run(  # pyright: ignore[reportPrivateUsage]
        capability, session, owner
    )


async def test_a_successful_probe_promotes_built_to_running(
    session: AsyncSession,
) -> None:
    alice = await make_user(session)

    async def yes(_s: AsyncSession, _o: uuid.UUID) -> ProbeResult:
        return ProbeResult(ok=True, evidence="it answered")

    result = await _resolve(
        Capability(
            key="x", name="X", area="rag", summary="s", declared="built", probe=yes
        ),
        session,
        alice.id,
    )
    assert result.status == "running"
    assert result.evidence == "it answered"
    assert result.probed is True


async def test_a_failing_probe_demotes_running_to_built(
    session: AsyncSession,
) -> None:
    alice = await make_user(session)

    async def no(_s: AsyncSession, _o: uuid.UUID) -> ProbeResult:
        return ProbeResult(ok=False, evidence="not switched on")

    result = await _resolve(
        Capability(
            key="x", name="X", area="rag", summary="s", declared="running", probe=no
        ),
        session,
        alice.id,
    )
    assert result.status == "built"


async def test_a_probe_cannot_overrule_a_decision(session: AsyncSession) -> None:
    """The one that matters.

    `exploring` and `building` are decisions. No runtime observation can talk
    you out of one — a probe that happens to succeed must not quietly promote
    a refused feature to "running" and erase the reasoning with it.
    """
    alice = await make_user(session)

    async def yes(_s: AsyncSession, _o: uuid.UUID) -> ProbeResult:
        return ProbeResult(ok=True, evidence="technically reachable")

    for declared in ("exploring", "building"):
        result = await _resolve(
            Capability(
                key="x",
                name="X",
                area="mcp",
                summary="s",
                declared=declared,  # pyright: ignore[reportArgumentType]
                probe=yes,
            ),
            session,
            alice.id,
        )
        assert result.status == declared


async def test_a_probe_that_raises_becomes_evidence_not_a_crash(
    session: AsyncSession,
) -> None:
    """A status page that falls over when a service is down is worse than none."""
    alice = await make_user(session)

    async def boom(_s: AsyncSession, _o: uuid.UUID) -> ProbeResult:
        raise ConnectionError("ollama is not running")

    result = await _resolve(
        Capability(
            key="x", name="X", area="rag", summary="s", declared="running", probe=boom
        ),
        session,
        alice.id,
    )
    assert result.status == "built"
    assert result.evidence is not None
    assert "ollama is not running" in result.evidence


async def test_a_hanging_probe_times_out_rather_than_holding_the_page(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    alice = await make_user(session)
    monkeypatch.setattr(capabilities, "PROBE_TIMEOUT_SECONDS", 0.05)

    async def forever(_s: AsyncSession, _o: uuid.UUID) -> ProbeResult:
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    result = await _resolve(
        Capability(
            key="x",
            name="X",
            area="rag",
            summary="s",
            declared="running",
            probe=forever,
        ),
        session,
        alice.id,
    )
    assert result.status == "built"
    assert result.evidence is not None and "timed out" in result.evidence


# ──────────────────────── The whole report ────────────────────────

async def test_the_report_covers_every_capability(session: AsyncSession) -> None:
    alice = await make_user(session)
    report = await capabilities.report(session=session, owner_id=alice.id)

    assert len(report.data) == len(capabilities.CAPABILITIES)
    assert sum(report.totals.values()) == len(report.data)


async def test_the_real_probes_survive_the_stub_environment(
    session: AsyncSession,
) -> None:
    """No Ollama and no Anthropic key in the suite, and it must still report.

    That is the realistic failure case — a machine where half the services are
    absent — so the whole registry runs here rather than a fixture of two.
    """
    alice = await make_user(session)
    report = await capabilities.report(session=session, owner_id=alice.id)

    assert report.totals.get("exploring", 0) >= 5
    # The vector index and MCP are both local and must be genuinely live.
    live = {c.key for c in report.data if c.status == "running"}
    assert "vectors" in live
    assert "mcp" in live


async def test_mcp_is_counted_over_a_real_session(session: AsyncSession) -> None:
    """The probe lists tools over the protocol, so it tracks the real server."""
    alice = await make_user(session)
    report = await capabilities.report(session=session, owner_id=alice.id)

    mcp = next(c for c in report.data if c.key == "mcp")
    assert mcp.status == "running"
    assert mcp.evidence is not None
    assert "search_documents" in mcp.evidence


async def test_the_tutor_probe_is_owner_scoped(session: AsyncSession) -> None:
    """Every read in this app is scoped to one owner, including this one."""
    alice = await make_user(session)
    bob = await make_user(session)

    from app import crud
    from app.models import DocumentChunk
    from app.services.vectors import upsert_chunks

    doc = await crud.create_document(
        session=session,
        owner_id=alice.id,
        title="A lesson",
        description="Embeddings",
        file_type="tutor/interaction",
    )
    chunk = DocumentChunk(
        document_id=doc.id, content="banana", chunk_index=0, embedding_model="stub-embed"
    )
    await crud.replace_chunks(session=session, document_id=doc.id, chunks=[chunk])
    await upsert_chunks(session, alice.id, doc.id, [(chunk.id, [0.0, 1.0, 0.0, 0.0])])
    await session.commit()

    hers = await capabilities.report(session=session, owner_id=alice.id)
    his = await capabilities.report(session=session, owner_id=bob.id)

    alice_tutor = next(c for c in hers.data if c.key == "tutor")
    bob_tutor = next(c for c in his.data if c.key == "tutor")

    assert alice_tutor.status == "running"
    assert bob_tutor.status == "built"
    assert bob_tutor.evidence is not None
    assert "nothing indexed" in bob_tutor.evidence


# ──────────────────────── The route ────────────────────────

async def test_the_route_requires_a_token(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/status/")).status_code == 401


async def test_the_route_reports(session: AsyncSession, client: AsyncClient) -> None:
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    response = await client.get("/api/v1/status/", headers=headers)
    assert response.status_code == 200

    body = response.json()
    assert body["totals"]
    assert body["generated_at"]

    keys = {row["key"] for row in body["data"]}
    assert {"mcp", "vectors", "byok", "docker"} <= keys

    # Every row the UI needs, present and typed.
    for row in body["data"]:
        assert row["status"] in ("running", "built", "building", "exploring")
        assert row["area"] in ("llm", "rag", "mcp", "identity", "deploy")
        assert isinstance(row["probed"], bool)


async def test_no_probe_leaks_a_secret(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Evidence strings are rendered in a browser. A fingerprint is fine; a key
    never is, and neither is anything else that could be pasted into a curl."""
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    raw = (await client.get("/api/v1/status/", headers=headers)).text
    assert "sk-ant-" not in raw
    assert "SECRET_KEY" not in raw
    assert "password" not in raw.lower()
