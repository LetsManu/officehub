"""Video meetings: planned meetings, the standing room of each space, calls from the chat and guests.

This API decides who may join and hands out the connection details (built in, or the company's own Jitsi
server when it runs). It is the same for the web page and for later desktop or phone apps.
"""

import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import or_, select

from ..deps import DB, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import (
    Channel,
    ChannelMember,
    Meeting,
    MeetingGuest,
    MeetingInvitee,
    MeetingPresence,
    Message,
    Space,
    SpaceMember,
    User,
    WikiPage,
    WikiRevision,
    utcnow,
)
from ..schemas import UserBrief, UtcDateTime
from ..services.meetings import (
    connect,
    expire_rings,
    get_meeting,
    ics,
    is_host,
    is_moderator,
    mark_present,
    mode,
    new_room,
    participants,
    when_text,
)
from ..services.notifications import notify
from ..services.recurrence import next_occurrence, skipped_days
from .chat import direct_channel
from ..services.spaces import get_space

router = APIRouter(tags=["meetings"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
GuestName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class Person(BaseModel):
    person: UserBrief
    response: str


class Participant(BaseModel):
    id: int | None
    name: str
    guest: bool


class WaitingGuest(BaseModel):
    id: int
    name: str
    since: UtcDateTime


class MeetingOut(BaseModel):
    id: int
    kind: str
    title: str
    description: str
    starts_at: UtcDateTime | None  # the first meeting of a series
    ends_at: UtcDateTime | None
    recurrence: str = ""
    recurrence_until: date | None = None
    next_start: UtcDateTime | None = None  # series: the next meeting that has not ended yet
    next_end: UtcDateTime | None = None
    space_id: int | None
    space_name: str | None
    organizer: UserBrief | None
    invitees: list[Person]
    my_response: str | None
    is_organizer: bool
    guest_link: str | None
    live: list[Participant]
    cancelled: bool
    town_hall: bool = False
    is_moderator: bool = False
    e2ee: bool = False
    e2ee_forced: bool = False  # the organizer's meetings are always encrypted (set by HR / Admin)


class MeetingDetail(MeetingOut):
    notes: str
    notes_version: int
    waiting: list[WaitingGuest]


class MeetingIn(BaseModel):
    title: Title
    description: Text = ""
    starts_at: datetime
    ends_at: datetime
    invitee_ids: list[int] = []
    space_id: int | None = None
    allow_guests: bool = False
    recurrence: Literal["", "daily", "weekdays", "weekly", "biweekly", "monthly"] = ""
    recurrence_until: date | None = None
    town_hall: bool = False
    e2ee: bool = False


class RespondIn(BaseModel):
    response: str


class NotesIn(BaseModel):
    notes: Annotated[str, StringConstraints(max_length=100_000)]
    base_version: int


class CallIn(BaseModel):
    channel_id: int | None = None
    user_id: int | None = None  # call a person directly (uses your conversation with them)


class Ringing(BaseModel):
    meeting_id: int
    caller: UserBrief | None
    title: str
    started: UtcDateTime


class CallState(BaseModel):
    meeting_id: int
    status: str  # ringing, active, declined, missed, ended
    people: list[Person]


class Join(BaseModel):
    meeting_id: int
    title: str
    connection: dict


class Presence(BaseModel):
    live: list[Participant]
    waiting: list[WaitingGuest]
    ended: bool


class GuestInfo(BaseModel):
    title: str
    organizer: str | None
    starts_at: UtcDateTime | None


class GuestRequestIn(BaseModel):
    name: GuestName


class GuestStatus(BaseModel):
    status: str  # waiting, admitted, denied
    secret: str
    join: Join | None = None


# ---------- helpers ----------


def _field_error(field: str, code: str, message: str) -> ApiError:
    error = ApiError(422, code, message)
    error.field = field  # type: ignore[attr-defined]
    return error


def _live(db: DB, meeting: Meeting) -> list[Participant]:
    out = []
    for p in participants(db, meeting):
        if p.user is not None:
            out.append(Participant(id=p.user.id, name=p.user.full_name, guest=False))
        elif p.guest_id is not None:
            guest = db.get(MeetingGuest, p.guest_id)
            if guest is not None:
                out.append(Participant(id=None, name=guest.name, guest=True))
    return out


def _waiting(db: DB, meeting: Meeting) -> list[WaitingGuest]:
    since = utcnow() - timedelta(minutes=10)
    rows = db.scalars(select(MeetingGuest).where(MeetingGuest.meeting_id == meeting.id, MeetingGuest.status == "waiting",
                                                 MeetingGuest.created_at >= since).order_by(MeetingGuest.id))
    return [WaitingGuest(id=g.id, name=g.name, since=g.created_at) for g in rows]


def _out(db: DB, user: User, meeting: Meeting, cls=MeetingOut, **extra) -> MeetingOut:
    space = db.get(Space, meeting.space_id) if meeting.space_id else None
    mine = next((i.response for i in meeting.invitees if i.user_id == user.id), None)
    upcoming = next_occurrence(meeting, utcnow()) if meeting.recurrence and meeting.starts_at else None
    return cls(
        id=meeting.id, kind=meeting.kind, title=meeting.title, description=meeting.description,
        starts_at=meeting.starts_at, ends_at=meeting.ends_at, space_id=meeting.space_id,
        recurrence=meeting.recurrence or "", recurrence_until=meeting.recurrence_until,
        next_start=upcoming[0] if upcoming else None, next_end=upcoming[1] if upcoming else None,
        space_name=space.name if space else None,
        organizer=UserBrief.model_validate(meeting.organizer) if meeting.organizer else None,
        invitees=[Person(person=UserBrief.model_validate(i.user), response=i.response)
                  for i in sorted(meeting.invitees, key=lambda i: i.user.last_name)],
        my_response=mine, is_organizer=meeting.organizer_id == user.id,
        guest_link=f"/guest/{meeting.guest_token}" if meeting.guest_token and is_host(user, meeting) else None,
        live=_live(db, meeting), cancelled=meeting.cancelled, town_hall=meeting.town_hall,
        is_moderator=is_moderator(user, meeting), e2ee=meeting.e2ee,
        e2ee_forced=bool(meeting.organizer and meeting.organizer.e2ee_required), **extra,
    )


def _detail(db: DB, user: User, meeting: Meeting) -> MeetingDetail:
    return _out(db, user, meeting, MeetingDetail, notes=meeting.notes, notes_version=meeting.notes_version,
                waiting=_waiting(db, meeting) if is_host(user, meeting) else [])


def _check_times(body: MeetingIn) -> None:
    if body.ends_at <= body.starts_at:
        raise _field_error("ends_at", "end_before_start_time", "The end must be after the start.")
    if body.ends_at - body.starts_at > timedelta(hours=12):
        raise _field_error("ends_at", "meeting_too_long", "A meeting can be at most 12 hours long.")
    if body.recurrence and body.recurrence_until and body.recurrence_until < body.starts_at.date():
        raise _field_error("recurrence_until", "end_before_start", "The series must end after it starts.")


def _naive_utc(value: datetime) -> datetime:
    """Times are stored as UTC without a time zone (like everywhere else)."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


def _invite(db: DB, user: User, meeting: Meeting, ids: set[int]) -> None:
    for person in db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))):
        meeting.invitees.append(MeetingInvitee(user_id=person.id, response="pending"))
        notify(db, person.id, "meeting_invite",
               {"name": user.full_name, "title": meeting.title, "when": when_text(meeting, person.language)},
               link=f"/meetings/{meeting.id}", attachment=("einladung.ics", ics(meeting), "text/calendar"))


def _join(db: DB, user: User, meeting: Meeting) -> Join:
    if meeting.cancelled:
        raise ApiError(409, "meeting_cancelled", "This meeting has been cancelled.")
    mark_present(db, meeting, user_id=user.id)
    for ring in meeting.invitees:
        if ring.user_id == user.id and ring.response in ("ringing", "pending", "missed"):
            ring.response = "accepted"
    db.commit()
    return Join(meeting_id=meeting.id, title=meeting.title, connection=connect(db, meeting, user.full_name, str(user.id), True, is_moderator(user, meeting)))


# ---------- config ----------


@router.get("/api/meetings/config")
def config(user: CurrentUser) -> dict:
    return {"enabled": True, "mode": mode()}


# ---------- planned meetings ----------


@router.get("/api/meetings", response_model=list[MeetingOut])
def list_meetings(user: CurrentUser, db: DB, past: bool = False) -> list[MeetingOut]:
    now = utcnow()
    query = select(Meeting).where(
        Meeting.kind == "scheduled",
        or_(Meeting.organizer_id == user.id,
            Meeting.id.in_(select(MeetingInvitee.meeting_id).where(MeetingInvitee.user_id == user.id))),
    )
    soon = now - timedelta(minutes=30)
    if past:
        query = query.where(Meeting.ends_at < now).order_by(Meeting.starts_at.desc()).limit(80)
        return [_out(db, user, m) for m in db.scalars(query) if not m.recurrence or not next_occurrence(m, now)][:50]
    query = query.where(or_(Meeting.ends_at >= soon, Meeting.recurrence != ""))
    items = [_out(db, user, m) for m in db.scalars(query)]
    items = [m for m in items if not m.recurrence or m.next_start]  # a finished series is in the past
    return sorted(items, key=lambda m: m.next_start or m.starts_at)


@router.post("/api/meetings", response_model=MeetingDetail, status_code=201)
def create_meeting(body: MeetingIn, user: CurrentUser, db: DB) -> MeetingDetail:
    _check_times(body)
    if body.space_id is not None:
        get_space(db, user, body.space_id, write=True)
    meeting = Meeting(kind="scheduled", title=body.title, description=body.description, room=new_room("m"),
                      starts_at=_naive_utc(body.starts_at), ends_at=_naive_utc(body.ends_at), space_id=body.space_id,
                      organizer_id=user.id, guest_token=secrets.token_urlsafe(18) if body.allow_guests else None,
                      recurrence=body.recurrence, recurrence_until=body.recurrence_until if body.recurrence else None,
                      town_hall=body.town_hall, e2ee=body.e2ee or user.e2ee_required)
    db.add(meeting)
    db.flush()
    _invite(db, user, meeting, set(body.invitee_ids) - {user.id})
    db.commit()
    return _detail(db, user, meeting)


@router.get("/api/meetings/{meeting_id}", response_model=MeetingDetail)
def meeting_detail(meeting_id: int, user: CurrentUser, db: DB) -> MeetingDetail:
    return _detail(db, user, get_meeting(db, user, meeting_id))


@router.put("/api/meetings/{meeting_id}", response_model=MeetingDetail)
def update_meeting(meeting_id: int, body: MeetingIn, user: CurrentUser, db: DB) -> MeetingDetail:
    meeting = get_meeting(db, user, meeting_id)
    if meeting.organizer_id != user.id:
        raise forbidden("Only the organizer can change the meeting.")
    _check_times(body)
    meeting.title, meeting.description = body.title, body.description
    meeting.starts_at, meeting.ends_at = _naive_utc(body.starts_at), _naive_utc(body.ends_at)
    meeting.recurrence = body.recurrence
    meeting.town_hall = body.town_hall
    meeting.e2ee = body.e2ee or user.e2ee_required
    meeting.recurrence_until = body.recurrence_until if body.recurrence else None
    if body.allow_guests and not meeting.guest_token:
        meeting.guest_token = secrets.token_urlsafe(18)
    if not body.allow_guests:
        meeting.guest_token = None
    current = {i.user_id for i in meeting.invitees}
    wanted = set(body.invitee_ids) - {user.id}
    meeting.invitees = [i for i in meeting.invitees if i.user_id in wanted]
    _invite(db, user, meeting, wanted - current)
    db.commit()
    return _detail(db, user, meeting)


@router.delete("/api/meetings/{meeting_id}", status_code=204)
def cancel_meeting(meeting_id: int, user: CurrentUser, db: DB, occurrence: date | None = Query(None)) -> None:
    """Cancel the meeting – or, for a series, only the meeting on one day (local date)."""
    meeting = get_meeting(db, user, meeting_id)
    if meeting.organizer_id != user.id or meeting.kind != "scheduled":
        raise forbidden("Only the organizer can cancel the meeting.")
    if occurrence is not None and meeting.recurrence:
        meeting.skipped = ",".join(sorted(skipped_days(meeting) | {occurrence.isoformat()}))
        day = occurrence.strftime("%d.%m.%Y")
        for i in meeting.invitees:
            notify(db, i.user_id, "meeting_cancelled", {"name": user.full_name, "title": meeting.title, "when": day},
                   link=f"/meetings/{meeting.id}")
        db.commit()
        return
    meeting.cancelled = True
    for i in meeting.invitees:
        person = db.get(User, i.user_id)
        notify(db, i.user_id, "meeting_cancelled",
               {"name": user.full_name, "title": meeting.title, "when": when_text(meeting, person.language if person else "de")},
               link=f"/meetings/{meeting.id}", attachment=("absage.ics", ics(meeting, "CANCEL"), "text/calendar"))
    db.commit()


@router.post("/api/meetings/{meeting_id}/respond", response_model=MeetingDetail)
def respond(meeting_id: int, body: RespondIn, user: CurrentUser, db: DB) -> MeetingDetail:
    meeting = get_meeting(db, user, meeting_id)
    invite = next((i for i in meeting.invitees if i.user_id == user.id), None)
    if invite is None or body.response not in ("accepted", "declined"):
        raise ApiError(422, "invalid_choice", "Please accept or decline.")
    invite.response = body.response
    db.commit()
    return _detail(db, user, meeting)


@router.get("/api/meetings/{meeting_id}/ics")
def meeting_ics(meeting_id: int, user: CurrentUser, db: DB) -> Response:
    meeting = get_meeting(db, user, meeting_id)
    if meeting.starts_at is None:
        raise not_found("Meeting")
    return Response(ics(meeting, "PUBLISH"), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="meeting-{meeting.id}.ics"'})


# ---------- joining, presence, notes ----------


@router.post("/api/meetings/{meeting_id}/join", response_model=Join)
def join(meeting_id: int, user: CurrentUser, db: DB) -> Join:
    return _join(db, user, get_meeting(db, user, meeting_id))


@router.post("/api/meetings/{meeting_id}/presence", response_model=Presence)
def presence(meeting_id: int, user: CurrentUser, db: DB) -> Presence:
    meeting = get_meeting(db, user, meeting_id)
    mark_present(db, meeting, user_id=user.id)
    db.commit()
    return Presence(live=_live(db, meeting), waiting=_waiting(db, meeting) if is_host(user, meeting) else [],
                    ended=meeting.ended_at is not None)


@router.delete("/api/meetings/{meeting_id}/presence", status_code=204)
def leave(meeting_id: int, user: CurrentUser, db: DB) -> None:
    meeting = get_meeting(db, user, meeting_id)
    for row in db.scalars(select(MeetingPresence).where(MeetingPresence.meeting_id == meeting.id,
                                                        MeetingPresence.user_id == user.id)):
        db.delete(row)
    db.flush()
    if meeting.kind == "call" and not participants(db, meeting):
        meeting.ended_at = utcnow()
        for ring in meeting.invitees:
            if ring.response == "ringing":
                ring.response = "missed"
    db.commit()


@router.put("/api/meetings/{meeting_id}/notes", response_model=MeetingDetail)
def save_notes(meeting_id: int, body: NotesIn, user: CurrentUser, db: DB) -> MeetingDetail:
    meeting = get_meeting(db, user, meeting_id)
    if body.base_version != meeting.notes_version:
        raise ApiError(409, "notes_conflict", "Someone saved the notes in the meantime.")
    meeting.notes, meeting.notes_version = body.notes, meeting.notes_version + 1
    db.commit()
    return _detail(db, user, meeting)


@router.post("/api/meetings/{meeting_id}/notes-to-wiki", response_model=dict)
def notes_to_wiki(meeting_id: int, user: CurrentUser, db: DB, space_id: int | None = Query(None)) -> dict:
    """Keep the meeting notes as a wiki page in the meeting's space (or a space you choose)."""
    meeting = get_meeting(db, user, meeting_id)
    target = space_id or meeting.space_id
    if target is None:
        raise _field_error("space_id", "space_required", "Please choose a space.")
    space = get_space(db, user, target, write=True)
    date = (meeting.starts_at or meeting.created_at).strftime("%Y-%m-%d")
    title = f"{meeting.title} – {date}"[:150]
    page = WikiPage(space_id=space.id, title=title, body=meeting.notes or "", updated_by_id=user.id)
    db.add(page)
    db.flush()
    db.add(WikiRevision(page_id=page.id, version=1, title=title, body=page.body, author_id=user.id))
    db.commit()
    return {"space_id": space.id, "page_id": page.id}


# ---------- guests ----------


@router.post("/api/meetings/{meeting_id}/guests/{guest_id}/{decision}", response_model=Presence)
def decide_guest(meeting_id: int, guest_id: int, decision: str, user: CurrentUser, db: DB) -> Presence:
    meeting = get_meeting(db, user, meeting_id)
    if not is_host(user, meeting):
        raise forbidden()
    guest = db.get(MeetingGuest, guest_id)
    if guest is None or guest.meeting_id != meeting.id or decision not in ("admit", "deny"):
        raise not_found("Guest")
    guest.status, guest.decided_by_id = ("admitted" if decision == "admit" else "denied"), user.id
    db.commit()
    return presence(meeting_id, user, db)


def _guest_meeting(db: DB, token: str) -> Meeting:
    meeting = db.scalar(select(Meeting).where(Meeting.guest_token == token))
    if meeting is None or meeting.cancelled:
        raise not_found("Meeting")
    return meeting


@router.get("/api/guest/{token}", response_model=GuestInfo)
def guest_info(token: str, db: DB) -> GuestInfo:
    meeting = _guest_meeting(db, token)
    return GuestInfo(title=meeting.title, organizer=meeting.organizer.full_name if meeting.organizer else None,
                     starts_at=meeting.starts_at)


@router.post("/api/guest/{token}/request", response_model=GuestStatus, status_code=201)
def guest_request(token: str, body: GuestRequestIn, db: DB) -> GuestStatus:
    meeting = _guest_meeting(db, token)
    recent = utcnow() - timedelta(minutes=10)
    waiting = db.scalars(select(MeetingGuest.id).where(MeetingGuest.meeting_id == meeting.id,
                                                       MeetingGuest.status == "waiting", MeetingGuest.created_at >= recent)).all()
    if len(waiting) >= 20:
        raise ApiError(429, "too_many_guests", "Too many people are waiting. Please try again later.")
    guest = MeetingGuest(meeting_id=meeting.id, name=body.name, secret=secrets.token_urlsafe(24))
    db.add(guest)
    db.commit()
    return GuestStatus(status="waiting", secret=guest.secret)


@router.get("/api/guest/status/{secret}", response_model=GuestStatus)
def guest_status(secret: str, db: DB) -> GuestStatus:
    guest = db.scalar(select(MeetingGuest).where(MeetingGuest.secret == secret))
    if guest is None:
        raise not_found("Guest")
    meeting = db.get(Meeting, guest.meeting_id)
    if meeting is None or meeting.cancelled:
        raise not_found("Meeting")
    join_info = None
    if guest.status == "admitted":
        mark_present(db, meeting, guest_id=guest.id)
        db.commit()
        name = f"{guest.name} (Gast)" if meeting.organizer and meeting.organizer.language == "de" else f"{guest.name} (guest)"
        join_info = Join(meeting_id=meeting.id, title=meeting.title, connection=connect(db, meeting, name, f"guest-{guest.id}", False))
    return GuestStatus(status=guest.status, secret=guest.secret, join=join_info)


# ---------- the standing room of a space ----------


@router.get("/api/spaces/{space_id}/meeting", response_model=MeetingOut)
def space_room(space_id: int, user: CurrentUser, db: DB) -> MeetingOut:
    space = get_space(db, user, space_id)
    if db.scalar(select(SpaceMember.id).where(SpaceMember.space_id == space.id, SpaceMember.user_id == user.id)) is None:
        raise forbidden("Only members of this space can join its meeting room.")
    meeting = db.scalar(select(Meeting).where(Meeting.kind == "space", Meeting.space_id == space.id))
    if meeting is None:
        meeting = Meeting(kind="space", title=space.name, room=new_room("s"), space_id=space.id, organizer_id=user.id)
        db.add(meeting)
        db.commit()
    return _out(db, user, meeting)


# ---------- calls from the chat ----------


@router.post("/api/calls", response_model=Join, status_code=201)
def start_call(body: CallIn, user: CurrentUser, db: DB) -> Join:
    """Start a call in a chat: a direct conversation rings the other person, a channel posts a "join" message."""
    if body.user_id is not None:
        channel = direct_channel(db, user, body.user_id)
    elif body.channel_id is not None:
        channel = db.get(Channel, body.channel_id)
    else:
        channel = None
    if channel is None:
        raise not_found("Conversation")
    if channel.space_id is not None:
        member = db.scalar(select(SpaceMember.id).where(SpaceMember.space_id == channel.space_id, SpaceMember.user_id == user.id))
        if member is None:
            raise not_found("Conversation")
        others: list[int] = []
        title = f"# {channel.name}"
    else:
        ids = set(db.scalars(select(ChannelMember.user_id).where(ChannelMember.channel_id == channel.id)))
        if user.id not in ids:
            raise not_found("Conversation")
        others = sorted(ids - {user.id})
        title = user.full_name
    # A call is end-to-end encrypted when anyone it rings must have that (set by HR / Admin)
    required = user.e2ee_required or any(u.e2ee_required for u in db.scalars(select(User).where(User.id.in_(others))))
    meeting = Meeting(kind="call", title=title, room=new_room("c"), space_id=channel.space_id, channel_id=channel.id,
                      organizer_id=user.id, e2ee=required)
    db.add(meeting)
    db.flush()
    for uid in others:
        meeting.invitees.append(MeetingInvitee(user_id=uid, response="ringing"))
    db.add(Message(channel_id=channel.id, author_id=user.id, body="", meeting_id=meeting.id))
    db.commit()
    return _join(db, user, meeting)


@router.get("/api/calls/incoming", response_model=list[Ringing])
def incoming(user: CurrentUser, db: DB) -> list[Ringing]:
    """Polled every few seconds by the open portal (and later the apps) so a call can ring."""
    for missed in expire_rings(db, user.id):
        meeting = db.get(Meeting, missed.meeting_id)
        caller = meeting.organizer
        notify(db, user.id, "call_missed", {"name": caller.full_name if caller else ""},
               link=f"/chat/{meeting.channel_id}" if meeting.channel_id else "/chat")
    db.commit()
    rows = db.execute(select(MeetingInvitee, Meeting).join(Meeting).where(
        MeetingInvitee.user_id == user.id, MeetingInvitee.response == "ringing", Meeting.kind == "call",
        Meeting.ended_at.is_(None))).all()
    return [Ringing(meeting_id=m.id, caller=UserBrief.model_validate(m.organizer) if m.organizer else None,
                    title=m.title, started=m.created_at) for _ring, m in rows]


@router.post("/api/calls/{meeting_id}/decline", status_code=204)
def decline(meeting_id: int, user: CurrentUser, db: DB) -> None:
    meeting = get_meeting(db, user, meeting_id)
    for ring in meeting.invitees:
        if ring.user_id == user.id and ring.response == "ringing":
            ring.response = "declined"
    db.commit()


@router.get("/api/calls/{meeting_id}", response_model=CallState)
def call_state(meeting_id: int, user: CurrentUser, db: DB) -> CallState:
    meeting = get_meeting(db, user, meeting_id)
    if meeting.kind != "call":
        raise not_found("Call")
    expire_rings(db)
    db.commit()
    responses = {i.response for i in meeting.invitees}
    if meeting.ended_at is not None:
        status = "ended"
    elif "accepted" in responses or not meeting.invitees:
        status = "active"
    elif "ringing" in responses:
        status = "ringing"
    elif responses == {"declined"}:
        status = "declined"
    else:
        status = "missed"
    return CallState(meeting_id=meeting.id, status=status,
                     people=[Person(person=UserBrief.model_validate(i.user), response=i.response) for i in meeting.invitees])

