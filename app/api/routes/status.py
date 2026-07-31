"""What the app can do, checked rather than claimed.

`GET /health` answers "is this process alive". This answers "and which parts of
it actually work" — by probing, not by reading a list someone maintained by
hand. Reasoning in `app/services/capabilities.py`.

Authenticated, like every route but `/health`. Two of the probes are
owner-scoped (the tutor corpus, and whether *you* have a key on file), so there
is a caller either way; and the report names which providers are reachable,
which is system information rather than something to hand to anonymous
visitors. If the public Space later wants this on its landing page, that is a
deliberate change with a redacted variant, not a decorator someone deletes.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.models import CapabilityReport
from app.services import capabilities

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/", response_model=CapabilityReport)
async def read_status(
    session: SessionDep, current_user: CurrentUser
) -> CapabilityReport:
    """Probe every capability and report. Never fails because a service is down.

    Each probe has its own timeout and its own exception handling, so an Ollama
    that stopped answering shows as one amber row rather than a 503 for the
    whole page — which is the entire point of a status page.
    """
    return await capabilities.report(session=session, owner_id=current_user.id)
