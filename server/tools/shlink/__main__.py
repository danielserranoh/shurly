"""
`python -m server.tools.shlink export | review | import`: Phase 8.4, moving Shlink's links
to Shurly. See README.md, including where a snapshot may be kept: it can hold personal data.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func

from server.core.models import User
from server.tools.shlink import importer
from server.tools.shlink.export import export_snapshot, shlink_client, summary, write_snapshot
from server.tools.shlink.review import check_destinations, review_rows, write_review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.tools.shlink")
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser(
        "export", help="Shlink's REST API → a raw JSON snapshot (SHLINK_URL, SHLINK_API_KEY)"
    )
    export.add_argument(
        "--visits", action="store_true", help="every link's visits too: personal data"
    )
    export.add_argument("--out-dir", type=Path, default=Path("_exchange"))

    review = commands.add_parser("review", help="a snapshot → a CSV to decide keep/archive/drop")
    review.add_argument("snapshot", type=Path)
    review.add_argument("--out", type=Path, help="default: next to the snapshot")
    review.add_argument(
        "--check-destinations",
        action="store_true",
        help="fetch each destination's HTTP status (public http(s) addresses only)",
    )
    review.add_argument("--concurrency", type=int, default=8)
    review.add_argument("--timeout", type=float, default=5.0, help="seconds per request")

    importing = commands.add_parser(
        "import", help="a snapshot and its reviewed sheet → Shurly's database (the DB_* settings)"
    )
    importing.add_argument("snapshot", type=Path)
    importing.add_argument("review", type=Path)
    importing.add_argument(
        "--as",
        dest="owner",
        required=True,
        help="email of an organization owner: the links' creator",
    )
    importing.add_argument(
        "--visits", action="store_true", help="Shlink's visits too (decision A): personal data"
    )
    importing.add_argument("--dry-run", action="store_true", help="run it all, then roll back")

    args = parser.parse_args(argv)
    commands_by_name = {"export": _export, "review": _review, "import": _import}
    return commands_by_name[args.command](args)


def _export(args: argparse.Namespace) -> int:
    url, api_key = os.environ.get("SHLINK_URL"), os.environ.get("SHLINK_API_KEY")
    missing = [
        name for name, value in (("SHLINK_URL", url), ("SHLINK_API_KEY", api_key)) if not value
    ]
    if missing:
        print(f"Set {' and '.join(missing)} in the environment.", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    try:
        with shlink_client(url, api_key) as client:
            snapshot = export_snapshot(
                client,
                visits=args.visits,
                now=now,
                progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        hint = " Check SHLINK_API_KEY." if status in (401, 403) else ""
        print(f"Shlink answered {status} to {error.request.url.path}.{hint}", file=sys.stderr)
        return 1
    except httpx.HTTPError as error:
        print(f"Couldn't reach Shlink at SHLINK_URL: {type(error).__name__}.", file=sys.stderr)
        return 1
    path = write_snapshot(snapshot, args.out_dir, now=now)
    print(f"{path}: it stays out of the repository (README.md).")
    print("\n".join(summary(snapshot)))
    return 0


def _review(args: argparse.Namespace) -> int:
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    statuses = {}
    if args.check_destinations:
        destinations = [entry["short_url"]["longUrl"] for entry in snapshot["links"]]
        statuses = asyncio.run(
            check_destinations(destinations, concurrency=args.concurrency, timeout=args.timeout)
        )
    rows = review_rows(snapshot, statuses=statuses)
    out = args.out or args.snapshot.with_name(
        args.snapshot.name.removesuffix(".json").removesuffix(".snapshot") + ".review.csv"
    )
    try:
        write_review(rows, out)
    except FileExistsError:
        print(
            f"{out} exists and may hold decisions: pass --out to write elsewhere.", file=sys.stderr
        )
        return 1
    print(f"{out}: {len(rows)} links to review.")
    return 0


def _import(args: argparse.Namespace) -> int:
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    try:
        decisions = importer.read_decisions(args.review)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    with importer.session_factory() as db:
        email = args.owner.strip().lower()
        owner = db.query(User).filter(func.lower(User.email) == email).first()
        if owner is None:
            print(f"No account {args.owner}.", file=sys.stderr)
            return 2
        try:
            report = importer.import_snapshot(db, snapshot, decisions, owner, visits=args.visits)
        except importer.ImportRefused as refused:
            db.rollback()
            print(refused, file=sys.stderr)
            return 2
        print(importer.format_report(report, snapshot, visits=args.visits))
        if report.blocked:
            db.rollback()
            print(
                "Nothing was written: drop those links in the review, or fix them, and run it again."
            )
            return 1
        if args.dry_run:
            db.rollback()
            print("Dry run: nothing was written.")
            return 0
        db.commit()
        print("Imported.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
