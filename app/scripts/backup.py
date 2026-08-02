"""Back up the database, safely, while the app is running.

    uv run python -m app.scripts.backup
    uv run python -m app.scripts.backup --out ~/backups
    uv run python -m app.scripts.backup --restore ~/backups/rag-2026-08-02.db

**Why not `cp`.** SQLite in WAL mode is two files that must agree: `rag.db` and
`rag.db-wal`. Copying them with `cp` while anything is writing gives you a
database and a write-ahead log from two different instants, and the result is
either subtly wrong or refuses to open. `.backup` uses SQLite's own online
backup API, which takes a consistent snapshot of a live database — that is what
it exists for.

**The vectors come too.** `vec_chunks` and `vec_learning` are tables inside the
same file, so one backup file is the whole application state: users, documents,
chunks, lessons, learning events and every vector. There is no second store to
keep in step, which is the quiet advantage of having chosen SQLite.

**Restore is here too, and that is the point.** A backup nobody has restored is
a belief, not a backup. `--restore` verifies the file opens, counts what is in
it, refuses to overwrite a database that is being written to, and keeps the
previous file rather than deleting it.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

# Tables worth counting in a report. Not a schema check — just enough to tell a
# real backup from an empty file at a glance.
COUNTED = ("user", "document", "documentchunk", "tutorlesson", "learningevent")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        # Counting ordinary tables does not need the extension. Only a query
        # against a vec0 table would, and none of these are.
        pass
    return conn


def _describe(path: Path) -> list[str]:
    lines: list[str] = []
    conn = _connect(path)
    try:
        names = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        for table in COUNTED:
            if table in names:
                count = conn.execute(f"select count(*) from {table}").fetchone()[0]
                lines.append(f"    {table:<16} {count}")
        vec_tables = sorted(
            row[0]
            for row in conn.execute(
                "select name from sqlite_master "
                "where type='table' and sql like '%USING vec0%'"
            )
        )
        if vec_tables:
            lines.append(f"    vector indexes   {', '.join(vec_tables)}")
    finally:
        conn.close()
    return lines


def backup(out_dir: Path) -> Path:
    source = settings.sqlite_file
    if not source.exists():
        sys.exit(f"No database at {source}. Nothing to back up.")

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    target = out_dir / f"rag-{stamp}.db"

    src = _connect(source)
    try:
        # Fold the WAL back into the main file first. Without this the backup is
        # still correct, but a checkpointed source makes the copy smaller and
        # the two files easier to reason about afterwards.
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        dst = sqlite3.connect(str(target))
        try:
            with dst:
                src.backup(dst)   # SQLite's online backup API
        finally:
            dst.close()
    finally:
        src.close()

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"  backed up {source}")
    print(f"         -> {target}  ({size_mb:.1f} MB)")
    for line in _describe(target):
        print(line)
    return target


def restore(backup_file: Path) -> None:
    if not backup_file.exists():
        sys.exit(f"No such backup: {backup_file}")

    print(f"  checking {backup_file}")
    try:
        conn = _connect(backup_file)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        sys.exit(f"  that file is not a readable SQLite database: {exc}")
    if ok != "ok":
        sys.exit(f"  integrity check failed: {ok}")
    print("  integrity ok")
    for line in _describe(backup_file):
        print(line)

    target = settings.sqlite_file
    # A live app holds the WAL open. Restoring underneath a running process is
    # how you get a corrupted database and a confusing afternoon, so refuse
    # rather than race it.
    wal = target.with_name(target.name + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        sys.exit(
            f"  {wal.name} is non-empty, so something is probably using "
            f"{target.name}.\n"
            "  Stop the app first (docker compose stop, or Ctrl-C the dev "
            "server), then run this again."
        )

    if target.exists():
        # Never delete the thing being replaced. If the restore was a mistake,
        # this file is the way back.
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        aside = target.with_name(f"{target.stem}-replaced-{stamp}{target.suffix}")
        shutil.move(str(target), str(aside))
        print(f"  previous database kept at {aside}")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(backup_file), str(target))
    for suffix in ("-wal", "-shm"):
        stale = target.with_name(target.name + suffix)
        stale.unlink(missing_ok=True)
    print(f"  restored to {target}")
    print("  start the app and sign in to confirm.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("backups"),
        help="directory to write the backup into (default: ./backups)",
    )
    parser.add_argument(
        "--restore",
        type=Path,
        metavar="FILE",
        help="restore this backup over the live database",
    )
    args = parser.parse_args()

    if args.restore:
        restore(args.restore)
    else:
        backup(args.out)


if __name__ == "__main__":
    main()
