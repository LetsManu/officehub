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
from ..services import breakouts, rtc
from ..models import Meeting
from ..services.meetings import BUILTIN_MAX, connect_room, rtc_key, ticket
from ..services.office import jwt_decode

router = APIRouter(prefix="/api/rtc", tags=["meetings"])

# App messages anyone may send, and those only for people leading the meeting
APP_KINDS = {"react", "wb", "wb-clear", "wb-req", "wb-all", "rec", "sync-req"}
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


@router.post("/poll")
async def poll(body: PollIn, token: Token) -> dict:
    _ticket_data, peer = _peer(token, body.peer_id)
    return {"messages": await rtc.poll(peer, body.after)}


@router.post("/bye", status_code=204)
async def bye(body: PeerIn, token: Token) -> None:
    t = _ticket(token)
    if rtc.find(t["room"], body.peer_id, str(t["who"])) is not None:
        rtc.leave(t["room"], body.peer_id)


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
    info = connect_room(db, room, t["main"], t["name"], who, bool(t.get("host")), bool(t.get("mod")), town_hall)
    return info | {"town_hall": town_hall}
