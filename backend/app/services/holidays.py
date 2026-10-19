"""Public holidays for the configured country/region plus company holidays HR adds."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..holidays import public_holidays
from ..models import CompanyHoliday
from .settings import get_setting

DEFAULT_CONFIG = {"country": "", "region": ""}


def holiday_config(db: Session) -> dict:
    return {**DEFAULT_CONFIG, **get_setting(db, "holidays", {})}


def holidays_in(db: Session, start: date, end: date) -> list[tuple[date, str, str, bool]]:
    """(date, German name, English name, is company holiday) between start and end, sorted."""
    config = holiday_config(db)
    out: list[tuple[date, str, str, bool]] = []
    if config["country"]:
        for year in range(start.year, end.year + 1):
            out.extend((d, de, en, False) for d, de, en in public_holidays(year, config["country"], config["region"]))
    for row in db.scalars(select(CompanyHoliday).where(CompanyHoliday.day >= start, CompanyHoliday.day <= end)):
        out.append((row.day, row.name, row.name, True))
    return sorted((h for h in out if start <= h[0] <= end), key=lambda h: h[0])


def holiday_dates(db: Session, start: date | None, end: date | None) -> set[date]:
    if not start or not end or end < start:
        return set()
    return {h[0] for h in holidays_in(db, start, end)}
