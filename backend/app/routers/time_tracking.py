"""Working time: clock in/out, hand-entered times, weekly timesheet, overtime balance and exports.

Times are stored in UTC and shown in the company's time zone (TIMEZONE setting). The daily target is
the weekly working time divided by five on Monday to Friday; public/company holidays and approved
vacation days have no target.
"""

import csv
import io
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..deps import DB, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import Request, TimeEntry, User, utcnow
from ..schemas import UserBrief, UtcDateTime
from ..services.holidays import holidays_in
from ..services.requests import deputy_for

router = APIRouter(prefix="/api/time", tags=["time tracking"])

TZ = ZoneInfo(settings.timezone)
HAND_EDIT_DAYS = 31  # people can add or fix their own times for this many days back
Clock = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class EntryOut(BaseModel):
    id: int
    day: date
    start_at: UtcDateTime
    end_at: UtcDateTime | None
    minutes: int
    note: str
    edited: bool


class DayOut(BaseModel):
    date: date
    entries: list[EntryOut]
    worked: int
    target: int
    off: str | None  # "holiday:<name>", "vacation" or None
    warnings: list[str]


class Week(BaseModel):
    person: UserBrief
    start: date
    days: list[DayOut]
    worked: int
    target: int
    balance_year: int  # minutes over (+) or under (-) target this year, since time was first recorded


class Status(BaseModel):
    running: EntryOut | None
    today_worked: int
    today_target: int
    week_worked: int
    week_target: int
    balance_year: int


