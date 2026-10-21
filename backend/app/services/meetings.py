"""Video meetings without any outside service.

Two ways, chosen automatically:
- built in (always available): OfficeHub introduces the browsers to each other (see services/rtc.py) and
  audio and video go directly between them. Good for calls and small meetings.
- the company's own Jitsi Meet server, when it runs in the stack: better for larger meetings. OfficeHub
  hands out a short-lived JWT for exactly one conference; Prosody checks it with the shared secret.
"""

import secrets
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..errors import ApiError, not_found
from ..models import (
    Channel,
    ChannelMember,
    Meeting,
    MeetingInvitee,
    MeetingPresence,
    MeetingReminder,
    SpaceMember,
    User,
    utcnow,
)
from .notifications import notify
from .office import jwt_decode, jwt_encode
from . import rtc
from .probe import reachable
from .recurrence import occurrences, rrule, skipped_days
from .settings import get_setting, set_setting

TOKEN_HOURS = 6
REMINDER_MINUTES = 10
PRESENCE_SECONDS = 25  # the meeting page reports every 10 seconds
RING_SECONDS = 45  # an unanswered call counts as missed after this


BUILTIN_MAX = 8  # people per meeting without a Jitsi server: everyone sends their video to everyone
BUILTIN_TOWN_HALL_MAX = 30  # in a town hall only the few people on stage send


def jitsi_running() -> bool:
    return bool(settings.jitsi_app_secret and settings.jitsi_internal_url
                and reachable(f"{settings.jitsi_internal_url}/libs/lib-jitsi-meet.min.js"))


def mode() -> str:
    """'jitsi' when the company's Jitsi server is running, otherwise 'builtin'."""
    return "jitsi" if jitsi_running() else "builtin"


def new_room(prefix: str) -> str:
    """Conference names are lower case; the random part keeps rooms unguessable."""
    return f"{prefix}-{secrets.token_hex(8)}"


def jitsi_token(room: str, name: str, user_id: str, moderator: bool, avatar: str = "", main: str = "", mod: bool = False) -> str:
    now = int(time.time())
    user = {"id": user_id, "name": name}
    if avatar:
        user["avatar"] = avatar
    payload = {
        "aud": settings.jitsi_app_id,
        "iss": settings.jitsi_app_id,
        "sub": settings.jitsi_domain,
        "room": room,
        "nbf": now - 10,
        "exp": now + TOKEN_HOURS * 3600,
        "context": {"user": user},
        "moderator": moderator,
        # OfficeHub's own claims (Prosody ignores them): the meeting this room belongs to (breakout rooms), who
        # this is and whether they lead the meeting
        "main": main or room,
        "who": user_id,
        "name": name,
        "mod": mod,
    }
    return jwt_encode(payload, settings.jitsi_app_secret or "")


def rtc_token(db: Session, room: str, name: str, who: str, host: bool, main: str = "", mod: bool = False,
              max_people: int = BUILTIN_MAX) -> str:
    """Admission to one built-in meeting room, valid for the same time as a Jitsi token."""
    payload = {"room": room, "main": main or room, "name": name, "who": who, "host": host, "mod": mod,
               "max": max_people, "exp": int(time.time()) + TOKEN_HOURS * 3600}
    return jwt_encode(payload, rtc_key(db))


def ticket(db: Session, token: str) -> dict:
    """Read a room token of either kind (built in or Jitsi) as {room, main, who, name, host, mod}."""
    try:
        data = jwt_decode(token, rtc_key(db))
    except ApiError:
        if not settings.jitsi_app_secret:
            raise
        data = jwt_decode(token, settings.jitsi_app_secret)
        data = {"room": data.get("room"), "main": data.get("main"), "who": data.get("who"), "name": data.get("name"),
                "host": bool(data.get("moderator")), "mod": bool(data.get("mod"))}
    if not all(data.get(k) for k in ("room", "main", "who", "name")):
        raise ApiError(401, "invalid_token", "Invalid token.")
    return data


def rtc_key(db: Session) -> str:
    key = get_setting(db, "rtc_key", None)
    if not key:
        key = secrets.token_urlsafe(48)
        set_setting(db, "rtc_key", key)
        db.commit()
    return key


def ice_servers() -> list[dict]:
    """No outside STUN servers: inside the office network browsers find each other directly."""
    if not settings.ice_servers:
        return []
    server: dict = {"urls": list(settings.ice_servers)}
    if settings.ice_username:
        server.update(username=settings.ice_username, credential=settings.ice_password or "")
    return [server]


