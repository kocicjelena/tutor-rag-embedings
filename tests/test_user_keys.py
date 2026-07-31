"""The derived public id, and bring-your-own Anthropic keys.

The claim being defended is narrow and worth stating: **this app never holds
anything that can call Anthropic on a user's behalf.** Several tests below
assert on storage contents and on route shapes rather than on behaviour,
because that claim fails silently — an "encrypted key" column added later for
convenience would break it while every functional test still passed.
"""

from pathlib import Path
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core import identity
from app.core.config import settings
from app.models import UserApiKey, UserPublic
from app.services import user_keys
from app.services.providers import get_chat_provider
from app.services.providers.claude_provider import ClaudeChatProvider
from tests.conftest import auth_headers, make_user

# Shaped like a real key so the prefix check passes; never sent anywhere.
FAKE_KEY = "sk-ant-api03-" + "T" * 40 + "WXYZ"
OTHER_KEY = "sk-ant-api03-" + "Q" * 40 + "6789"


@pytest.fixture(autouse=True)
def _never_call_anthropic(  # pyright: ignore[reportUnusedFunction]  (pytest fixture)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No test in this file may reach the network.

    `store()` verifies keys against Anthropic by default, which is right in
    production and unacceptable in a suite that must run offline.
    """

    async def _offline_verify(api_key: str) -> None:
        # Keep the real prefix check — it is the half that needs no network,
        # and the message it produces is what the 422 test asserts on.
        if not api_key.strip().startswith(user_keys.KEY_PREFIX):
            raise user_keys.InvalidApiKeyError(
                f"An Anthropic API key starts with {user_keys.KEY_PREFIX!r}."
            )

    monkeypatch.setattr(user_keys, "verify_with_anthropic", _offline_verify)


# ──────────────────────── the derived public id ────────────────────────

def test_public_id_is_deterministic() -> None:
    assert identity.derive_public_id("a@b.com") == identity.derive_public_id("a@b.com")


def test_public_id_normalises_case_and_whitespace() -> None:
    """One person, one handle — matching how emails are compared everywhere else."""
    assert identity.derive_public_id(" A@B.com ") == identity.derive_public_id("a@b.com")


def test_public_id_differs_per_user() -> None:
    assert identity.derive_public_id("a@b.com") != identity.derive_public_id("c@d.com")


def test_public_id_does_not_leak_the_email() -> None:
    """It goes in URLs on a public, crawlable page. It must reveal nothing."""
    email = "jelena.private@example.com"
    derived = identity.derive_public_id(email)
    assert email not in derived
    for fragment in ("jelena", "private", "example", "@"):
        assert fragment not in derived


def test_public_id_is_url_safe() -> None:
    derived = identity.derive_public_id("a@b.com")
    assert derived.isalnum() and derived.islower()
    assert len(derived) == identity.PUBLIC_ID_CHARS


def test_public_id_depends_on_the_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards the documented hazard: rotating the pepper breaks every link.

    Not a bug — but it must stay a *known* consequence, so if someone removes
    the pepper and makes this a plain hash, this test fails and says why.
    """
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "pepper-one")
    first = identity.derive_public_id("a@b.com")
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "pepper-two")
    assert identity.derive_public_id("a@b.com") != first


def test_matches_is_true_only_for_the_right_email() -> None:
    handle = identity.derive_public_id("a@b.com")
    assert identity.matches("a@b.com", handle)
    assert not identity.matches("c@d.com", handle)


def test_user_public_exposes_the_derived_id() -> None:
    payload = UserPublic(id=uuid.uuid4(), email="a@b.com").model_dump()
    assert payload["public_id"] == identity.derive_public_id("a@b.com")


# ──────────────────── what is stored, and what is not ────────────────────

def test_fingerprint_reveals_only_the_last_four() -> None:
    printed = user_keys.fingerprint(FAKE_KEY)
    assert printed == "sk-ant-…WXYZ"
    assert "T" * 10 not in printed


async def test_store_never_persists_the_plaintext(session: AsyncSession) -> None:
    """The central claim. Nothing in the row may be usable as a key."""
    alice = await make_user(session)
    await user_keys.store(session=session, owner_id=alice.id, api_key=FAKE_KEY)

    row = (
        await session.execute(
            select(UserApiKey).where(UserApiKey.owner_id == alice.id)
        )
    ).scalars().one()

    serialised = row.model_dump_json()
    assert FAKE_KEY not in serialised
    # Not even the middle of it — a partial key is still a leak.
    assert "T" * 20 not in serialised
    assert row.key_sha256 == user_keys.hash_key(FAKE_KEY)
    assert row.fingerprint == "sk-ant-…WXYZ"


