"""Resource planning: who can plan whom, working capacity per day and planned vs. booked time."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Allocation, Request, TimeEntry, User
from .holidays import holiday_dates
from .requests import deputy_for


def plannable_ids(db: Session, user: User) -> set[int]:
    """People the user may plan: HR/admins everyone, managers their team (and themselves), others nobody."""
    if user.is_hr:
        return set(db.scalars(select(User.id).where(User.is_active.is_(True))))
    if not user.is_approver and not deputy_for(db, user):
        return set()
    managers = [user.id] + deputy_for(db, user)
    team = set(db.scalars(select(User.id).where(User.manager_id.in_(managers), User.is_active.is_(True))))
    return team | ({user.id} if user.is_approver else set())


def absences(db: Session, person_ids: list[int], start: date, end: date) -> dict[int, dict[date, str]]:
    """Approved vacation per person and day."""
    out: dict[int, dict[date, str]] = {pid: {} for pid in person_ids}
    if not person_ids:
        return out
    rows = db.scalars(
        select(Request).where(
            Request.requester_id.in_(person_ids), Request.type == "vacation", Request.status == "approved",
            Request.start_date <= end, Request.end_date >= start,
        )
    )
    for r in rows:
        current = max(r.start_date, start)
        while current <= min(r.end_date, end):
            out[r.requester_id][current] = "vacation"
            current += timedelta(days=1)
    return out


class Calendar:
    """Daily working capacity in minutes, with holidays and vacation already taken out."""

    def __init__(self, db: Session, people: list[User], start: date, end: date):
        self.start, self.end = start, end
        self.holidays = holiday_dates(db, start, end)
        self.away = absences(db, [p.id for p in people], start, end)
        self.people = {p.id: p for p in people}

    def capacity(self, person_id: int, day: date) -> int:
        person = self.people[person_id]
        if day.weekday() >= 5 or day in self.holidays or day in self.away[person_id]:
            return 0
        if (person.start_date and day < person.start_date) or (person.last_day and day > person.last_day):
            return 0
        return person.weekly_minutes // 5

    def days(self):
        current = self.start
        while current <= self.end:
            yield current
            current += timedelta(days=1)


def planned_minutes(cal: Calendar, allocation: Allocation) -> int:
    """Planned minutes of one allocation inside the calendar's range, only on days the person works."""
    total = 0
    current = max(allocation.start_date, cal.start)
    while current <= min(allocation.end_date, cal.end):
        if cal.capacity(allocation.user_id, current):
            total += allocation.minutes_per_day
        current += timedelta(days=1)
    return total


def booked_minutes(db: Session, start: date, end: date, *, person_ids: list[int] | None = None,
                   project_id: int | None = None) -> dict[tuple[int, int | None], int]:
    """Finished time entries in the range, summed per (person, project)."""
    query = select(TimeEntry.user_id, TimeEntry.project_id, TimeEntry.start_at, TimeEntry.end_at).where(
        TimeEntry.day >= start, TimeEntry.day <= end, TimeEntry.end_at.is_not(None)
    )
    if person_ids is not None:
        query = query.where(TimeEntry.user_id.in_(person_ids))
    if project_id is not None:
        query = query.where(TimeEntry.project_id == project_id)
    out: dict[tuple[int, int | None], int] = {}
    for user_id, pid, start_at, end_at in db.execute(query):
        key = (user_id, pid)
        out[key] = out.get(key, 0) + max(0, int((end_at - start_at).total_seconds() // 60))
    return out


def project_span(db: Session, project_id: int) -> tuple[date, date] | None:
    """First and last day anything was planned or booked for the project."""
    lo_a, hi_a = db.execute(
        select(func.min(Allocation.start_date), func.max(Allocation.end_date)).where(Allocation.project_id == project_id)
    ).one()
    lo_t, hi_t = db.execute(
        select(func.min(TimeEntry.day), func.max(TimeEntry.day)).where(TimeEntry.project_id == project_id)
    ).one()
    lows = [d for d in (lo_a, lo_t) if d]
    highs = [d for d in (hi_a, hi_t) if d]
    return (min(lows), max(highs)) if lows else None
