"""Per-user Anthropic keys — so the user pays for their own Claude usage.

The problem this solves is in `docs/PLAN.md` §6: a public deploy with paid
Claude calls behind it is an open invoice. On Hugging Face Spaces there is no
Ollama, so Claude is the *only* generator — which turns "who pays" from a
detail into the thing that decides whether the demo can be public at all.

## What is stored, and what is not

**Never the plaintext.** Only:

  * `key_sha256`  — one-way. Recognises the same key again.
  * `fingerprint` — `sk-ant-…AB12`, for display.

Neither can call Anthropic. A dump of `user_api_key` is worth nothing.

The working key lives in the caller's session and arrives on each request as a
header. It is used for that request and dropped.

## Why not encrypt it at rest instead?

Encryption is reversible — that is the point of it, and also the problem. An
encrypted column plus the server's key means the app *can* read every user's
Anthropic key, so a server compromise leaks all of them at once, and Jelena
would be holding credentials she never wanted to hold. Hashing gives up the
convenience of "never re-enter your key" and buys the guarantee instead. That
was the explicit choice (2026-07-30).

## Why hash a secret that is already high-entropy?

Plain SHA-256, not bcrypt. `sk-ant-…` keys are long random strings, not
human-chosen passwords, so there is no dictionary to attack and no need for a
slow KDF. The hash exists to *recognise* a key, not to withstand cracking of a
guessable one.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone

import anthropic
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models import UserApiKey, UserApiKeyPublic, UserApiKeyStatus

logger = logging.getLogger(__name__)

ANTHROPIC = "anthropic"

# Anthropic keys start with this. Checked before spending a network round trip
# on something that is obviously not a key — a pasted password, say.
KEY_PREFIX = "sk-ant-"

# Characters of the key kept for display. Four is the card-number convention:
# enough for the owner to recognise which key it is, useless to anyone else.
FINGERPRINT_TAIL = 4


class InvalidApiKeyError(ValueError):
    """The key is malformed, or Anthropic rejected it.

    Raised before anything is written, so a bad key never lands in the table.
    """


def fingerprint(api_key: str) -> str:
    """`sk-ant-…AB12` — recognisable to its owner, useless to anyone else."""
    tail = api_key.strip()[-FINGERPRINT_TAIL:]
    return f"{KEY_PREFIX}…{tail}"


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.strip().encode()).hexdigest()


async def verify_with_anthropic(api_key: str) -> None:
    """Confirm the key works, by making the cheapest real call there is.

    Listing models costs no tokens, so this does not bill the user to find out
    whether they can be billed. It also means a typo is caught at the moment
    they paste it, rather than surfacing as a confusing 503 in the middle of
    their first question.
    """
    cleaned = api_key.strip()
    if not cleaned.startswith(KEY_PREFIX):
        raise InvalidApiKeyError(
            f"An Anthropic API key starts with {KEY_PREFIX!r}. "
            "Create one at console.anthropic.com → API keys."
        )

    client = AsyncAnthropic(api_key=cleaned)
    try:
        await client.models.list(limit=1)
    except anthropic.AuthenticationError:
        raise InvalidApiKeyError(
            "Anthropic rejected that key. Check it was copied whole, and that "
            "it has not been revoked."
        ) from None
    except anthropic.APIConnectionError:
        raise InvalidApiKeyError(
            "Could not reach Anthropic to check the key. Try again shortly."
        ) from None
    except anthropic.APIStatusError as exc:
        raise InvalidApiKeyError(
            f"Anthropic returned {exc.status_code} while checking the key."
        ) from None
    finally:
        await client.close()


async def get_record(
    *, session: AsyncSession, owner_id: uuid.UUID, provider: str = ANTHROPIC
) -> UserApiKey | None:
    result = await session.execute(
        select(UserApiKey)
        .where(UserApiKey.owner_id == owner_id)
        .where(UserApiKey.provider == provider)
    )
    return result.scalars().first()


async def store(
    *,
    session: AsyncSession,
    owner_id: uuid.UUID,
    api_key: str,
    provider: str = ANTHROPIC,
    verify: bool = True,
) -> UserApiKey:
    """Verify a key, then keep only what cannot be used.

    Replaces any existing record for this provider — one key per user per
    provider, so pasting a new one is a rotation rather than a second entry
    nobody can tell apart.
    """
    if verify:
        await verify_with_anthropic(api_key)

    record = await get_record(session=session, owner_id=owner_id, provider=provider)
    if record is None:
        record = UserApiKey(owner_id=owner_id, provider=provider, key_sha256="", fingerprint="")

    record.key_sha256 = hash_key(api_key)
    record.fingerprint = fingerprint(api_key)
    record.last_used_at = None
    session.add(record)
    await session.commit()
    await session.refresh(record)

    # Fingerprint only. Never log a key, not even at debug — logs travel.
    logger.info("stored %s key %s for %s", provider, record.fingerprint, owner_id)
    return record


async def revoke(
    *, session: AsyncSession, owner_id: uuid.UUID, provider: str = ANTHROPIC
) -> bool:
    record = await get_record(session=session, owner_id=owner_id, provider=provider)
    if record is None:
        return False
    await session.delete(record)
    await session.commit()
    return True


async def note_use(
    *, session: AsyncSession, owner_id: uuid.UUID, api_key: str, provider: str = ANTHROPIC
) -> None:
    """Record that a key was used, if it is the one we know about.

    Best effort and deliberately quiet: this is a "last used" timestamp for the
    owner's own screen, not an audit log, and it must never be the reason a
    perfectly good Claude answer fails to return.
    """
    try:
        record = await get_record(session=session, owner_id=owner_id, provider=provider)
        if record is None or record.key_sha256 != hash_key(api_key):
            return
        record.last_used_at = datetime.now(timezone.utc)
        session.add(record)
        await session.commit()
    except Exception:
        logger.warning("could not record key use for %s", owner_id, exc_info=True)


def to_public(record: UserApiKey) -> UserApiKeyPublic:
    return UserApiKeyPublic(
        provider=record.provider,
        fingerprint=record.fingerprint,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
    )


async def status_for(
    *, session: AsyncSession, owner_id: uuid.UUID
) -> UserApiKeyStatus:
    record = await get_record(session=session, owner_id=owner_id)
    return UserApiKeyStatus(
        configured=record is not None,
        key=to_public(record) if record else None,
        app_key_fallback=settings.claude_available,
    )
