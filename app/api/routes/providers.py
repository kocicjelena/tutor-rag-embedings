"""Provider and model discovery — feeds the frontend picker."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.models import ProvidersPublic
from app.services import user_keys
from app.services.providers import describe_providers

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/", response_model=ProvidersPublic)
async def list_providers(
    session: SessionDep, current_user: CurrentUser
) -> ProvidersPublic:
    """Which providers are usable right now, and with which models.

    Ollama's list is queried live, so pulling a new model makes it appear
    without restarting the API. A provider that is configured but unreachable is
    reported as `available: false` with a `detail` explaining why, rather than
    failing the whole request.

    **Availability is per user.** Claude counts as available to anyone who has
    supplied their own Anthropic key, even when this app holds none — which is
    exactly the case on a public deploy. Reporting a single global answer would
    tell a visitor with a perfectly good key that the feature is off.
    """
    record = await user_keys.get_record(session=session, owner_id=current_user.id)
    return await describe_providers(caller_has_key=record is not None)
