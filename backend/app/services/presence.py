"""Who is reachable right now, like the coloured dot in Teams.

"auto" follows what OfficeHub knows: in a meeting or call, a meeting in the calendar, approved vacation,
no mouse or keyboard for a while. People can also choose a status themselves, with a short message.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Meeting, MeetingInvitee, MeetingPresence, Request, User, utcnow
from .recurrence import occurrences

MANUAL = ("auto", "available", "busy", "dnd", "away", "offline")
ONLINE_SECONDS = 150  # the portal reports every 30 seconds; a little slack for slow networks
IN_MEETING_SECONDS = 30


def _on_vacation(db: Session, ids: list[int], today: date) -> set[int]:
    return set(db.scalars(select(Request.requester_id).where(
        Request.requester_id.in_(ids), Request.type == "vacation", Request.status == "approved",
        Request.start_date <= today, Request.end_date >= today)))


def _in_meeting(db: Session, ids: list[int], now: datetime) -> set[int]:
    since = now - timedelta(seconds=IN_MEETING_SECONDS)
    return set(db.scalars(select(MeetingPresence.user_id).where(MeetingPresence.user_id.in_(ids),
                                                                MeetingPresence.seen_at >= since)))


def _busy_by_calendar(db: Session, ids: list[int], now: datetime) -> set[int]:
    """People with a planned meeting right now (as organizer or invitee who did not decline)."""
    invited = select(MeetingInvitee.meeting_id).where(MeetingInvitee.user_id.in_(ids), MeetingInvitee.response != "declined")
    meetings = db.scalars(select(Meeting).where(
        Meeting.kind == "scheduled", Meeting.cancelled.is_(False), Meeting.starts_at <= now,
        or_(Meeting.organizer_id.in_(ids), Meeting.id.in_(invited)),
        or_(Meeting.recurrence != "", Meeting.ends_at > now),
    ))
    busy: set[int] = set()
    for m in meetings:
        if not occurrences(m, now, now + timedelta(seconds=1)):
            continue
        people = {i.user_id for i in m.invitees if i.response != "declined"}
        if m.organizer_id:
            people.add(m.organizer_id)
        busy |= people & set(ids)
    return busy


def states(db: Session, ids: list[int]) -> dict[int, dict]:
    """{user id: {"state": ..., "text": ...}} for many people at once."""
    users = list(db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))))
    if not users:
        return {}
    now = utcnow()
    all_ids = [u.id for u in users]
    vacation = _on_vacation(db, all_ids, date.today())
    meeting = _in_meeting(db, all_ids, now)
    calendar = _busy_by_calendar(db, all_ids, now)
    out = {}
    for u in users:
        online = u.last_seen_at is not None and (now - u.last_seen_at).total_seconds() < ONLINE_SECONDS
        if u.presence == "offline" or not online:
            state = "ooo" if u.id in vacation else "offline"
        elif u.presence != "auto":
            state = u.presence
        elif u.id in meeting:
            state = "in_meeting"
        elif u.id in calendar:
            state = "busy"
        elif u.id in vacation:
            state = "ooo"
        elif u.idle:
            state = "away"
        else:
            state = "available"
        out[u.id] = {"state": state, "text": u.status_text, "manual": u.presence}
    return out


def state_of(db: Session, user: User) -> dict:
    return states(db, [user.id]).get(user.id, {"state": "offline", "text": "", "manual": "auto"})
