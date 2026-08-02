"""What this account has used, and what is left.

Exists so the limit is *visible before it bites*. A person who uploads a third
document and is refused without warning experiences a bug; the same person
watching "2 of 3 used" experiences a free tier. Same rule, entirely different
thing to be on the receiving end of.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import QuotaPublic
from app.services import quota

router = APIRouter(prefix="/quota", tags=["quota"])


@router.get("/", response_model=QuotaPublic)
async def read_quota(session: SessionDep, current_user: CurrentUser) -> QuotaPublic:
    """This caller's allowance. Owner-scoped like everything else."""
    allowance = await quota.usage_for(session, current_user)
    return QuotaPublic(
        enforced=allowance.enforced,
        uploads_used=allowance.uploads_used,
        uploads_limit=allowance.uploads_limit,
        uploads_left=allowance.uploads_left,
        lessons_used=allowance.lessons_used,
        lessons_limit=allowance.lessons_limit,
        lessons_left=allowance.lessons_left,
        can_upload=allowance.can_upload,
        can_learn=allowance.can_learn,
        support_email=settings.SUPPORT_EMAIL.strip() or None,
    )
