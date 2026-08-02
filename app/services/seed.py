"""Seed a fresh deployment with a corpus, so the demo is not an empty room.

Jelena's ask, 2026-08-02, ahead of the fly.io deploy. It matters more there
than it looks: on a deployed instance there is no local chat model, so a
visitor cannot *make* a lesson until they have pasted an Anthropic key. Without
seeding, a first visit shows an empty tutor, an empty recall, and two download
buttons that export nothing — a demo of the plumbing with the water off.

**It is import, not a second code path.** The fixtures are ordinary
`model.json` files in the export format, and they are applied through
`tutor_model.apply_import`, which is the same function `POST /tutor/model/import`
uses. That is deliberate and is what keeps the format honest: if the export
ever stops round-tripping, seeding breaks too, loudly, on the next boot.

Three rules hold it together.

**Only when the corpus is empty.** Never "top up". On an ephemeral disk this
restores the demo after a rebuild; on a real volume it runs exactly once and
then never touches anything again. Anything else risks duplicating a user's own
material every time the machine restarts, which is the one unrecoverable
mistake available here.

**Never fatal.** Seeding runs at startup, and startup is where the embedding
provider is least likely to be ready — Ollama may still be loading. An app that
refuses to boot because it could not install sample content is worse than one
that boots without it, so every failure is logged and swallowed. `GET /status/`
will show an empty corpus, which is the truth.

**It belongs to a real account.** Vectors are owner-scoped, so seeded material
has to be owned by somebody. It goes to the demo user when one is configured,
and to the superuser otherwise.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.core.config import settings
from app.models import TutorLesson, TutorModelImport, User
from app.services import tutor_model

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


async def _corpus_is_empty(session: AsyncSession, owner_id: object) -> bool:
    result = await session.execute(
        select(func.count()).select_from(TutorLesson).where(
            TutorLesson.owner_id == owner_id  # pyright: ignore[reportArgumentType]
        )
    )
    return (result.scalar_one() or 0) == 0


async def _seed_owner(session: AsyncSession) -> User | None:
    """Whose corpus the samples land in.

    The demo account first: it is the one a visitor is told to sign in with, so
    it is the one that should have something in it. The superuser is the
    fallback, because an instance with no demo account still deserves a
    non-empty tutor.
    """
    for email in (settings.DEMO_USER, settings.FIRST_SUPERUSER):
        if not email.strip():
            continue
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        if user is not None:
            return user
    return None


def load_fixtures() -> list[tuple[str, TutorModelImport]]:
    """Read every `*.json` in `app/seed/`, newest-sorted by filename.

    Parsed here rather than at import time so a malformed fixture is a logged
    startup warning rather than a module that cannot be imported at all — the
    difference between an app that boots without samples and an app that does
    not boot.
    """
    if not SEED_DIR.is_dir():
        return []

    fixtures: list[tuple[str, TutorModelImport]] = []
    for path in sorted(SEED_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            fixtures.append((path.name, TutorModelImport.model_validate(payload)))
        except Exception:
            logger.exception("seed: %s is not a valid model file — skipping", path.name)
    return fixtures


async def seed_if_empty(session: AsyncSession) -> int:
    """Install the sample corpus if this deployment has none. Returns lessons added.

    Safe to call on every startup; that is how it is meant to be used.
    """
    if not settings.SEED_ON_STARTUP:
        return 0

    owner = await _seed_owner(session)
    if owner is None:
        logger.info("seed: no account to own the samples — skipping")
        return 0

    if not await _corpus_is_empty(session, owner.id):
        return 0

    fixtures = load_fixtures()
    if not fixtures:
        logger.info("seed: no fixtures in %s", SEED_DIR)
        return 0

    added = 0
    for name, fixture in fixtures:
        # The same version gate the HTTP route applies. A fixture written for a
        # future format should be refused here too, or seeding becomes the one
        # door where an unrecognised file gets in.
        if not tutor_model.is_supported(fixture.format, fixture.version):
            logger.warning(
                "seed: %s is format %s v%s, which this build does not read",
                name, fixture.format, fixture.version,
            )
            continue
        try:
            result = await tutor_model.apply_import(
                session=session, owner_id=owner.id, lessons=fixture.lessons
            )
            added += result.imported
            logger.info(
                "seed: %s → %d lessons, %d chunks", name, result.imported,
                result.indexed_chunks,
            )
        except Exception:
            # Embedding is the likely failure, and at startup the model server
            # may simply not be up yet. Losing the samples is a much smaller
            # problem than an app that will not start.
            logger.exception("seed: %s failed — continuing without it", name)

    if added:
        logger.info("seed: %d sample lessons installed for %s", added, owner.email)
    return added
