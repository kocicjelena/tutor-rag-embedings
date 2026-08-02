"""FastAPI application entrypoint."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.main import api_router
from app.core.config import settings
from app.core.db import check_health, init_db
from app.services.providers import ProviderUnavailableError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Create the schema and bootstrap superuser on startup, then seed.

    The inherited code defined init_db() but never called it, so a fresh
    database had no tables and no way to log in.
    """
    await init_db()
    logger.info("Database ready at %s", settings.sqlite_file)

    # Sample content, only when this deployment has none. Wrapped because
    # seeding needs the embedding provider and startup is exactly when it is
    # least likely to be ready — an app that refuses to boot over missing
    # sample content would be worse than one that boots without it. A failure
    # here shows up honestly as an empty corpus on GET /status/.
    try:
        from app.core.db import SessionLocal
        from app.services.seed import seed_if_empty

        async with SessionLocal() as session:
            await seed_if_empty(session)
    except Exception:
        logger.exception("Seeding failed — starting with an empty corpus")

    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.all_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ProviderUnavailableError)
async def provider_unavailable_handler(
    _request: Request, exc: ProviderUnavailableError
) -> JSONResponse:
    """A provider outage is a 503 with a fixable message, not a stack trace."""
    logger.warning("provider %s unavailable: %s", exc.provider, exc.detail)
    return JSONResponse(
        status_code=503,
        content={"detail": exc.detail, "provider": exc.provider},
    )


@app.get("/health", tags=["meta"])
async def health() -> dict[str, Any]:
    """Liveness + confirmation that sqlite-vec actually loaded."""
    return {"status": "ok", **await check_health()}


app.include_router(api_router, prefix=settings.API_V1_STR)
