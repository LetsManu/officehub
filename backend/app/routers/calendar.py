"""My calendar, like in Outlook: meetings, room bookings, my time off, public holidays and company events
in one list for a date range. The team view (who is away) stays in /api/team/calendar."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from ..config import settings
from ..deps import DB, CurrentUser
from ..errors import ApiError
from ..models import PENDING_STATUSES, Announcement, Meeting, MeetingInvitee, Request, Room, RoomBooking, Space, User
from ..schemas import UtcDateTime
from ..services.holidays import holidays_in
from ..services.recurrence import local_day, occurrences

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class Entry(BaseModel):
    id: str
    kind: str  # meeting, booking, vacation, home_office, holiday, event
    title: str
    start: UtcDateTime | None = None  # timed entries
    end: UtcDateTime | None = None
    day: date | None = None  # all-day entries (first and last day)
    last_day: date | None = None
    detail: str = ""  # room, space, organizer …
    status: str = ""  # meeting: my answer; time off: approved / pending
    link: str = ""
    series: bool = False


class Busy(BaseModel):
    start: UtcDateTime
    end: UtcDateTime
    kind: str  # meeting, booking, away – never what it is about


def _range(start: date, end: date, days: int) -> tuple[datetime, datetime]:
    if end < start or (end - start).days > days:
        raise ApiError(422, "invalid_range", "Please choose a shorter time range.")
    tz = ZoneInfo(settings.timezone)
    since = datetime.combine(start, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    return since, until


def _meetings(db, ids: list[int], since: datetime, until: datetime) -> list[Meeting]:
    """Planned meetings of these people (organizer, or invited and not declined) that may fall into the range."""
    invited = select(MeetingInvitee.meeting_id).where(MeetingInvitee.user_id.in_(ids), MeetingInvitee.response != "declined")
    return list(db.scalars(select(Meeting).where(
        Meeting.kind == "scheduled", Meeting.cancelled.is_(False), Meeting.starts_at < until,
        or_(Meeting.ends_at > since, Meeting.recurrence != ""),
        or_(Meeting.organizer_id.in_(ids), Meeting.id.in_(invited)),
    ).order_by(Meeting.starts_at)))


def _utc(day: date, clock: str) -> datetime:
    """A local wall-clock time (bookings are stored like that) as UTC without time zone, like all other times."""
    hours, minutes = (int(x) for x in clock.split(":"))
    local = datetime.combine(day, time(hours, minutes), tzinfo=ZoneInfo(settings.timezone))
    return local.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("", response_model=list[Entry])
def my_calendar(user: CurrentUser, db: DB, start: date = Query(...), end: date = Query(...)) -> list[Entry]:
    since, until = _range(start, end, 62)
    out: list[Entry] = []
    for m in _meetings(db, [user.id], since, until):
        mine = next((i.response for i in m.invitees if i.user_id == user.id), "organizer")
        space = db.get(Space, m.space_id) if m.space_id else None
        detail = " · ".join(x for x in (m.organizer.full_name if m.organizer else "", space.name if space else "") if x)
        for begins, ends in occurrences(m, since, until):
            day = local_day(begins).isoformat()
            out.append(Entry(id=f"m{m.id}-{day}", kind="meeting", title=m.title, start=begins, end=ends, detail=detail,
                             status=mine, series=bool(m.recurrence),
                             link=f"/meetings/{m.id}?occurrence={day}" if m.recurrence else f"/meetings/{m.id}"))

    for b in db.scalars(select(RoomBooking).where(RoomBooking.user_id == user.id, RoomBooking.day >= start,
                                                  RoomBooking.day <= end)):
        out.append(Entry(id=f"b{b.id}", kind="booking", title=b.title, start=_utc(b.day, b.start_time),
                         end=_utc(b.day, b.end_time), detail=b.room.name, link="/rooms"))

    for r in db.scalars(select(Request).where(
        Request.requester_id == user.id, Request.type.in_(("vacation", "home_office")),
        Request.status.in_(("approved", *PENDING_STATUSES)), Request.start_date <= end, Request.end_date >= start,
    )):
        out.append(Entry(id=f"r{r.id}", kind=r.type, title="", day=r.start_date, last_day=r.end_date,
                         status="approved" if r.status == "approved" else "pending", link=f"/requests/{r.id}"))

    for day, name_de, name_en, _company in holidays_in(db, start, end):
        out.append(Entry(id=f"h{day.isoformat()}", kind="holiday", title=name_de if user.language == "de" else name_en,
                         day=day, last_day=day))

    for a in db.scalars(select(Announcement).where(
        Announcement.archived.is_(False), Announcement.publish_date <= date.today(),
        Announcement.event_date >= start, Announcement.event_date <= end,
    )):
        out.append(Entry(id=f"e{a.id}", kind="event", title=a.title, day=a.event_date, last_day=a.event_date,
                         link=f"/announcements#a-{a.id}"))
    return out


@router.get("/busy", response_model=dict[int, list[Busy]])
def free_busy(user: CurrentUser, db: DB, ids: str = Query(..., max_length=2000), start: date = Query(...),
              end: date = Query(...)) -> dict[int, list[Busy]]:
    """When colleagues are busy – for finding a time for a meeting. Shows only busy times, never what they are."""
    since, until = _range(start, end, 31)
    try:
        wanted = sorted({int(x) for x in ids.split(",") if x.strip()})[:50]
    except ValueError:
        raise ApiError(422, "invalid_ids", "Please send person numbers.") from None
    active = set(db.scalars(select(User.id).where(User.id.in_(wanted), User.is_active.is_(True))))
    out: dict[int, list[Busy]] = {uid: [] for uid in active}
    for m in _meetings(db, list(active), since, until):
        people = {i.user_id for i in m.invitees if i.response != "declined"} | ({m.organizer_id} if m.organizer_id else set())
        for start_at, end_at in occurrences(m, since, until):
            for uid in people & active:
                out[uid].append(Busy(start=start_at, end=end_at, kind="meeting"))
    # Only meeting rooms: a booked desk or parking space does not make anyone busy
    for b in db.scalars(select(RoomBooking).join(Room, Room.id == RoomBooking.room_id).where(
        RoomBooking.user_id.in_(active), RoomBooking.day >= start, RoomBooking.day <= end, Room.kind == "room",
    )):
        out[b.user_id].append(Busy(start=_utc(b.day, b.start_time), end=_utc(b.day, b.end_time), kind="booking"))
    for r in db.scalars(select(Request).where(
        Request.requester_id.in_(active), Request.type == "vacation", Request.status == "approved",
        Request.start_date <= end, Request.end_date >= start,
    )):
        first, last = max(r.start_date, start), min(r.end_date, end)
        out[r.requester_id].append(Busy(start=_range(first, first, 0)[0], end=_range(last, last, 0)[1], kind="away"))
    for items in out.values():
        items.sort(key=lambda b: b.start)
    return out