async def test_no_column_can_hold_a_usable_key() -> None:
    """A shape test, deliberately.

    If someone adds `encrypted_key` or similar to make the key survive a
    session, this fails and points at the decision that ruled it out. The
    functional tests would all still pass.
    """
    fields = set(UserApiKey.model_fields)
    forbidden = {"key", "api_key", "plaintext", "encrypted_key", "secret", "token"}
    assert not fields & forbidden, (
        f"{fields & forbidden} would make this table worth stealing — "
        "see app/services/user_keys.py"
    )


async def test_storing_again_rotates_rather_than_duplicates(
    session: AsyncSession,
) -> None:
    alice = await make_user(session)
    await user_keys.store(session=session, owner_id=alice.id, api_key=FAKE_KEY)
    await user_keys.store(session=session, owner_id=alice.id, api_key=OTHER_KEY)

    rows = (
        await session.execute(
            select(UserApiKey).where(UserApiKey.owner_id == alice.id)
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].key_sha256 == user_keys.hash_key(OTHER_KEY)


async def test_a_bad_key_is_rejected_before_anything_is_written(
    session: AsyncSession,
) -> None:
    alice = await make_user(session)
    with pytest.raises(user_keys.InvalidApiKeyError):
        await user_keys.store(
            session=session, owner_id=alice.id, api_key="not-a-key"
        )
    assert await user_keys.get_record(session=session, owner_id=alice.id) is None


async def test_keys_are_owner_scoped(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    await user_keys.store(session=session, owner_id=alice.id, api_key=FAKE_KEY)

    assert await user_keys.get_record(session=session, owner_id=bob.id) is None


# ──────────────────── who gets billed ────────────────────

def test_a_caller_key_produces_a_provider_bound_to_it() -> None:
    provider = get_chat_provider("claude", api_key=FAKE_KEY)
    assert isinstance(provider, ClaudeChatProvider)
    assert provider.billed_to_caller
    # Usable even though this app has no key of its own — the whole point.
    assert not settings.claude_available
    assert provider.available


def test_each_caller_gets_a_separate_provider_instance() -> None:
    """No caching, so one user's credential can never be handed to another."""
    first = get_chat_provider("claude", api_key=FAKE_KEY)
    second = get_chat_provider("claude", api_key=OTHER_KEY)
    assert first is not second


def test_without_a_caller_key_claude_is_unavailable_here() -> None:
    """conftest sets no ANTHROPIC_API_KEY, so this is the public-deploy case."""
    from app.services.providers import ProviderUnavailableError

    with pytest.raises(ProviderUnavailableError):
        get_chat_provider("claude")


def test_ollama_ignores_a_caller_key() -> None:
    """Local generation has nothing to bill; the key must not change routing."""
    plain = get_chat_provider("ollama")
    with_key = get_chat_provider("ollama", api_key=FAKE_KEY)
    assert plain is with_key


# ──────────────────── the HTTP surface ────────────────────

async def test_key_routes_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/keys/anthropic")).status_code == 401
    assert (
        await client.put("/api/v1/keys/anthropic", json={"api_key": FAKE_KEY})
    ).status_code == 401
    assert (await client.delete("/api/v1/keys/anthropic")).status_code == 401


async def test_put_then_get_never_returns_the_key(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    put = await client.put(
        "/api/v1/keys/anthropic", json={"api_key": FAKE_KEY}, headers=headers
    )
    assert put.status_code == 200, put.text
    assert FAKE_KEY not in put.text
    assert put.json()["fingerprint"] == "sk-ant-…WXYZ"

    get = await client.get("/api/v1/keys/anthropic", headers=headers)
    assert get.status_code == 200
    assert FAKE_KEY not in get.text
    body = get.json()
    assert body["configured"] is True
    assert body["key"]["fingerprint"] == "sk-ant-…WXYZ"
    # No app key in the test env, so a user without their own gets no Claude.
    assert body["app_key_fallback"] is False


async def test_status_is_honest_when_no_key_is_set(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    body = (await client.get("/api/v1/keys/anthropic", headers=headers)).json()
    assert body["configured"] is False
    assert body["key"] is None


async def test_put_rejects_a_malformed_key(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    response = await client.put(
        "/api/v1/keys/anthropic", json={"api_key": "hunter2xx"}, headers=headers
    )
    assert response.status_code == 422
    assert "sk-ant-" in response.json()["detail"]


async def test_delete_removes_the_record(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)
    await client.put(
        "/api/v1/keys/anthropic", json={"api_key": FAKE_KEY}, headers=headers
    )

    assert (await client.delete("/api/v1/keys/anthropic", headers=headers)).status_code == 200
    assert (
        await client.get("/api/v1/keys/anthropic", headers=headers)
    ).json()["configured"] is False


async def test_one_user_cannot_see_another_users_key(
    session: AsyncSession, client: AsyncClient
) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    alice_headers = await auth_headers(client, alice.email)
    await client.put(
        "/api/v1/keys/anthropic", json={"api_key": FAKE_KEY}, headers=alice_headers
    )

    bob_headers = await auth_headers(client, bob.email)
    body = (await client.get("/api/v1/keys/anthropic", headers=bob_headers)).json()
    assert body["configured"] is False


async def test_no_key_route_can_ever_return_a_plaintext_key() -> None:
    """Shape test over the response schemas, not over one response.

    A `GET /keys/anthropic/reveal` added later "just for the owner" would be a
    single change away from an exfiltration bug. Nothing in these schemas may
    carry a key-shaped field.
    """
    from app.models import UserApiKeyPublic, UserApiKeyStatus

    for schema in (UserApiKeyPublic, UserApiKeyStatus):
        fields = set(schema.model_fields)
        assert not fields & {"api_key", "key_sha256", "plaintext", "secret"}, (
            f"{schema.__name__} exposes something it should not"
        )


async def test_providers_route_offers_claude_once_a_key_is_set(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public-deploy case: no app key, but this visitor brought one.

    conftest replaces the registry with Ollama alone, so Claude is put back for
    this one test — `list_models` on it is a hard-coded list, not a network call.
    """
    from app.services.providers import registry

    monkeypatch.setitem(registry._chat_providers, "claude", ClaudeChatProvider())  # pyright: ignore[reportPrivateUsage]

    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)

    def claude_entry(payload: dict[str, Any]) -> dict[str, Any]:
        entries = [p for p in payload["data"] if p["name"] == "claude"]
        assert entries, f"claude missing from {[p['name'] for p in payload['data']]}"
        return entries[0]

    before = claude_entry((await client.get("/api/v1/providers/", headers=headers)).json())
    assert before["available"] is False
    assert "your own Anthropic API key" in (before["detail"] or "")

    await client.put(
        "/api/v1/keys/anthropic", json={"api_key": FAKE_KEY}, headers=headers
    )

    after = claude_entry((await client.get("/api/v1/providers/", headers=headers)).json())
    assert after["available"] is True


async def test_the_header_reaches_the_provider(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: `X-Anthropic-Key` on the request becomes the billing key."""
    seen: dict[str, Any] = {}

    def _capture(name: str | None = None, *, api_key: str | None = None) -> Any:
        seen["provider"] = name
        seen["api_key"] = api_key
        from tests.conftest import StubChatProvider

        return StubChatProvider()

    monkeypatch.setattr("app.api.routes.query.get_chat_provider", _capture)

    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)
    headers["X-Anthropic-Key"] = FAKE_KEY

    response = await client.post(
        "/api/v1/query/",
        json={"question": "anything", "provider": "claude"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert seen["api_key"] == FAKE_KEY


async def test_no_header_means_no_caller_key(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def _capture(name: str | None = None, *, api_key: str | None = None) -> Any:
        seen["api_key"] = api_key
        from tests.conftest import StubChatProvider

        return StubChatProvider()

    monkeypatch.setattr("app.api.routes.query.get_chat_provider", _capture)

    alice = await make_user(session)
    headers = await auth_headers(client, alice.email)
    await client.post("/api/v1/query/", json={"question": "anything"}, headers=headers)

    assert seen["api_key"] is None


# ──────────────── BYOK must stay live on the deployed Space ────────────────
#
# Jelena's standing instruction, 2026-07-31: adding your own Anthropic key
# stays a feature on the Space — distant from the identity plan, independent of
# it, but live. These two guard the deploy-time settings, because the failure
# they prevent does not look like a config mistake: it looks like Claude is
# broken.

def test_the_image_keeps_user_keys_switched_on() -> None:
    """With ALLOW_APP_KEY_FALLBACK=false beside it, turning this off leaves the
    Space with no route to Claude at all."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    body = dockerfile.read_text()

    assert "USER_ANTHROPIC_KEYS=true" in body, (
        "the deployed image must let visitors bring their own Anthropic key"
    )
    assert "ALLOW_APP_KEY_FALLBACK=false" in body, (
        "a public URL must not spend the operator's balance"
    )


def test_byok_is_on_by_default_in_config() -> None:
    """A visitor with their own key reaches Claude even when the app has none."""
    from app.core.config import Settings

    assert Settings().USER_ANTHROPIC_KEYS is True
