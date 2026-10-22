"""Signalling for built-in meetings (see services/rtc.py), moderation and breakout rooms. The room token from
/api/meetings/{id}/join (or the guest page) is the admission ticket, so the same endpoints serve people, guests
and later the apps."""

import time
from typing import Annotated, Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field, StringConstraints

from sqlalchemy import select

from ..db import SessionLocal
from ..deps import DB
from ..errors import ApiError, forbidden
from ..services import breakouts, keys, mls, rtc
from ..models import Meeting
from ..services.meetings import BUILTIN_MAX, connect_room, rtc_key, ticket
from ..services.office import jwt_decode

router = APIRouter(prefix="/api/rtc", tags=["meetings"])

# App messages anyone may send, and those only for people leading the meeting
APP_KINDS = {"react", "wb", "wb-clear", "wb-req", "wb-all", "rec", "sync-req"}
# In an end-to-end encrypted meeting these carry content and only travel encrypted (MLS, /mls/app)
SEALED_KINDS = {"react", "wb", "wb-clear", "wb-all"}
MOD_KINDS = {"mute", "mute-all", "spotlight", "stage", "lower-hand", "sync", "breakouts"}

_key: str | None = None  # signalling is busy: keep the key instead of asking the database each time


def _load_key() -> str:
    global _key  # noqa: PLW0603 - read once from the database
    with SessionLocal() as db:
        _key = rtc_key(db)
    return _key


def _ticket(token: str) -> dict:
    try:
        data = jwt_decode(token, _key or _load_key())
    except ApiError:
        data = jwt_decode(token, _load_key())  # the key may have been created anew (fresh database)
    if not all(k in data for k in ("room", "who", "name")):
        raise ApiError(401, "invalid_token", "Invalid token.")
    data.setdefault("main", data["room"])
    return data


def _peer(token: str, peer_id: str) -> tuple[dict, rtc.Peer]:
    ticket_data = _ticket(token)
    peer = rtc.find(ticket_data["room"], peer_id, str(ticket_data["who"]))
    if peer is None:
        raise ApiError(410, "peer_gone", "Please join again.")
    return ticket_data, peer


Token = Annotated[str, Header(alias="X-Meeting-Token", max_length=2000)]


class PeerIn(BaseModel):
    peer_id: str = Field(max_length=32)


class SendIn(PeerIn):
    to: str | None = Field(None, max_length=32)
    type: Literal["signal", "state", "chat", "app"]
    data: dict


class PollIn(PeerIn):
    after: int = 0


class RemoveIn(PeerIn):
    target: str = Field(max_length=32)


@router.post("/hello")
async def hello(token: Token) -> dict:
    t = _ticket(token)
    if rtc.is_removed(t["main"], str(t["who"])):
        raise ApiError(403, "removed_from_meeting", "You were removed from this meeting.")
    if rtc.count(t["room"]) >= int(t.get("max", BUILTIN_MAX)):
        raise ApiError(409, "meeting_full", "This meeting is full.")
    peer, others = rtc.join(t["room"], str(t["who"]), t["name"], bool(t.get("host")), bool(t.get("mod")))
    return {"peer_id": peer.id, "peers": [p.public() for p in others]}


@router.post("/send", status_code=204)
async def send(body: SendIn, token: Token) -> None:
    t, peer = _peer(token, body.peer_id)
    if len(str(body.data)) > 64_000:
        raise ApiError(413, "too_large", "Message too large.")
    if t.get("e2ee") and (body.type == "chat" or (body.type == "app" and body.data.get("kind") in SEALED_KINDS)):
        raise ApiError(422, "encrypted_only", "In this meeting, messages travel only end-to-end encrypted.")
    if body.type == "chat":
        text = str(body.data.get("text", "")).strip()[:1000]
        if not text:
            return
        body.data = {"text": text}
    if body.type == "app":
        kind = body.data.get("kind")
        if kind in MOD_KINDS and not t.get("mod"):
            raise forbidden("Only the people leading the meeting can do this.")
        if kind not in APP_KINDS | MOD_KINDS:
            raise ApiError(422, "invalid_message", "Unknown message.")
    rtc.send(t["room"], peer, body.to, body.type, body.data)


