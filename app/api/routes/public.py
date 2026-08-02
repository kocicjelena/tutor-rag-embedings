"""What the sign-in page needs to know before anyone has signed in.

The only unauthenticated **read** in the API, and it is deliberately tiny: the
sign-in page cannot ask an authenticated endpoint whether registration is open,
because nobody is authenticated yet.

It can publish a working password, which is why every field is opt-in and the
defaults publish nothing at all.
"""

from fastapi import APIRouter

from app.core.config import settings
from app.models import SignInInfo

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/signin-info", response_model=SignInInfo)
async def signin_info() -> SignInInfo:
    """Registration state, the demo account, and who to write to.

    **The demo password is returned only when `PUBLISH_DEMO_CREDENTIALS` is
    explicitly true.** Two separate settings have to line up before a password
    leaves this route — the account must exist *and* publishing must be
    switched on — because a default that leaked one would be the worst kind of
    bug: silent, public, and correct-looking.
    """
    publish = settings.PUBLISH_DEMO_CREDENTIALS and settings.demo_user_enabled

    return SignInInfo(
        registration_open=settings.OPEN_REGISTRATION,
        quota_enabled=settings.QUOTA_ENABLED,
        free_uploads=settings.FREE_UPLOADS,
        free_lessons=settings.FREE_LESSONS,
        demo_email=settings.DEMO_USER if publish else None,
        demo_password=settings.DEMO_USER_PASSWORD if publish else None,
        support_email=settings.SUPPORT_EMAIL.strip() or None,
    )
