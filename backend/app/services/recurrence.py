"""Recurring meetings: the single occurrences of a series in a time range.

A series repeats at the same local wall-clock time (09:00 stays 09:00 across daylight saving time).
Times are stored and returned as UTC without a time zone, like everywhere else.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import settings
from ..models import Meeting

RECURRENCES = ("", "daily", "weekdays", "weekly", "biweekly", "monthly")
MAX_STEPS = 2000  # about five years of daily meetings – plenty, and it keeps every lookup quick


def _local(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.timezone))


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def skipped_days(meeting: Meeting) -> set[str]:
    return {d for d in (meeting.skipped or "").split(",") if d}


def _local_starts(meeting: Meeting):
    """Local start of every occurrence, in order (skipped days included; the caller drops them)."""
    first = _local(meeting.starts_at)
    rule = meeting.recurrence or ""
    if not rule:
        yield first
        return
    tz = first.tzinfo
    naive = first.replace(tzinfo=None)
    step = 0
    month = 0
    while step < MAX_STEPS:
        if rule == "monthly":
            year, mon = divmod(naive.month - 1 + month, 12)
            month += 1
            try:
                candidate = naive.replace(year=naive.year + year, month=mon + 1)
            except ValueError:  # e.g. the 31st in a shorter month: no meeting that month
                step += 1
                continue
        else:
            days = {"daily": 1, "weekdays": 1, "weekly": 7, "biweekly": 14}[rule] * step
            candidate = naive + timedelta(days=days)
            if rule == "weekdays" and candidate.weekday() >= 5:
                step += 1
                continue
        step += 1
        if meeting.recurrence_until and candidate.date() > meeting.recurrence_until:
            return
        yield candidate.replace(tzinfo=tz)


def occurrences(meeting: Meeting, since: datetime, until: datetime) -> list[tuple[datetime, datetime]]:
    """(start, end) in UTC of every occurrence overlapping [since, until)."""
    if meeting.starts_at is None:
        return []
    length = (meeting.ends_at or meeting.starts_at + timedelta(hours=1)) - meeting.starts_at
    skip = skipped_days(meeting)
    out = []
    for local_start in _local_starts(meeting):
        start = _utc(local_start)
        if start >= until:
            break
        if start + length > since and local_start.date().isoformat() not in skip:
            out.append((start, start + length))
    return out


def next_occurrence(meeting: Meeting, after: datetime) -> tuple[datetime, datetime] | None:
    """The first occurrence that has not ended yet at `after` (within the next two years)."""
    found = occurrences(meeting, after, after + timedelta(days=740))
    return found[0] if found else None


def is_series(meeting: Meeting) -> bool:
    return bool(meeting.recurrence)


def local_day(value: datetime) -> date:
    return _local(value).date()


def rrule(meeting: Meeting) -> str | None:
    """The same rule for calendar files (Outlook, Thunderbird, phones)."""
    rule = meeting.recurrence or ""
    if not rule:
        return None
    parts = {
        "daily": "FREQ=DAILY",
        "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        "weekly": "FREQ=WEEKLY",
        "biweekly": "FREQ=WEEKLY;INTERVAL=2",
        "monthly": "FREQ=MONTHLY",
    }[rule]
    if meeting.recurrence_until:
        end = datetime.combine(meeting.recurrence_until, datetime.max.time()).replace(tzinfo=ZoneInfo(settings.timezone))
        parts += f";UNTIL={_utc(end).strftime('%Y%m%dT%H%M%SZ')}"
    return f"RRULE:{parts}"