def is_moderator(user: User | None, meeting: Meeting) -> bool:
    """Who leads the meeting (mute everyone, remove people, breakout rooms, town hall stage): the organizer of a
    planned meeting; in space rooms and calls everyone with an account."""
    if user is None:
        return False
    return meeting.organizer_id == user.id or meeting.kind != "scheduled"


def connect(db: Session, meeting: Meeting, name: str, who: str, host: bool, mod: bool = False) -> dict:
    """Everything a client needs to join: the web page here, and later the desktop or Android app."""
    info = connect_room(db, meeting.room, meeting.room, name, who, host, mod, meeting.town_hall)
    info["town_hall"] = meeting.town_hall
    return info


def connect_room(db: Session, room: str, main: str, name: str, who: str, host: bool, mod: bool,
                 town_hall: bool = False) -> dict:
    """Connection details for one room: the meeting itself or one of its breakout rooms."""
    roles = {"who": who, "moderator": mod}
    # While the Jitsi server runs, every meeting and call goes through it. Only a meeting that already runs built in
    # (the server was started in the meantime) stays that way until it is empty, so nobody ends up in another room.
    if mode() == "jitsi" and not rtc.count(room):
        token = jitsi_token(room, name, who, moderator=host, main=main, mod=mod)
        return connection_info(room, token, name) | roles
    max_people = BUILTIN_TOWN_HALL_MAX if town_hall else BUILTIN_MAX
    return {
        "mode": "builtin",
        "room": room,
        "token": rtc_token(db, room, name, who, host, main=main, mod=mod, max_people=max_people),
        "display_name": name,
        "signal": "/api/rtc",
        "ice_servers": ice_servers(),
        "max_people": max_people,
    } | roles


def connection_info(room: str, token: str, name: str) -> dict:
    return {
        "mode": "jitsi",
        "room": room,
        "token": token,
        "display_name": name,
        "domain": settings.jitsi_domain,
        "muc": settings.jitsi_muc,
        "websocket": "/jitsi/xmpp-websocket",
        "library": "/jitsi/libs/lib-jitsi-meet.min.js",
    }


def can_join(db: Session, user: User, meeting: Meeting) -> bool:
    if meeting.organizer_id == user.id:
        return True
    if any(i.user_id == user.id for i in meeting.invitees):
        return True
    if meeting.space_id is not None:
        member = db.scalar(select(SpaceMember.id).where(SpaceMember.space_id == meeting.space_id, SpaceMember.user_id == user.id))
        if member is not None:
            return True
    if meeting.channel_id is not None:
        channel = db.get(Channel, meeting.channel_id)
        if channel is not None and channel.space_id is None:
            return db.scalar(select(ChannelMember.id).where(ChannelMember.channel_id == channel.id,
                                                            ChannelMember.user_id == user.id)) is not None
    return False


def get_meeting(db: Session, user: User, meeting_id: int) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or not can_join(db, user, meeting):
        raise not_found("Meeting")
    return meeting


def is_host(user: User, meeting: Meeting) -> bool:
    """Organizer, or anyone invited/in the space for space rooms and calls (they let guests in)."""
    return meeting.organizer_id == user.id or meeting.kind != "scheduled" or any(
        i.user_id == user.id and i.response != "declined" for i in meeting.invitees)


def participants(db: Session, meeting: Meeting) -> list[MeetingPresence]:
    since = utcnow() - timedelta(seconds=PRESENCE_SECONDS)
    return list(db.scalars(select(MeetingPresence).where(MeetingPresence.meeting_id == meeting.id,
                                                         MeetingPresence.seen_at >= since)))


def mark_present(db: Session, meeting: Meeting, user_id: int | None = None, guest_id: int | None = None) -> None:
    query = select(MeetingPresence).where(MeetingPresence.meeting_id == meeting.id)
    query = query.where(MeetingPresence.user_id == user_id) if user_id else query.where(MeetingPresence.guest_id == guest_id)
    row = db.scalar(query)
    if row is None:
        db.add(MeetingPresence(meeting_id=meeting.id, user_id=user_id, guest_id=guest_id))
    else:
        row.seen_at = utcnow()


def expire_rings(db: Session, user_id: int | None = None) -> list[MeetingInvitee]:
    """Calls nobody answered in time become missed calls. Returns the newly missed ones."""
    limit = utcnow() - timedelta(seconds=RING_SECONDS)
    query = select(MeetingInvitee).join(Meeting).where(
        Meeting.kind == "call", MeetingInvitee.response == "ringing", Meeting.created_at < limit)
    if user_id is not None:
        query = query.where(MeetingInvitee.user_id == user_id)
    missed = list(db.scalars(query))
    for ring in missed:
        ring.response = "missed"
    return missed