@router.post("/remove", status_code=204)
async def remove(body: RemoveIn, token: Token) -> None:
    """Remove someone from the meeting (people leading it only)."""
    t, _peer_row = _peer(token, body.peer_id)
    if not t.get("mod"):
        raise forbidden("Only the people leading the meeting can remove someone.")
    target = rtc.rooms.get(t["room"], {}).get(body.target)
    if target is None:
        return
    if target.mod:
        raise forbidden("People leading the meeting cannot be removed.")
    rtc.remove(t["main"], t["room"], body.target)
    mls.leave_who(t["room"], target.who)


@router.post("/poll")
async def poll(body: PollIn, token: Token) -> dict:
    t, peer = _peer(token, body.peer_id)
    rtc.sweep(t["room"])  # the others see that someone whose page stopped asking has left
    return {"messages": await rtc.poll(peer, body.after)}


@router.post("/bye", status_code=204)
async def bye(body: PeerIn, token: Token) -> None:
    t = _ticket(token)
    if rtc.find(t["room"], body.peer_id, str(t["who"])) is not None:
        rtc.leave(t["room"], body.peer_id)


# ---------- end-to-end encryption: MLS delivery (services/mls.py) ----------

B64 = Annotated[str, StringConstraints(max_length=mls.MAX_BYTES, pattern=r"^[A-Za-z0-9+/=_-]*$")]


class MemberIn(BaseModel):
    member_id: str = Field(max_length=32)


class PublishIn(MemberIn):
    key_package: B64


class CommitIn(MemberIn):
    epoch: int = Field(ge=0)
    message: B64
    welcome: B64 = ""
    added: list[Annotated[str, StringConstraints(max_length=32)]] = Field(default=[], max_length=500)
    removed: list[Annotated[str, StringConstraints(max_length=32)]] = Field(default=[], max_length=500)


class SealedIn(MemberIn):
    epoch: int = Field(ge=0)
    message: B64


class MlsPollIn(MemberIn):
    after: int = 0


def _member(token: str, member_id: str) -> tuple[dict, mls.Member]:
    t = _ticket(token)
    if not t.get("e2ee"):
        raise forbidden("This meeting is not end-to-end encrypted.")
    member = mls.find(t["room"], member_id, str(t["who"]))
    if member is None:
        raise ApiError(410, "peer_gone", "Please join again.")
    return t, member


@router.post("/mls/hello")
async def mls_hello(token: Token) -> dict:
    t = _ticket(token)
    if not t.get("e2ee"):
        raise forbidden("This meeting is not end-to-end encrypted.")
    if rtc.is_removed(t["main"], str(t["who"])):
        raise ApiError(403, "removed_from_meeting", "You were removed from this meeting.")
    who = str(t["who"])
    # Stays on the event loop (the groups wake each other's polls): one short read
    with SessionLocal() as db:
        if not who.isdigit() and keys.policy(db) == "strict":
            raise ApiError(403, "e2ee_guests_blocked", "This meeting is only for confirmed people.")
        # The person's device keys travel with the roster: every browser checks them itself (frontend e2ee/identity.ts)
        chain = keys.chain(db, int(who)) if who.isdigit() else []
    member, roster = mls.join(t["room"], who, t["name"], chain)
    return {"member_id": member.id, "roster": roster}


@router.post("/mls/create")
async def mls_create(body: MemberIn, token: Token) -> dict:
    t, member = _member(token, body.member_id)
    created, version = mls.create(t["room"], member)
    return {"created": created, "version": version}


@router.post("/mls/publish")
async def mls_publish(body: PublishIn, token: Token) -> dict:
    t, member = _member(token, body.member_id)
    return {"version": mls.publish(t["room"], member, body.key_package)}


@router.post("/mls/commit")
async def mls_commit(body: CommitIn, token: Token) -> dict:
    t, member = _member(token, body.member_id)
    try:
        epoch, version = mls.commit(t["room"], member, body.epoch, body.message, body.welcome, body.added, body.removed)
    except mls.Conflict:
        raise ApiError(409, "epoch_conflict", "The group moved on; please try again.") from None
    return {"epoch": epoch, "version": version}


