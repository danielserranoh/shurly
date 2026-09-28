"""
`python -m server.tools.shlink export | review`: Phase 8.4, moving Shlink's links to
Shurly. See README.md, including where a snapshot may be kept: it can hold personal data.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from server.tools.shlink.export import export_snapshot, shlink_client, write_snapshot
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

    args = parser.parse_args(argv)
    return _export(args) if args.command == "export" else _review(args)


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
            snapshot = export_snapshot(client, visits=args.visits, now=now)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        hint = " Check SHLINK_API_KEY." if status in (401, 403) else ""
        print(f"Shlink answered {status} to {error.request.url.path}.{hint}", file=sys.stderr)
        return 1
    except httpx.HTTPError as error:
        print(f"Couldn't reach Shlink at SHLINK_URL: {type(error).__name__}.", file=sys.stderr)
        return 1
    path = write_snapshot(snapshot, args.out_dir, now=now)
    what = "links and their visits" if args.visits else "links"
    print(f"{path}: {len(snapshot['links'])} {what}. It stays out of the repository (README.md).")
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


if __name__ == "__main__":
    sys.exit(main())
