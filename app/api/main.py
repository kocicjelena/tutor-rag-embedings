from fastapi import APIRouter

from app.api.routes import documents, login, providers, query, tutor, users

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(documents.router)
api_router.include_router(query.router)
api_router.include_router(providers.router)
api_router.include_router(tutor.router)
