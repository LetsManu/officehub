"""Video meetings with the company's own Jitsi Meet server.

OfficeHub decides who may join which conference and hands out a short-lived JWT for exactly that
conference. The Jitsi server (Prosody) checks the token with the shared secret. Meetings never use
an outside service.
"""

import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..errors import ApiError, not_found
from ..models import Channel, ChannelMember, Meeting, MeetingInvitee, MeetingPresence, SpaceMember, User, utcnow
from .office import jwt_encode

TOKEN_HOURS = 6
PRESENCE_SECONDS = 25  # the meeting page reports every 10 seconds
RING_SECONDS = 45  # an unanswered call counts as missed after this


def enabled() -> bool:
    return bool(settings.jitsi_app_secret)


def require_enabled() -> None:
    if not enabled():
        raise ApiError(409, "meetings_unavailable", "Video meetings are not set up.")


def new_room(prefix: str) -> str:
    """Conference names are lower case; the random part keeps rooms unguessable."""
    return f"{prefix}-{secrets.token_hex(8)}"


def jitsi_token(room: str, name: str, user_id: str, moderator: bool, avatar: str = "") -> str:
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
    }
    return jwt_encode(payload, settings.jitsi_app_secret or "")


def connection_info(room: str, token: str, name: str) -> dict:
    """Everything a client needs to join: the web page here, and later the desktop or Android app."""
    return {
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
        f"SEQUENCE:{int(time.time()) // 60}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode()


def when_text(meeting: Meeting, language: str) -> str:
    if meeting.starts_at is None:
        return ""
    local = meeting.starts_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.timezone))
    return local.strftime("%d.%m.%Y, %H:%M") if language == "de" else local.strftime("%Y-%m-%d %H:%M")
