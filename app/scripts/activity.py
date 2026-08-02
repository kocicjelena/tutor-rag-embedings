"""Has anyone been using this app, and did it cost anything.

    uv run python -m app.scripts.activity
    uv run python -m app.scripts.activity --days 30

On fly:

    fly ssh console -a tutor-rag-embeddings -C "python -m app.scripts.activity"

Reads the database directly, so it works when the web app is asleep, when
nobody can sign in, and when the only thing you have is a shell. The same
numbers are available over HTTP at `GET /api/v1/admin/activity` as a superuser
— this is the version that needs neither a browser nor a token.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from app.core.db import SessionLocal
from app.models import ActivityReport
from app.services import activity


def _ago(when: datetime | None) -> str:
    if when is None:
        return "never"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - when).total_seconds()
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def render(report: ActivityReport) -> str:
    lines = [
        "",
        f"  Activity — last {report.window_days} days"
        f"   (as of {report.generated_at:%Y-%m-%d %H:%M} UTC)",
        "  " + "─" * 62,
        f"    accounts          {report.total_users}"
        f"   ({report.new_users} first seen in this window)",
        f"    sign-ins          {report.sign_ins}",
        f"    uploads           {report.uploads}"
        f"   (of {report.total_uploads} ever)",
        f"    lessons           {report.lessons}"
        f"   (of {report.total_lessons} ever)",
        f"    learning pieces   {report.learning_events}",
        "",
    ]

    if not report.users:
        lines += ["    no accounts yet", ""]
        return "\n".join(lines)

    lines += [
        f"  {'account':<34}{'in':>4}{'up':>4}{'les':>5}  {'last seen':>10}",
        "  " + "─" * 62,
    ]
    for person in report.users:
        name = person.email if len(person.email) <= 32 else person.email[:31] + "…"
        mark = " *" if person.is_superuser else "  "
        lines.append(
            f"  {name:<32}{mark}{person.sign_ins:>4}{person.uploads:>4}"
            f"{person.lessons:>5}  {_ago(person.last_sign_in):>10}"
        )

    lines += ["", "  * superuser — exempt from the free tier", ""]

    # The line that matters for a bill: one account doing all the work.
    spenders = [p for p in report.users if not p.is_superuser]
    if spenders:
        top = spenders[0]
        if top.uploads + top.lessons > 0:
            lines += [
                f"  Busiest visitor: {top.email} — {top.uploads} uploads, "
                f"{top.lessons} lessons.",
                "",
            ]
    if report.total_users > 25:
        lines += [
            "  More than 25 accounts. On an app with no rate limiting that is",
            "  worth a look — see OPEN_REGISTRATION in fly.toml if it is not you.",
            "",
        ]
    return "\n".join(lines)


async def main_async(days: int) -> None:
    async with SessionLocal() as session:
        print(render(await activity.build_report(session, days=days)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="window (default 7)")
    args = parser.parse_args()
    asyncio.run(main_async(args.days))


if __name__ == "__main__":
    main()
