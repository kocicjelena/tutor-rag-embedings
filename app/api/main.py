from fastapi import APIRouter

from app.api.routes import (
    documents,
    keys,
    login,
    mcp,
    providers,
    query,
    status,
    tutor,
    users,
)

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(keys.router)
api_router.include_router(documents.router)
api_router.include_router(query.router)
api_router.include_router(providers.router)
api_router.include_router(tutor.router)
api_router.include_router(mcp.router)
api_router.include_router(status.router)