@router.post("/mls/app", status_code=204)
async def mls_app(body: SealedIn, token: Token) -> None:
    t, member = _member(token, body.member_id)
    mls.relay(t["room"], member, {"epoch": body.epoch, "message": body.message})


@router.post("/mls/rejoin", status_code=204)
async def mls_rejoin(body: MemberIn, token: Token) -> None:
    t, member = _member(token, body.member_id)
    mls.rejoin(t["room"], member)


@router.post("/mls/poll")
async def mls_poll(body: MlsPollIn, token: Token) -> dict:
    t, member = _member(token, body.member_id)
    mls.sweep(t["room"])  # someone whose page stopped asking (closed tab, lost network) leaves the group
    return {"messages": await mls.poll(member, body.after)}


@router.post("/mls/bye", status_code=204)
async def mls_bye(body: MemberIn, token: Token) -> None:
    t = _ticket(token)
    if mls.find(t["room"], body.member_id, str(t["who"])) is not None:
        mls.leave(t["room"], body.member_id)


# ---------- breakout rooms (built in and Jitsi alike) ----------

RoomName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class BreakoutsIn(BaseModel):
    rooms: Annotated[list[RoomName], Field(min_length=1, max_length=breakouts.MAX_ROOMS)]
    assign: dict[Annotated[str, StringConstraints(max_length=40)], int] = {}
    open: bool
    minutes: int | None = Field(None, ge=1, le=240)


class BreakoutJoinIn(BaseModel):
    room: int | None = None  # None = back to the meeting


def _breakouts_out(t: dict, state: breakouts.Breakouts) -> dict:
    out = state.public(str(t["who"]))
    if not t.get("mod"):
        out.pop("assign")
    out["moderator"] = bool(t.get("mod"))
    out["current"] = None if t["room"] == t["main"] else t["room"]
    return out


@router.get("/breakouts")
def breakouts_state(token: Token, db: DB) -> dict:
    t = ticket(db, token)
    return _breakouts_out(t, breakouts.get(t["main"]))


@router.put("/breakouts")
def set_breakouts(body: BreakoutsIn, token: Token, db: DB) -> dict:
    t = ticket(db, token)
    if not t.get("mod"):
        raise forbidden("Only the people leading the meeting can manage breakout rooms.")
    if any(not 0 <= n < len(body.rooms) for n in body.assign.values()):
        raise ApiError(422, "invalid_room", "Please choose one of the rooms.")
    state = breakouts.get(t["main"])
    state.rooms = body.rooms
    state.assign = dict(body.assign)
    state.open = body.open
    state.ends_at = time.time() + body.minutes * 60 if body.open and body.minutes else None
    return _breakouts_out(t, state)


@router.post("/breakouts/join")
def join_breakout(body: BreakoutJoinIn, token: Token, db: DB) -> dict:
    """The connection for my breakout room (or back to the meeting), with the same name and role."""
    t = ticket(db, token)
    who = str(t["who"])
    if rtc.is_removed(t["main"], who):
        raise ApiError(403, "removed_from_meeting", "You were removed from this meeting.")
    room = t["main"]
    town_hall = False
    if body.room is None:
        meeting = db.scalar(select(Meeting).where(Meeting.room == t["main"]))
        town_hall = bool(meeting and meeting.town_hall)
    else:
        state = breakouts.get(t["main"])
        state.public(who)  # closes the rooms when their time is up
        allowed = t.get("mod") or (state.open and state.assign.get(who) == body.room)
        if not allowed or not 0 <= body.room < len(state.rooms):
            raise forbidden("This breakout room is not for you.")
        room = breakouts.room_name(t["main"], body.room)
    main = db.scalar(select(Meeting).where(Meeting.room == t["main"]))
    e2ee = bool(main and main.e2ee)
    info = connect_room(db, room, t["main"], t["name"], who, bool(t.get("host")), bool(t.get("mod")), town_hall, e2ee)
    return info | {"town_hall": town_hall}
