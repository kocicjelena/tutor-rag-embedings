"""The public user id — derived, not stored.

Jelena's ask: *"id will be calculated in app (some crypt value derived to every
user who register)"*.

`User.id` is a random UUID and stays the internal key. This module adds a
second, **public** identifier derived from the email, for anywhere a user has
to be named outside the database: a URL segment, a shared link, a log line.

Three properties, and each one is the reason for a design choice:

**Deterministic.** The same email always derives the same id, so a link keeps
working and re-registration lands on the same handle. That rules out a random
value stored in a column.

**Does not leak the email.** A public page keyed by `jelena@gmail.com` — or by
anything reversible to it — publishes her address to every crawler that reads
it. So the derivation is one-way.

**Not guessable from the email alone.** This is why it is an HMAC and not a
plain hash. With `sha256(email)` anyone can take a list of addresses, hash
each one, and ask the app whether that user exists — a membership oracle for
free. The server-side pepper makes that impossible without stealing the pepper.

**Rotating the pepper changes every public id.** They are derived, never
stored, so there is nothing to migrate — but old links break. Treat
`IDENTITY_PEPPER` as permanent once anything is published.
"""

import base64
import hashlib
import hmac

from app.core.config import settings

# 130 bits of the digest, base32'd. Long enough that guessing is hopeless,
# short enough to read out loud. Base32 (not base64url) because the result
# lands in URLs and gets copied by hand: no case sensitivity, no `-`/`_`
# confusion, no padding.
PUBLIC_ID_CHARS = 26


def normalise_email(email: str) -> str:
    """Lowercase and strip, so one person derives one id.

    `Jelena@Example.com ` and `jelena@example.com` are the same account
    everywhere else in this app — `crud.get_user_by_email` matches on the
    stored string — so they must derive the same public id too. Anything else
    would hand one user two links that both work.
    """
    return email.strip().lower()


def _pepper() -> bytes:
    """The HMAC key.

    Falls back to `SECRET_KEY` when unset, so the app runs without one more
    required env var. The coupling is worth stating plainly: with no dedicated
    pepper, rotating `SECRET_KEY` — which you would do after a token leak, and
    should be able to do freely — silently changes every public id. Set
    `IDENTITY_PEPPER` before publishing any link.
    """
    configured = settings.IDENTITY_PEPPER.strip()
    return (configured or settings.SECRET_KEY).encode()


def derive_public_id(email: str) -> str:
    """The public handle for an email. One-way, stable, unguessable."""
    digest = hmac.new(_pepper(), normalise_email(email).encode(), hashlib.sha256).digest()
    encoded = base64.b32encode(digest).decode().rstrip("=").lower()
    return encoded[:PUBLIC_ID_CHARS]


def matches(email: str, public_id: str) -> bool:
    """Whether `public_id` is the handle for `email`. Constant-time."""
    return hmac.compare_digest(derive_public_id(email), public_id.strip().lower())