class EntryIn(BaseModel):
    day: date
    start: Clock
    end: Clock
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class EntryUpdate(BaseModel):
    start: Clock
    end: Clock
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class NoteIn(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class TeamRow(BaseModel):
    person: UserBrief
    worked: int
    target: int
    clocked_in: bool


# ---------- helpers ----------


def local_today() -> date:
    return datetime.now(TZ).date()


def _to_utc(day: date, clock: str) -> datetime:
    local = datetime.combine(day, time.fromisoformat(clock), tzinfo=TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _minutes(entry: TimeEntry, now: datetime | None = None) -> int:
    end = entry.end_at or now or utcnow()
    return max(0, int((end - entry.start_at).total_seconds() // 60))


def _out(entry: TimeEntry) -> EntryOut:
    return EntryOut(
        id=entry.id, day=entry.day, start_at=entry.start_at, end_at=entry.end_at,
        minutes=_minutes(entry), note=entry.note, edited=entry.edited,
    )


def _field_error(field: str, code: str, message: str) -> ApiError:
    error = ApiError(422, code, message)
    error.field = field  # type: ignore[attr-defined]
    return error


def _vacation_days(db: Session, person: User, start: date, end: date) -> set[date]:
    rows = db.scalars(
        select(Request).where(
            Request.requester_id == person.id, Request.type == "vacation", Request.status == "approved",
            Request.start_date <= end, Request.end_date >= start,
        )
    )
    days: set[date] = set()
    for r in rows:
        current = max(r.start_date, start)
        while current <= min(r.end_date, end):
            days.add(current)
            current += timedelta(days=1)
    return days


def _days(db: Session, person: User, start: date, end: date) -> list[DayOut]:
    entries = db.scalars(
        select(TimeEntry).where(TimeEntry.user_id == person.id, TimeEntry.day >= start, TimeEntry.day <= end).order_by(TimeEntry.start_at)
    ).all()
    holidays = {h[0]: (h[1] if person.language == "de" else h[2]) for h in holidays_in(db, start, end)}
    vacation = _vacation_days(db, person, start, end)
    daily = person.weekly_minutes // 5
    out: list[DayOut] = []
    current = start
    while current <= end:
        day_entries = [e for e in entries if e.day == current]
        worked = sum(_minutes(e) for e in day_entries)
        off = f"holiday:{holidays[current]}" if current in holidays else ("vacation" if current in vacation else None)
        before_start = person.start_date is not None and current < person.start_date
        target = 0 if (current.weekday() >= 5 or off or before_start) else daily
        out.append(DayOut(date=current, entries=[_out(e) for e in day_entries], worked=worked, target=target, off=off,
                          warnings=_warnings(day_entries, worked)))
        current += timedelta(days=1)
    return out


def _warnings(entries: list[TimeEntry], worked: int) -> list[str]:
    """Gentle hints based on common working-time rules (breaks after 6 and 9 hours, max. 10 hours)."""
    warnings: list[str] = []
    if not entries:
        return warnings
    finished = [e for e in entries if e.end_at]
    if finished:
        span = int((max(e.end_at for e in finished) - min(e.start_at for e in entries)).total_seconds() // 60)
        pause = max(0, span - worked)
        if (worked > 9 * 60 and pause < 45) or (worked > 6 * 60 and pause < 30):
            warnings.append("break_short")
    if worked > 10 * 60:
        warnings.append("over_ten_hours")
    if any(e.end_at is None and e.day < local_today() for e in entries):
        warnings.append("still_running")
    return warnings


def _balance(db: Session, person: User, until: date) -> int:
    """Over/under time this year, counted from the first day the person recorded any time."""
    first = db.scalar(select(func.min(TimeEntry.day)).where(TimeEntry.user_id == person.id))
    if first is None:
        return 0
    start = max(date(until.year, 1, 1), first, person.start_date or first)
    if start > until:
        return 0
    return sum(d.worked - d.target for d in _days(db, person, start, until))


def _team_ids(db: Session, user: User) -> set[int]:
    if user.is_admin:
        return set(db.scalars(select(User.id).where(User.is_active.is_(True))))
    managers = [user.id] + deputy_for(db, user)
    return set(db.scalars(select(User.id).where(User.manager_id.in_(managers), User.is_active.is_(True))))


def _person(db: Session, user: User, person_id: int | None) -> User:
    """The signed-in person, or someone they may see: HR sees everyone, managers their team."""
    if person_id is None or person_id == user.id:
        return user
    if person_id not in _team_ids(db, user):
        raise forbidden()
    person = db.get(User, person_id)
    if person is None:
        raise not_found("Person")
    return person


def _running(db: Session, user: User) -> TimeEntry | None:
    return db.scalar(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.end_at.is_(None)))


def _check_overlap(db: Session, user: User, start: datetime, end: datetime, ignore_id: int | None = None) -> None:
    query = select(TimeEntry).where(
        TimeEntry.user_id == user.id, TimeEntry.start_at < end,
        (TimeEntry.end_at.is_(None)) | (TimeEntry.end_at > start),
    )
    if ignore_id:
        query = query.where(TimeEntry.id != ignore_id)
    if db.scalar(query) is not None:
        raise _field_error("start", "time_overlap", "This time overlaps with another entry.")


def _editable(db: Session, user: User, entry_id: int) -> TimeEntry:
    entry = db.get(TimeEntry, entry_id)
    if entry is None or not (entry.user_id == user.id or user.is_admin):
        raise not_found("Time entry")
    if entry.user_id == user.id and not user.is_admin and entry.day < local_today() - timedelta(days=HAND_EDIT_DAYS):
        raise ApiError(409, "time_locked", "Times older than 31 days can only be changed by HR.")
    return entry


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


# ---------- endpoints ----------


@router.get("/status", response_model=Status)
def status(user: CurrentUser, db: DB) -> Status:
    today = local_today()
    week = _days(db, user, _monday(today), _monday(today) + timedelta(days=6))
    today_row = next(d for d in week if d.date == today)
    running = _running(db, user)
    return Status(
        running=_out(running) if running else None,
        today_worked=today_row.worked, today_target=today_row.target,
        week_worked=sum(d.worked for d in week), week_target=sum(d.target for d in week),
        balance_year=_balance(db, user, today),
    )


@router.post("/clock-in", response_model=Status)
def clock_in(body: NoteIn, user: CurrentUser, db: DB) -> Status:
    if _running(db, user):
        raise ApiError(409, "already_clocked_in", "You are already clocked in.")
    now = utcnow()
    db.add(TimeEntry(user_id=user.id, day=local_today(), start_at=now.replace(second=0, microsecond=0), note=body.note))
    db.commit()
    return status(user, db)


@router.post("/clock-out", response_model=Status)
def clock_out(user: CurrentUser, db: DB) -> Status:
    entry = _running(db, user)
    if entry is None:
        raise ApiError(409, "not_clocked_in", "You are not clocked in.")
    entry.end_at = max(utcnow().replace(second=0, microsecond=0), entry.start_at)
    db.commit()
    return status(user, db)


@router.get("/week", response_model=Week)
def week(user: CurrentUser, db: DB, start: date | None = None, person_id: int | None = None) -> Week:
    person = _person(db, user, person_id)
    monday = _monday(start or local_today())
    days = _days(db, person, monday, monday + timedelta(days=6))
    return Week(
        person=UserBrief.model_validate(person), start=monday, days=days,
        worked=sum(d.worked for d in days), target=sum(d.target for d in days),
        balance_year=_balance(db, person, min(local_today(), monday + timedelta(days=6))),
    )


@router.post("/entries", response_model=EntryOut, status_code=201)
def add_entry(body: EntryIn, user: CurrentUser, db: DB) -> EntryOut:
    today = local_today()
    if body.day > today:
        raise _field_error("day", "day_future", "Times can only be entered for today or earlier.")
    if body.day < today - timedelta(days=HAND_EDIT_DAYS) and not user.is_admin:
        raise _field_error("day", "time_locked", "Times older than 31 days can only be changed by HR.")
    if body.end <= body.start:
        raise _field_error("end", "end_before_start_time", "The end time must be after the start time.")
    start, end = _to_utc(body.day, body.start), _to_utc(body.day, body.end)
    if end > utcnow() + timedelta(minutes=1):
        raise _field_error("end", "time_future", "The end time cannot be in the future.")
    _check_overlap(db, user, start, end)
    entry = TimeEntry(user_id=user.id, day=body.day, start_at=start, end_at=end, note=body.note, edited=True)
    db.add(entry)
    db.commit()
    return _out(entry)


@router.put("/entries/{entry_id}", response_model=EntryOut)
def update_entry(entry_id: int, body: EntryUpdate, user: CurrentUser, db: DB) -> EntryOut:
    entry = _editable(db, user, entry_id)
    if body.end <= body.start:
        raise _field_error("end", "end_before_start_time", "The end time must be after the start time.")
    start, end = _to_utc(entry.day, body.start), _to_utc(entry.day, body.end)
    if end > utcnow() + timedelta(minutes=1):
        raise _field_error("end", "time_future", "The end time cannot be in the future.")
    owner = db.get(User, entry.user_id)
    _check_overlap(db, owner, start, end, ignore_id=entry.id)
    entry.start_at, entry.end_at, entry.note, entry.edited = start, end, body.note, True
    db.commit()
    return _out(entry)


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, user: CurrentUser, db: DB) -> None:
    db.delete(_editable(db, user, entry_id))
    db.commit()


@router.get("/team", response_model=list[TeamRow])
def team(user: CurrentUser, db: DB, start: date | None = None) -> list[TeamRow]:
    ids = _team_ids(db, user)
    if not ids:
        raise forbidden()
    monday = _monday(start or local_today())
    rows = []
    for person in db.scalars(select(User).where(User.id.in_(ids)).order_by(User.last_name, User.first_name)):
        days = _days(db, person, monday, monday + timedelta(days=6))
        rows.append(TeamRow(
            person=UserBrief.model_validate(person), worked=sum(d.worked for d in days),
            target=sum(d.target for d in days), clocked_in=_running(db, person) is not None,
        ))
    return rows


@router.get("/export.csv")
def export(user: CurrentUser, db: DB, month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), person_id: int | None = None) -> Response:
    person = _person(db, user, person_id)
    first = date.fromisoformat(f"{month}-01")
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["date", "start", "end", "minutes", "target_minutes", "note", "day_off"])
    for day in _days(db, person, first, last):
        if not day.entries:
            writer.writerow([day.date.isoformat(), "", "", 0, day.target, "", day.off or ""])
        for e in day.entries:
            start = e.start_at.replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%H:%M")
            end = e.end_at.replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%H:%M") if e.end_at else ""
            note = ("'" + e.note) if e.note[:1] in ("=", "+", "-", "@") else e.note
            writer.writerow([day.date.isoformat(), start, end, e.minutes, day.target, note, day.off or ""])
    name = f"time-{re.sub(r'[^a-z0-9]+', '-', person.last_name.lower()).strip('-') or person.id}-{month}.csv"
    return Response(
        "﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
