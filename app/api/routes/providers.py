"""Provider and model discovery — feeds the frontend picker."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.models import ProvidersPublic
from app.services.providers import describe_providers

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/", response_model=ProvidersPublic)
async def list_providers(_current_user: CurrentUser) -> ProvidersPublic:
    """Which providers are usable right now, and with which models.

    Ollama's list is queried live, so pulling a new model makes it appear
    without restarting the API. A provider that is configured but unreachable is
    reported as `available: false` with a `detail` explaining why, rather than
    failing the whole request.
    """
    return await describe_providers()