def ics(meeting: Meeting, method: str = "REQUEST") -> bytes:
    """A calendar invitation for Outlook, Thunderbird, phones …"""

    def text(value: str) -> str:
        for char, escaped in (("\\", "\\\\"), (";", "\\;"), (",", "\\,"), ("\n", "\\n")):
            value = value.replace(char, escaped)
        return value

    def stamp(value: datetime) -> str:
        return value.replace(tzinfo=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    link = f"{settings.portal_url}/meetings/{meeting.id}"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OfficeHub//Meetings//DE", f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:meeting-{meeting.id}@officehub",
        f"DTSTAMP:{stamp(utcnow())}",
        f"DTSTART:{stamp(meeting.starts_at)}",
        f"DTEND:{stamp(meeting.ends_at or meeting.starts_at + timedelta(hours=1))}",
        f"SUMMARY:{text(meeting.title)}",
        f"DESCRIPTION:{text((meeting.description + chr(10) + chr(10) if meeting.description else '') + link)}",
        f"URL:{link}",
        f"LOCATION:{text(link)}",
        f"STATUS:{'CANCELLED' if meeting.cancelled else 'CONFIRMED'}",
        *([rule] if (rule := rrule(meeting)) else []),
        *[f"EXDATE:{stamp(start)}" for start, _end in skipped_occurrences(meeting)],
        f"SEQUENCE:{int(time.time()) // 60}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode()


SERIES_TEXT = {
    "de": {"daily": "täglich", "weekdays": "werktags", "weekly": "wöchentlich", "biweekly": "alle 2 Wochen", "monthly": "monatlich"},
    "en": {"daily": "daily", "weekdays": "weekdays", "weekly": "weekly", "biweekly": "every 2 weeks", "monthly": "monthly"},
}


def when_text(meeting: Meeting, language: str) -> str:
    if meeting.starts_at is None:
        return ""
    local = meeting.starts_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.timezone))
    text = local.strftime("%d.%m.%Y, %H:%M") if language == "de" else local.strftime("%Y-%m-%d %H:%M")
    if meeting.recurrence:
        text += f", {SERIES_TEXT.get(language, SERIES_TEXT['en'])[meeting.recurrence]}"
    return text


def skipped_occurrences(meeting: Meeting) -> list[tuple[datetime, datetime]]:
    """The cancelled single meetings of a series, as UTC start and end (for EXDATE in calendar files)."""
    skip = skipped_days(meeting)
    if not skip or meeting.starts_at is None:
        return []
    local = meeting.starts_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.timezone))
    out = []
    for day in sorted(skip):
        start = datetime.combine(date.fromisoformat(day), local.timetz())
        start_utc = start.astimezone(timezone.utc).replace(tzinfo=None)
        out.append((start_utc, start_utc + ((meeting.ends_at or meeting.starts_at) - meeting.starts_at)))
    return out


def due_reminders(db: Session, user: User) -> list[dict]:
    """Meetings starting within 10 minutes (or just started): one notification each, and the list for the banner."""
    now = utcnow()
    since, until = now - timedelta(minutes=5), now + timedelta(minutes=REMINDER_MINUTES)
    invited = select(MeetingInvitee.meeting_id).where(MeetingInvitee.user_id == user.id,
                                                       MeetingInvitee.response != "declined")
    meetings = db.scalars(select(Meeting).where(
        Meeting.kind == "scheduled", Meeting.cancelled.is_(False), Meeting.starts_at <= until,
        or_(Meeting.organizer_id == user.id, Meeting.id.in_(invited)),
        or_(Meeting.recurrence != "", Meeting.starts_at >= since),
    ))
    out = []
    for m in meetings:
        for start, end in occurrences(m, since, until):
            if not since <= start <= until:
                continue
            out.append({"meeting_id": m.id, "title": m.title, "starts_at": start, "ends_at": end})
            sent = db.scalar(select(MeetingReminder.id).where(MeetingReminder.meeting_id == m.id,
                                                              MeetingReminder.user_id == user.id,
                                                              MeetingReminder.occurrence == start))
            if sent is None:
                db.add(MeetingReminder(meeting_id=m.id, user_id=user.id, occurrence=start))
                minutes = max(0, round((start - now).total_seconds() / 60))
                notify(db, user.id, "meeting_reminder", {"title": m.title, "minutes": minutes},
                       link=f"/meetings/{m.id}/room")
    db.commit()
    return out
