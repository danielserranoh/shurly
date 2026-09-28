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

Phase 3.16 — a `Period` is the local days a per-link analytics route counts: the last N, or a
custom range, at most two years, never past today.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Query

from server.core.models import User, Visitor

DEFAULT_ZONE = "Etc/UTC"
DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 731  # two years, a leap day included


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

    def midnight(self, day: date) -> datetime:
        """The local midnight `day` starts at, as naive UTC like `visited_at`."""
        aware = datetime.combine(day, time.min, tzinfo=self.zone)
        return aware.astimezone(timezone.utc).replace(tzinfo=None)

    def local(self, at: datetime) -> datetime:
        """A naive-UTC instant (`visited_at`) as the zone's local time."""
        return at.replace(tzinfo=timezone.utc).astimezone(self.zone)

    def bounds(self, first: date, days: int) -> list[datetime]:
        """`days` + 1 naive-UTC instants: the local midnight each day starts at, then the
        one after the last."""
        return [self.midnight(first + timedelta(days=offset)) for offset in range(days + 1)]


class PeriodError(ValueError):
    """A period a route can't count: the message says why (a 422)."""


@dataclass(frozen=True)
class Period:
    """Phase 3.16 — the local days a per-link analytics route counts, `first` to `last`."""

    first: date
    last: date
    days: LocalDays

    @classmethod
    def resolve(
        cls, days: LocalDays, period: int | None, first: date | None, last: date | None
    ) -> "Period":
        """The last `period` local days, today included, or `first` to `last`. A custom range
        ends today at the latest, and lasts at most MAX_PERIOD_DAYS once it does."""
        if (first is None) != (last is None):
            raise PeriodError("Give both from and to, or neither.")
        if first is not None and period is not None:
            raise PeriodError("Give a period, or from and to, not both.")
        today = days.today()
        if first is None or last is None:
            length = period or DEFAULT_PERIOD_DAYS
            return cls(today - timedelta(days=length - 1), today, days)
        if first > last:
            raise PeriodError("from is after to.")
        last = min(last, today)
        if first > last:
            raise PeriodError("The range starts after today.")
        if (last - first).days + 1 > MAX_PERIOD_DAYS:
            raise PeriodError(f"A range lasts at most {MAX_PERIOD_DAYS} days.")
        return cls(first, last, days)

    def bounds(self) -> tuple[datetime, datetime]:
        """Naive UTC: the local midnight `first` starts at, and the one after `last`."""
        return self.days.midnight(self.first), self.days.midnight(self.last + timedelta(days=1))

    def buckets(self, group_by: str) -> list[tuple[date, date]]:
        """The local days, ISO weeks (from Monday) or months of the period, oldest first, as
        their first and last day, the first and last bucket clipped to the period."""
        buckets = []
        day = self.first
        while day <= self.last:
            if group_by == "week":
                end = day + timedelta(days=6 - day.weekday())
            elif group_by == "month":
                end = date(day.year + day.month // 12, day.month % 12 + 1, 1) - timedelta(days=1)
            else:
                end = day
            end = min(end, self.last)
            buckets.append((day, end))
            day = end + timedelta(days=1)
        return buckets


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
