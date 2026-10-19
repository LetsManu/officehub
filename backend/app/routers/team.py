"""Who is away, celebrations, the team calendar, vacation balance and the company activity feed."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import and_, select

from ..deps import DB, CurrentUser
from ..errors import ApiError
from ..models import PENDING_STATUSES, Announcement, Document, Request, User
from ..schemas import UserBrief

router = APIRouter(prefix="/api", tags=["team"])

AbsenceType = Literal["vacation", "home_office"]


class Absence(BaseModel):
    person: UserBrief
    type: AbsenceType
    start_date: date
    end_date: date


class Celebration(BaseModel):
    person: UserBrief
    kind: Literal["birthday", "anniversary", "new"]
    date: date
    years: int | None = None


class CalendarEvent(BaseModel):
    title: str
    date: date
    link: str


class Calendar(BaseModel):
    month: str
    absences: list[Absence]
    events: list[CalendarEvent]
    birthdays: list[Celebration]


class VacationBalance(BaseModel):
    year: int
    entitlement: int
    taken: int  # approved
    planned: int  # sent, not decided yet
    remaining: int  # entitlement - taken - planned


class ActivityItem(BaseModel):
    kind: Literal["announcement", "document", "new_colleague", "anniversary"]
    title: str
    date: date
    link: str
    years: int | None = None


# ---------- helpers ----------


def _absences(db, start: date, end: date, department: str | None = None) -> list[Absence]:
    """Approved vacation and home office overlapping [start, end]. Reasons are never shown."""
    query = (
        select(Request)
        .join(User, User.id == Request.requester_id)
        .where(
            Request.status == "approved",
            Request.type.in_(("vacation", "home_office")),
            Request.start_date <= end,
            Request.end_date >= start,
            User.is_active.is_(True),
        )
        .order_by(Request.start_date, User.last_name)
    )
    if department:
        query = query.where(User.department == department)
    return [
        Absence(person=UserBrief.model_validate(r.requester), type=r.type, start_date=r.start_date, end_date=r.end_date)
        for r in db.scalars(query)
    ]


def _on_or_after(day: int, month: int, start: date) -> date:
    """Next date with this day/month on or after start (29 Feb falls back to 28 Feb)."""
    for year in (start.year, start.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = date(year, month, 28)
        if candidate >= start:
            return candidate
    return candidate


def _active_people(db, department: str | None = None):
    query = select(User).where(User.is_active.is_(True))
    if department:
        query = query.where(User.department == department)
    return db.scalars(query).all()


def _month_range(month: str) -> tuple[date, date]:
    try:
        first = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise ApiError(422, "invalid_month", "Please use the format YYYY-MM.")
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first, last


def _calendar(db, month: str, department: str | None) -> Calendar:
    first, last = _month_range(month)
    events = db.scalars(
        select(Announcement).where(
            Announcement.archived.is_(False),
            Announcement.publish_date <= date.today(),
            Announcement.event_date >= first,
            Announcement.event_date <= last,
        )
    ).all()
    birthdays = []
    for person in _active_people(db, department):
        if person.show_birthday and person.birthday_month == first.month and person.birthday_day:
            day = _on_or_after(person.birthday_day, person.birthday_month, first)
            birthdays.append(Celebration(person=UserBrief.model_validate(person), kind="birthday", date=day))
    return Calendar(
        month=month,
        absences=_absences(db, first, last, department),
        events=[CalendarEvent(title=e.title, date=e.event_date, link=f"/announcements#a-{e.id}") for e in events],
        birthdays=sorted(birthdays, key=lambda c: c.date),
    )


# ---------- endpoints ----------


@router.get("/team/away", response_model=list[Absence])
def who_is_away(user: CurrentUser, db: DB, days: int = Query(7, ge=0, le=31)) -> list[Absence]:
    today = date.today()
    return _absences(db, today, today + timedelta(days=days))


@router.get("/team/celebrations", response_model=list[Celebration])
def celebrations(user: CurrentUser, db: DB, days: int = Query(14, ge=1, le=60)) -> list[Celebration]:
    today = date.today()
    until = today + timedelta(days=days)
    out: list[Celebration] = []
    for person in _active_people(db):
        brief = UserBrief.model_validate(person)
        if person.show_birthday and person.birthday_day and person.birthday_month:
            day = _on_or_after(person.birthday_day, person.birthday_month, today)
            if day <= until:
                out.append(Celebration(person=brief, kind="birthday", date=day))
        if person.start_date:
            if today - timedelta(days=30) <= person.start_date <= today:
                out.append(Celebration(person=brief, kind="new", date=person.start_date))
            elif person.start_date < today:
                day = _on_or_after(person.start_date.day, person.start_date.month, today)
                years = day.year - person.start_date.year
                if day <= until and years >= 1:
                    out.append(Celebration(person=brief, kind="anniversary", date=day, years=years))
    return sorted(out, key=lambda c: (c.kind == "new", c.date))


@router.get("/team/calendar", response_model=Calendar)
def team_calendar(
    user: CurrentUser, db: DB, month: str = Query(..., max_length=7), department: str | None = Query(None, max_length=80)
) -> Calendar:
    return _calendar(db, month, department)


def _ics_text(value: str) -> str:
    """Escapes text for iCalendar (RFC 5545, section 3.3.11)."""
    for char, escaped in (("\\", "\\\\"), (";", "\\;"), (",", "\\,"), ("\n", "\\n")):
        value = value.replace(char, escaped)
    return value


@router.get("/team/calendar.ics")
def team_calendar_ics(
    user: CurrentUser, db: DB, month: str = Query(..., max_length=7), department: str | None = Query(None, max_length=80)
) -> Response:
    """The month as an iCalendar file to import into Outlook, Thunderbird or a phone calendar."""
    data = _calendar(db, month, department)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OfficeHub//Team calendar//EN", "CALSCALE:GREGORIAN"]

    def event(uid: str, start: date, end: date, summary: str) -> None:
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}@officehub",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_ics_text(summary)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ])

    labels = {"vacation": "Urlaub / Vacation", "home_office": "Homeoffice"}
    for i, a in enumerate(data.absences):
        event(f"absence-{a.person.id}-{a.start_date}-{i}", a.start_date, a.end_date, f"{a.person.full_name}: {labels[a.type]}")
    for e in data.events:
        event(f"event-{e.link.rsplit('-', 1)[-1]}-{e.date}", e.date, e.date, e.title)
    for b in data.birthdays:
        event(f"birthday-{b.person.id}-{b.date}", b.date, b.date, f"{b.person.full_name}: Geburtstag / Birthday")
    lines.append("END:VCALENDAR")
    return Response(
        "\r\n".join(lines) + "\r\n",
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="officehub-{month}.ics"'},
    )


@router.get("/me/vacation", response_model=VacationBalance)
def vacation_balance(user: CurrentUser, db: DB, year: int | None = Query(None, ge=2000, le=2100)) -> VacationBalance:
    year = year or date.today().year
    rows = db.execute(
        select(Request.status, Request.working_days).where(
            Request.requester_id == user.id,
            Request.type == "vacation",
            Request.start_date >= date(year, 1, 1),
            Request.start_date <= date(year, 12, 31),
            Request.status.in_(("approved", *PENDING_STATUSES)),
        )
    ).all()
    taken = sum(days or 0 for status, days in rows if status == "approved")
    planned = sum(days or 0 for status, days in rows if status in PENDING_STATUSES)
    return VacationBalance(
        year=year, entitlement=user.vacation_days, taken=taken, planned=planned, remaining=user.vacation_days - taken - planned
    )


@router.get("/activity", response_model=list[ActivityItem])
def activity(user: CurrentUser, db: DB, limit: int = Query(20, ge=1, le=50)) -> list[ActivityItem]:
    """What happened in the company recently: news, updated documents, new colleagues, anniversaries."""
    today = date.today()
    since = today - timedelta(days=60)
    items: list[ActivityItem] = []
    for a in db.scalars(
        select(Announcement).where(
            Announcement.archived.is_(False), Announcement.publish_date <= today, Announcement.publish_date >= since
        )
    ):
        items.append(ActivityItem(kind="announcement", title=a.title, date=a.publish_date, link=f"/announcements#a-{a.id}"))
    for d in db.scalars(select(Document).where(Document.archived.is_(False), Document.updated_at >= since)):
        items.append(ActivityItem(kind="document", title=d.title, date=d.updated_at.date(), link=f"/documents/{d.id}"))
    for p in db.scalars(select(User).where(and_(User.is_active.is_(True), User.start_date.is_not(None)))):
        if since <= p.start_date <= today:
            items.append(ActivityItem(kind="new_colleague", title=p.full_name, date=p.start_date, link=f"/people?q={quote(p.full_name)}"))
        elif p.start_date < since:
            anniversary = _on_or_after(p.start_date.day, p.start_date.month, since)
            if anniversary <= today:
                items.append(
                    ActivityItem(
                        kind="anniversary", title=p.full_name, date=anniversary, link=f"/people?q={quote(p.full_name)}",
                        years=anniversary.year - p.start_date.year,
                    )
                )
    items.sort(key=lambda i: i.date, reverse=True)
    return items[:limit]
