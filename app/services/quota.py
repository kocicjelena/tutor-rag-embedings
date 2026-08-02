"""The free tier — and the message a person gets when they reach the end of it.

Jelena's decision, 2026-08-02: a visitor may upload a few documents and take a
few lessons, and beyond that the app costs money to run and asks them to get in
touch. Payments are **not built** and are not close; this is the limit and the
explanation, which is the half that can exist honestly on its own.

## What is counted, and what is deliberately not

Only the two things that cost money to host:

    uploads   disk, plus embedding CPU over a whole file
    lessons   one embedding round trip each

Everything that *demonstrates* the app is unlimited and should stay that way:
reading, searching, recall, the agent, the MCP catalogue, `/status`, and both
model downloads. This is a showcase before it is a product, and a wall in front
of the parts worth showing would hide the work rather than sell it. Claude
generation is not counted either — bring-your-own-key means the visitor's own
account is already paying for it.

## Counted from the data, not from a counter

There is no `usage` table. Uploads are *documents you currently have* and
lessons are *lessons you have been taught*, both read with a `SELECT COUNT`.

That is a deliberate trade. A counter column would be cumulative and exact; it
would also be a second source of truth that can drift from the rows it claims
to describe, and drift in a limit means either charging someone who owes
nothing or letting a mistake compound silently. Reading the rows cannot drift,
because the rows *are* the answer.

The visible consequence: deleting a document gives the slot back. That is the
right behaviour for a storage limit — a person trying a second file instead of
a first one is exactly what a free tier is for — and it is what the message
says, so nobody has to guess.

Seeded lessons do not count. They arrive from `app/seed/`, nobody asked for
them, and starting a new account at 6 of 10 used would be indefensible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.core.config import settings
from app.models import Document, TutorLesson, User
from app.services.tutor_model import TUTOR_FILE_TYPE

# `taught_by_provider` on a fixture lesson. Seeded material is a gift, not usage.
SEED_PROVIDER = "seed"


@dataclass(frozen=True)
class Allowance:
    """What one person has used and what is left."""

    uploads_used: int
    uploads_limit: int
    lessons_used: int
    lessons_limit: int
    enforced: bool

    @property
    def uploads_left(self) -> int:
        return max(0, self.uploads_limit - self.uploads_used)

    @property
    def lessons_left(self) -> int:
        return max(0, self.lessons_limit - self.lessons_used)

    @property
    def can_upload(self) -> bool:
        return not self.enforced or self.uploads_left > 0

    @property
    def can_learn(self) -> bool:
        return not self.enforced or self.lessons_left > 0


async def usage_for(session: AsyncSession, user: User) -> Allowance:
    """Read this person's usage straight out of their rows."""
    uploads = await session.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.owner_id == user.id)  # pyright: ignore[reportArgumentType]
        .where(Document.file_type != TUTOR_FILE_TYPE)  # pyright: ignore[reportArgumentType]
    )
    lessons = await session.execute(
        select(func.count())
        .select_from(TutorLesson)
        .where(TutorLesson.owner_id == user.id)  # pyright: ignore[reportArgumentType]
        .where(  # pyright: ignore[reportArgumentType]
            func.coalesce(TutorLesson.taught_by_provider, "") != SEED_PROVIDER
        )
    )

    # Superusers are never limited. The account that administers the instance
    # cannot be locked out of it by its own free tier — and on this deployment
    # that account is Jelena's.
    enforced = settings.QUOTA_ENABLED and not user.is_superuser

    return Allowance(
        uploads_used=uploads.scalar_one() or 0,
        uploads_limit=settings.FREE_UPLOADS,
        lessons_used=lessons.scalar_one() or 0,
        lessons_limit=settings.FREE_LESSONS,
        enforced=enforced,
    )


def _explain(what: str, used: int, limit: int, *, recoverable: str | None) -> str:
    """The whole message, written to be read by a person who is stuck.

    Four things, in this order, because that is the order the questions arrive
    in: what happened, why, what they can still do, and who to ask.
    """
    lines = [
        f"You have used all {limit} {what} on the free plan ({used} of {limit}).",
        "",
        "Why there is a limit: every upload and every lesson is embedded on "
        "the server, and that costs real money to run. The limit is on those "
        "two things only.",
        "",
        "Everything else still works, and always will — searching, recall, "
        "the tutor's answers on what you have already learned, the tool trace, "
        "and downloading your model as JSON or as an Ollama Modelfile. "
        "Nothing you have made is locked away, and you can take all of it with "
        "you at any time.",
    ]
    if recoverable:
        lines += ["", recoverable]

    # Plain text, not markdown. This string is read as-is in a curl response
    # and in an alert box, so asterisks around "not built yet" would arrive as
    # asterisks — emphasis that draws the eye to the wrong thing and looks like
    # a bug in the app rather than a bug in the sentence.
    lines += [
        "",
        "A paid plan with a higher limit is planned, but it is not built yet — "
        "so there is nothing to buy today, and nothing will ever be charged to "
        "you without you choosing it.",
    ]
    if settings.SUPPORT_EMAIL.strip():
        lines += [
            "",
            f"If you need more room now, or you would like to be told when a "
            f"plan exists, write to {settings.SUPPORT_EMAIL.strip()} — a real "
            f"person reads it.",
        ]
    return "\n".join(lines)


async def require_upload_allowance(session: AsyncSession, user: User) -> Allowance:
    """Raise 402 if this person has no upload left."""
    allowance = await usage_for(session, user)
    if not allowance.can_upload:
        raise HTTPException(
            status_code=402,
            detail=_explain(
                "document uploads",
                allowance.uploads_used,
                allowance.uploads_limit,
                recoverable=(
                    "The limit counts the documents you are storing right now, "
                    "so deleting one you no longer need frees a slot "
                    "immediately."
                ),
            ),
        )
    return allowance


async def require_lesson_allowance(session: AsyncSession, user: User) -> Allowance:
    """Raise 402 if this person has no lesson left.

    Checked before the tutor *generates* as well as before it records, so
    nobody watches an answer stream in and then discovers it cannot be kept.
    """
    allowance = await usage_for(session, user)
    if not allowance.can_learn:
        raise HTTPException(
            status_code=402,
            detail=_explain(
                "lessons",
                allowance.lessons_used,
                allowance.lessons_limit,
                recoverable=None,  # lessons are cumulative; nothing frees one
            ),
        )
    return allowance


async def usage_for_owner(session: AsyncSession, owner_id: uuid.UUID) -> Allowance:
    """`usage_for`, when only the id is to hand."""
    result = await session.execute(select(User).where(User.id == owner_id))
    user = result.scalars().one()
    return await usage_for(session, user)
