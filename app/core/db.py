"""Async SQLite engine, sqlite-vec loading, and schema bootstrap.

The inherited version defined `init_db()` but never called it, so a fresh
database had no tables and no bootstrap superuser — there was no way to obtain
a first login. It is now invoked from the FastAPI lifespan (`app/main.py`).
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any

import sqlite_vec
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from app.core.config import settings

logger = logging.getLogger(__name__)


def _make_engine() -> AsyncEngine:
    engine = create_async_engine(
        settings.async_database_uri,
        echo=False,
        # aiosqlite serialises access through one worker thread per connection;
        # a modest pool keeps concurrent requests from queueing behind each other.
        pool_pre_ping=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(  # pyright: ignore[reportUnusedFunction]  (registered by decorator)
        dbapi_conn: Any, _record: Any
    ) -> None:
        """Load sqlite-vec and set pragmas on every new connection.

        Why this is more convoluted than the usual recipe: aiosqlite creates the
        real `sqlite3.Connection` inside a private worker thread, and sqlite3
        objects are thread-bound. Calling `enable_load_extension` directly on
        the SQLAlchemy adapter raises AttributeError, and calling it on the raw
        connection from this thread raises ProgrammingError. So we schedule the
        work back onto aiosqlite's own thread via its `_execute` helper.

        This touches two private APIs (`aiosqlite.Connection._conn` and
        `._execute`). `tests/test_db.py::test_sqlite_vec_loaded` asserts
        `vec_version()` resolves, so a library upgrade that breaks this fails
        loudly instead of silently disabling vector search.
        """
        driver_conn = dbapi_conn.driver_connection
        raw = driver_conn._conn  # pyright: ignore[reportPrivateUsage]

        def _configure() -> None:
            raw.enable_load_extension(True)
            sqlite_vec.load(raw)
            raw.enable_load_extension(False)
            cur = raw.cursor()
            try:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA busy_timeout=5000")
            finally:
                cur.close()

        dbapi_conn.await_(
            driver_conn._execute(_configure)  # pyright: ignore[reportPrivateUsage]
        )

    return engine


engine: AsyncEngine = _make_engine()

SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create tables, the vector table, and the bootstrap accounts.

    Runs from the FastAPI lifespan on **every** startup, and is idempotent —
    each step is "create if missing", so restarting never duplicates anything.

    What that means in practice, because it surprises people:

      * A table added to `app.models` appears on the next start. A *column*
        added to an existing table does **not** — `create_all` never alters
        existing tables, and there are no migrations here. That is why
        `TutorLesson` is its own table.
      * Accounts are matched **by email**. Changing `FIRST_SUPERUSER` in `.env`
        does not rename anyone: the old account stays exactly as it was, and a
        second one is created alongside it on the next start. Renaming is a
        deliberate act, not a config edit.
    """
    # Imported here so `app.models` is registered on SQLModel.metadata before
    # create_all, and to avoid a circular import with app.crud.
    from app.services.vectors import (
        BASE_DIMENSIONS,
        create_learning_table,
        create_vector_table,
    )

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # The 768 index always exists — it holds everything indexed so far, and
        # `reembed` needs to be able to read it even while another provider is
        # active. The second call creates the configured width, and is the same
        # statement when that width is 768.
        await create_vector_table(conn, BASE_DIMENSIONS)
        await create_vector_table(conn)
        # The learning index, at the active width only. Unlike `vec_chunks`
        # there is nothing historical at 768 to keep readable — this index is
        # newer than the per-width scheme, so it has never held a vector the
        # active model cannot compare against.
        await create_learning_table(conn)

    async with SessionLocal() as session:
        await _ensure_user(
            session,
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        # The demo account is an ordinary user on purpose: it should exercise
        # what a visitor can actually do — upload, ask, learn, export a model —
        # not the user-administration routes, which are not the demo.
        if settings.demo_user_enabled:
            await _ensure_user(
                session,
                email=settings.DEMO_USER,
                password=settings.DEMO_USER_PASSWORD,
                is_superuser=False,
            )


async def _ensure_user(
    session: AsyncSession, *, email: str, password: str, is_superuser: bool
) -> None:
    """Create the account if no user has this email. Never modifies an existing one.

    Leaving an existing account alone matters: it owns documents, lessons and
    vectors by id, so silently rewriting it from config would be a much bigger
    action than it looks.
    """
    from app import crud
    from app.models import UserCreate

    if await crud.get_user_by_email(session=session, email=email) is not None:
        return

    await crud.create_user(
        session=session,
        user_create=UserCreate(
            email=email, password=password, is_superuser=is_superuser
        ),
    )
    logger.info(
        "Created bootstrap %s %s",
        "superuser" if is_superuser else "demo user",
        email,
    )


async def check_health() -> dict[str, str]:
    """Confirm the DB answers and the vector extension is actually loaded."""
    async with engine.connect() as conn:
        vec_version = (await conn.execute(text("select vec_version()"))).scalar_one()
    return {"database": "ok", "sqlite_vec": str(vec_version)}
