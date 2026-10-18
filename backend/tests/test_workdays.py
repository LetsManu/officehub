from datetime import date

from app.workdays import count_working_days


def test_single_weekday():
    assert count_working_days(date(2026, 10, 19), date(2026, 10, 19)) == 1  # Monday


def test_full_week():
    assert count_working_days(date(2026, 10, 19), date(2026, 10, 25)) == 5


def test_weekend_only():
    assert count_working_days(date(2026, 10, 24), date(2026, 10, 25)) == 0


def test_spanning_weekend():
    assert count_working_days(date(2026, 10, 22), date(2026, 10, 27)) == 4  # Thu..Tue


def test_end_before_start():
    assert count_working_days(date(2026, 10, 27), date(2026, 10, 20)) == 0
