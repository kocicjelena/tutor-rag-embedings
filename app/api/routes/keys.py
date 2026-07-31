"""The caller's own Anthropic key — add, inspect, remove.

Why this exists: on a public deploy there is no Ollama, so Claude is the only
generator, and every visitor's question would otherwise be spent from Jelena's
Anthropic balance. A user who brings their own key is billed by Anthropic
directly, and this app never holds anything worth stealing.

**No route here can return a key.** `POST` takes one and gives back a
fingerprint; `GET` returns metadata only. There is deliberately no read
endpoint — not for the owner, not for a superuser. A key that cannot be read
back cannot be leaked by a bug in this file.

The plaintext reaches Claude a different way entirely: the client holds it and
sends it per request as `X-Anthropic-Key`, which `deps.get_caller_anthropic_key`
picks up. It is never written to the database. See `app/services/user_keys.py`.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    Message,
    UserApiKeyCreate,
    UserApiKeyPublic,
    UserApiKeyStatus,
)
from app.services import user_keys

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/keys", tags=["keys"])

DISABLED = "User-supplied API keys are switched off on this deployment."


def _require_enabled() -> None:
    if not settings.USER_ANTHROPIC_KEYS:
        raise HTTPException(status_code=404, detail=DISABLED)


@router.get("/anthropic", response_model=UserApiKeyStatus)
async def key_status(
    session: SessionDep, current_user: CurrentUser
) -> UserApiKeyStatus:
    """Whether you have a key on file, and what this app does without one.

    `app_key_fallback` is the honest part: false means no key, no Claude.
    """
    _require_enabled()
    return await user_keys.status_for(session=session, owner_id=current_user.id)


@router.put("/anthropic", response_model=UserApiKeyPublic)
async def set_key(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: UserApiKeyCreate,
) -> UserApiKeyPublic:
    """Hand over an Anthropic key. Verified, hashed, and the plaintext dropped.

    `PUT` rather than `POST`: sending a second key replaces the first, which is
    idempotent in the way PUT describes. One key per user — two would leave
    nobody able to say which one is being billed.

    Rejected keys never reach the database, so a typo cannot leave a broken
    record behind.
    """
    _require_enabled()
    try:
        record = await user_keys.store(
            session=session, owner_id=current_user.id, api_key=body.api_key
        )
    except user_keys.InvalidApiKeyError as exc:
        # 422, not 503: the key is the user's input and the fix is theirs.
        raise HTTPException(status_code=422, detail=str(exc)) from None

    return user_keys.to_public(record)


@router.delete("/anthropic", response_model=Message)
async def delete_key(session: SessionDep, current_user: CurrentUser) -> Message:
    """Forget the key. Nothing recoverable was held, so this only drops metadata."""
    _require_enabled()
    removed = await user_keys.revoke(session=session, owner_id=current_user.id)
    return Message(
        message="Key removed." if removed else "No key was on file."
    )
