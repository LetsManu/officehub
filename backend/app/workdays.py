"""Working-day calculation (Monday to Friday; public holidays are not considered)."""

from datetime import date


def count_working_days(start: date, end: date) -> int:
    if end < start:
        return 0
    total_days = (end - start).days + 1
    full_weeks, remainder = divmod(total_days, 7)
    days = full_weeks * 5
    first_weekday = start.weekday()
    for offset in range(remainder):
        if (first_weekday + offset) % 7 < 5:
            days += 1
    return days
