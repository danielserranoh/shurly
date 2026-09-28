"""
Analytics days in the viewer's time zone (after Phase 3.12's profile).

A day is a calendar day where the viewer is: the zone a request names (`?tz=`), else their
profile's, else UTC. It runs from one local midnight to the next: those instants are built
aware in the zone, converted to UTC and made naive, since `visits.visited_at` holds naive
UTC. So a day can last 23 or 25 hours (DST), or start at 18:30 UTC (Asia/Kolkata).

A series is counted in one query: the visits are bounded by the whole range first, so an
index on `visited_at` can narrow the scan, then summed per day. It needs no time zone
support from the database, and nothing depends on what SQL's `date()` returns (a string on
SQLite, a date on PostgreSQL, which hid wrong counts from the tests).

The zone only groups the visits into days: which visits count stays the caller's query.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Query

from server.core.models import User, Visitor

DEFAULT_ZONE = "Etc/UTC"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LocalDays:
    """The zone a series of days is counted in. `name` is what responses say it is."""

    name: str
    zone: ZoneInfo

    @classmethod
    def named(cls, name: str) -> "LocalDays":
        return cls(name, ZoneInfo(name))

    @classmethod
    def of(cls, user: User, tz: str | None = None) -> "LocalDays":
        """`tz` (already an IANA name the profile would store), else the viewer's profile
        zone, else UTC."""
        if not tz:
            profile = user.profile
            tz = profile.timezone if profile is not None and profile.timezone else DEFAULT_ZONE
        return cls.named(tz)

    def today(self) -> date:
        return _now().astimezone(self.zone).date()

    def bounds(self, first: date, days: int) -> list[datetime]:
        """`days` + 1 naive-UTC instants: the local midnight each day starts at, then the
        one after the last."""
        return [
            datetime.combine(first + timedelta(days=offset), time.min, tzinfo=self.zone)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
            for offset in range(days + 1)
        ]


def count_per_period(visits: Query, bounds: list[datetime]) -> list[int]:
    """How many of `visits` fall in each [bounds[i], bounds[i + 1]), in one query."""
    in_range = visits.filter(Visitor.visited_at >= bounds[0], Visitor.visited_at < bounds[-1])
    sums = [
        func.coalesce(
            func.sum(
                case((and_(Visitor.visited_at >= start, Visitor.visited_at < end), 1), else_=0)
            ),
            0,
        )
        for start, end in zip(bounds, bounds[1:], strict=False)
    ]
    return [int(count) for count in in_range.with_entities(*sums).one()]


def last_days(visits: Query, days: LocalDays, count: int) -> list[tuple[date, int]]:
    """The last `count` local days, oldest first and today last, with the visits in each."""
    first = days.today() - timedelta(days=count - 1)
    counts = count_per_period(visits, days.bounds(first, count))
    return [(first + timedelta(days=offset), n) for offset, n in enumerate(counts)]
