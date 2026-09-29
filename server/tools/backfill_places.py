"""
Phase 8.4 — a visit's country and city, filled in where they're empty: the visits saved before
cities (migration 0011), or while an image had no geolocation database. Each is looked up as
the redirect does, from the stored address (anonymized, when that's on), so the lookup knows no
more than what's kept. A visit imported from Shlink has no address ("unknown"), and is skipped.

It only fills what's NULL, and never overwrites. A city goes only where the visit's country is
empty or agrees with it, so no pair is half one database's and half another's. A second run
finds only what the database couldn't place. It works in batches by id, a commit each, so it
can run while the app serves; what it prints are counts, never an address.

    python -m server.tools.backfill_places [--dry-run] [--batch-size N]

In production, as a one-off ECS task: scripts/run_backfill_places.sh (DEPLOYMENT.md).
"""

import argparse
import sys
from collections import Counter, defaultdict

from sqlalchemy import func, or_

from server.core import SessionLocal
from server.core.models import Visitor
from server.utils import geo
from server.utils.columns import fit
from server.utils.network import UNKNOWN_IP

# Tests point this at their database.
session_factory = SessionLocal


def backfill(db, batch_size: int = 1000, dry_run: bool = False) -> Counter:
    """Fill the empty countries and cities; what was done, counted. A dry run rolls back."""
    counts: Counter = Counter()
    places: dict[str, geo.Place] = {}  # an address's place, looked up once
    last = None
    while True:
        batch = db.query(Visitor.id, Visitor.ip, Visitor.country, Visitor.city).filter(
            or_(Visitor.country.is_(None), Visitor.city.is_(None)), Visitor.ip != UNKNOWN_IP
        )
        if last is not None:
            batch = batch.filter(Visitor.id > last)
        rows = batch.order_by(Visitor.id).limit(batch_size).all()
        if not rows:
            break
        countries: dict[str, list] = defaultdict(list)
        cities: dict[str, list] = defaultdict(list)
        for id_, ip, country, city in rows:
            counts["scanned"] += 1
            place = places.get(ip)
            if place is None:
                place = places[ip] = geo.place_of(ip)
            if place == geo.NOWHERE:
                counts["unplaced"] += 1
            if country is None and place.country:
                countries[place.country].append(id_)
            if city is None and place.city and country in (None, place.country):
                cities[fit(place.city, Visitor.city)].append(id_)
        # One UPDATE per value, and each still only where it's empty.
        for value, ids in countries.items():
            counts["countries"] += _fill(db, Visitor.country, value, ids)
        for value, ids in cities.items():
            counts["cities"] += _fill(db, Visitor.city, value, ids)
        if dry_run:
            db.rollback()
        else:
            db.commit()
        last = rows[-1].id
    counts["from_shlink"] = (
        db.query(func.count(Visitor.id))
        .filter(or_(Visitor.country.is_(None), Visitor.city.is_(None)), Visitor.ip == UNKNOWN_IP)
        .scalar()
    )
    return counts


def _fill(db, column, value: str, ids: list) -> int:
    return (
        db.query(Visitor)
        .filter(Visitor.id.in_(ids), column.is_(None))
        .update({column: value}, synchronize_session=False)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.tools.backfill_places")
    parser.add_argument("--dry-run", action="store_true", help="look everything up, write nothing")
    parser.add_argument("--batch-size", type=int, default=1000, metavar="N")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")

    reader = geo.open_database()
    if reader is None:
        print(
            "No geolocation database (GEOIP_DATABASE, GEOIP_FALLBACK_DATABASE): nothing to fill "
            "from. Nothing was written.",
            file=sys.stderr,
        )
        return 1
    database = reader.metadata().database_type
    with session_factory() as db:
        counts = backfill(db, args.batch_size, args.dry_run)
    print(
        f"{counts['scanned']} visits without a country or a city, looked up in {database}: "
        f"filled {counts['countries']} countries and {counts['cities']} cities; "
        f"{counts['unplaced']} it doesn't place. Left as they are: "
        f"{counts['from_shlink']} imported from Shlink, which have no address."
    )
    if args.dry_run:
        print("Dry run: nothing was written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
