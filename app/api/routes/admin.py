"""Who has been using this app.

Superuser only, and not because the numbers are secret — because they are
everyone's. A per-account breakdown naming emails is exactly the kind of thing
that should never be one forgotten dependency away from being public.
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import ActivityReport
from app.services import activity

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_active_superuser)],
)


@router.get("/activity", response_model=ActivityReport)
async def read_activity(
    session: SessionDep,
    days: int = Query(default=7, ge=1, le=365),
) -> ActivityReport:
    """Signups, sign-ins, uploads and lessons — totals and per account.

    The answer to "is anyone using this, and is it costing me anything". Read
    entirely from rows that already exist, so it cannot drift from the truth
    and there is no counter to maintain.
    """
    return await activity.build_report(session, days=days)
