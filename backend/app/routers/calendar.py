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
from ..models import PENDING_STATUSES, Announcement, Meeting, MeetingInvitee, Request, RoomBooking, Space
from ..schemas import UtcDateTime
from ..services.holidays import holidays_in

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


def _utc(day: date, clock: str) -> datetime:
    """A local wall-clock time (bookings are stored like that) as UTC without time zone, like all other times."""
    hours, minutes = (int(x) for x in clock.split(":"))
    local = datetime.combine(day, time(hours, minutes), tzinfo=ZoneInfo(settings.timezone))
    return local.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("", response_model=list[Entry])
def my_calendar(user: CurrentUser, db: DB, start: date = Query(...), end: date = Query(...)) -> list[Entry]:
    if end < start or (end - start).days > 62:
        raise ApiError(422, "invalid_range", "Please choose at most two months.")
    tz = ZoneInfo(settings.timezone)
    since = datetime.combine(start, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    out: list[Entry] = []

    invited = select(MeetingInvitee.meeting_id).where(MeetingInvitee.user_id == user.id,
                                                       MeetingInvitee.response != "declined")
    meetings = db.scalars(select(Meeting).where(
        Meeting.kind == "scheduled", Meeting.cancelled.is_(False), Meeting.starts_at < until, Meeting.ends_at > since,
        or_(Meeting.organizer_id == user.id, Meeting.id.in_(invited)),
    ).order_by(Meeting.starts_at))
    for m in meetings:
        mine = next((i.response for i in m.invitees if i.user_id == user.id), "organizer")
        space = db.get(Space, m.space_id) if m.space_id else None
        detail = " · ".join(x for x in (m.organizer.full_name if m.organizer else "", space.name if space else "") if x)
        out.append(Entry(id=f"m{m.id}", kind="meeting", title=m.title, start=m.starts_at, end=m.ends_at, detail=detail,
                         status=mine, link=f"/meetings/{m.id}"))

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
