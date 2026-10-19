"""Working-day calculation: Monday to Friday, minus the public and company holidays passed in."""

from collections.abc import Collection
from datetime import date, timedelta


def count_working_days(start: date, end: date, holidays: Collection[date] = ()) -> int:
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            days += 1
        current += timedelta(days=1)
    return days
