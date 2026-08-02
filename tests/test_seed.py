"""Seeding a fresh deployment.

The property that matters most here is the one that is hardest to notice when
it breaks: **seed only when the corpus is empty**. Topping up on every restart
would duplicate a learner's material silently and repeatedly, and there is no
undo for that — so it is asserted from both sides.
"""

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.core.config import settings
from app.models import TutorLesson
from app.services import seed, tutor_model
from tests.conftest import make_user


async def _lesson_count(session: AsyncSession, owner_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(TutorLesson).where(
            TutorLesson.owner_id == owner_id  # pyright: ignore[reportArgumentType]
        )
    )
    return result.scalar_one() or 0


def test_the_shipped_fixtures_are_valid_model_files() -> None:
    """A broken fixture must fail here, not on a deployed machine at 3am."""
    fixtures = seed.load_fixtures()
    assert fixtures, "no fixtures found — the demo would deploy empty"

    for name, fixture in fixtures:
        assert tutor_model.is_supported(fixture.format, fixture.version), name
        assert fixture.lessons, f"{name} has no lessons"
        for lesson in fixture.lessons:
            assert lesson.term.strip(), name
            assert lesson.question.strip(), name
            assert lesson.answer.strip(), name


def test_fixtures_are_exactly_the_export_format() -> None:
    """Seeding is import, not a second path — so the file a user downloads and
    the file we ship must be the same kind of object."""
    from app.models import TUTOR_MODEL_FORMAT, TUTOR_MODEL_VERSION

    for path in sorted(seed.SEED_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["format"] == TUTOR_MODEL_FORMAT, path.name
        assert payload["version"] == TUTOR_MODEL_VERSION, path.name


async def test_seeds_an_empty_corpus_then_never_again(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole contract, in one test: once, and only once."""
    user = await make_user(session, "seed-target@example.com")
    monkeypatch.setattr(settings, "DEMO_USER", user.email)
    monkeypatch.setattr(settings, "SEED_ON_STARTUP", True)

    added = await seed.seed_if_empty(session)
    assert added > 0
    first = await _lesson_count(session, user.id)
    assert first == added

    # Every subsequent startup.
    for _ in range(3):
        assert await seed.seed_if_empty(session) == 0
    assert await _lesson_count(session, user.id) == first


async def test_a_learners_own_corpus_is_never_topped_up(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone who has taken one lesson must not receive six samples on the
    next restart. 'Empty' means empty, not 'small'."""
    user = await make_user(session, "seed-hasown@example.com")
    monkeypatch.setattr(settings, "DEMO_USER", user.email)
    monkeypatch.setattr(settings, "SEED_ON_STARTUP", True)

    await tutor_model.record_lesson(
        session=session,
        owner_id=user.id,
        term="Their own",
        question="Something they asked",
        answer="Something they were told",
    )

    assert await seed.seed_if_empty(session) == 0
    assert await _lesson_count(session, user.id) == 1


async def test_the_setting_turns_it_off(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user(session, "seed-off@example.com")
    monkeypatch.setattr(settings, "DEMO_USER", user.email)
    monkeypatch.setattr(settings, "SEED_ON_STARTUP", False)

    assert await seed.seed_if_empty(session) == 0
    assert await _lesson_count(session, user.id) == 0


async def test_seeded_lessons_are_searchable(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seeding that produced rows but no vectors would look fine and answer
    nothing — which is the failure this exists to prevent."""
    from app.services import vectors

    user = await make_user(session, "seed-search@example.com")
    monkeypatch.setattr(settings, "DEMO_USER", user.email)
    monkeypatch.setattr(settings, "SEED_ON_STARTUP", True)
    await seed.seed_if_empty(session)

    hits = await vectors.search(session, user.id, [0.1, 0.2, 0.3, 0.4], top_k=3)
    assert hits, "seeded lessons were recorded but never indexed"


async def test_seeding_belongs_to_one_owner(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Samples land in one account, not in everybody's."""
    target = await make_user(session, "seed-owner@example.com")
    bystander = await make_user(session, "seed-bystander@example.com")
    monkeypatch.setattr(settings, "DEMO_USER", target.email)
    monkeypatch.setattr(settings, "SEED_ON_STARTUP", True)

    await seed.seed_if_empty(session)

    assert await _lesson_count(session, target.id) > 0
    assert await _lesson_count(session, bystander.id) == 0
