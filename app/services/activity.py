"""Who has been using this app, and what did it cost.

Jelena's ask, 2026-08-02: *"Somehow I have to know if someone was using app.
Please make addition so I have alert, or I can check."*

## What was concluded, and why it is not email

An email alert per signup needs an SMTP provider, another account, another
secret, and a delivery path that fails **silently** — the one failure mode an
alert must not have. It would also become noise the first time anything is
popular, and noise is how alerts get ignored.

Everything worth knowing is already in the database. Nothing new is recorded
here except sign-ins (below); the rest is `COUNT` and `MAX` over rows that
exist because the app works. So this is a **report**, not a monitoring system:
one route and one script, both reading what is already there.

## What answers "was someone using the app"

Four signals, and they answer different questions:

    signed up      someone arrived
    signed in      someone came back  ← the only one that needed a new row
    uploaded       someone spent your CPU
    took a lesson  someone spent your CPU, and used the thing this app is for

Only sign-ins needed storing. A person who registers and reads costs nothing
and leaves no trace otherwise, and *"did anyone actually come back"* is the
question a showcase owner most wants answered.

## Why a new table rather than a column on `user`

`create_all` adds missing tables and never missing columns, and there are no
migrations here — so `last_seen_at` on `User` would simply not exist on any
database that already exists. Same reason `TutorLesson` and `UserApiKey` are
their own tables. See `.claude/rules/DATABASE.md` §4.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.models import (
    ActivityReport,
    Document,
    LearningEvent,
    SignInEvent,
    TutorLesson,
    User,
    UserActivity,
)
from app.services.quota import SEED_PROVIDER
from app.services.tutor_model import TUTOR_FILE_TYPE


def _within(when: datetime | None, since: datetime) -> bool:
    """Is `when` inside the window, whatever it knows about timezones.

    SQLite has no datetime type: values come back **naive**, having gone in as
    UTC. Comparing one of those against an aware `datetime.now(timezone.utc)`
    raises `TypeError: can't compare offset-naive and offset-aware datetimes`
    — which is how this was found, and it would have been a 500 on a live
    admin page rather than a red test if nothing had exercised it.
    """
    if when is None:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when >= since


async def record_sign_in(session: AsyncSession, user_id: uuid.UUID) -> None:
    """One row per successful sign-in.

    Deliberately not merged into an "update last_seen" — a count of visits and
    a first/last pair are different facts, and rows give both. Never fatal:
    failing to *log* a sign-in must never fail the sign-in itself.
    """
    session.add(SignInEvent(owner_id=user_id))
    await session.commit()


async def build_report(session: AsyncSession, *, days: int = 7) -> ActivityReport:
    """Everything at once, for `GET /admin/activity` and the script.

    One pass per signal rather than a join: at showcase scale the queries are
    sub-millisecond, and separate counts are far easier to read and to trust
    than one clever statement.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async def _count(model: type, *conditions: object) -> int:
        stmt = select(func.count()).select_from(model)
        for condition in conditions:
            stmt = stmt.where(condition)  # pyright: ignore[reportArgumentType]
        result = await session.execute(stmt)
        return result.scalar_one() or 0

    users = (await session.execute(select(User))).scalars().all()

    # Per-person totals, so a single account that is consuming everything is
    # visible as such rather than hidden inside a grand total.
    people: list[UserActivity] = []
    for user in users:
        uploads = await _count(
            Document,
            Document.owner_id == user.id,
            Document.file_type != TUTOR_FILE_TYPE,
        )
        # Seeded lessons are excluded, exactly as the quota excludes them.
        # They are content the app installed, not something a person did — and
        # two numbers that disagree about the same account ("6 lessons" here,
        # "0 of 10 used" there) would make both untrustworthy.
        lessons = await _count(
            TutorLesson,
            TutorLesson.owner_id == user.id,
            func.coalesce(TutorLesson.taught_by_provider, "") != SEED_PROVIDER,
        )
        sign_ins = await _count(SignInEvent, SignInEvent.owner_id == user.id)
        bounds = await session.execute(
            select(
                func.min(SignInEvent.at), func.max(SignInEvent.at)
            ).where(SignInEvent.owner_id == user.id)
        )
        first_seen, last_seen = bounds.one()
        people.append(
            UserActivity(
                email=user.email,
                is_superuser=user.is_superuser,
                sign_ins=sign_ins,
                first_sign_in=first_seen,
                last_sign_in=last_seen,
                uploads=uploads,
                lessons=lessons,
            )
        )

    # Busiest first — the row that matters on a bill is the one at the top.
    people.sort(
        key=lambda p: (p.uploads + p.lessons, p.sign_ins), reverse=True
    )

    return ActivityReport(
        window_days=days,
        generated_at=datetime.now(timezone.utc),
        total_users=len(users),
        # `User` has no timestamp and cannot grow one, so "new this week" is
        # counted as accounts whose *first* sign-in falls in the window.
        # Registration signs you straight in, so the two coincide for anyone
        # who arrived through the form.
        new_users=sum(
            1 for p in people if _within(p.first_sign_in, since)
        ),
        sign_ins=await _count(SignInEvent, col(SignInEvent.at) >= since),
        uploads=await _count(
            Document,
            col(Document.created_at) >= since,
            Document.file_type != TUTOR_FILE_TYPE,
        ),
        lessons=await _count(
            TutorLesson,
            col(TutorLesson.created_at) >= since,
            func.coalesce(TutorLesson.taught_by_provider, "") != SEED_PROVIDER,
        ),
        learning_events=await _count(
            LearningEvent, col(LearningEvent.created_at) >= since
        ),
        total_uploads=await _count(Document, Document.file_type != TUTOR_FILE_TYPE),
        total_lessons=await _count(
            TutorLesson,
            func.coalesce(TutorLesson.taught_by_provider, "") != SEED_PROVIDER,
        ),
        users=people,
    )
