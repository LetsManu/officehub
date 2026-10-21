"""Signalling for built-in meetings (see services/rtc.py). The room token from /api/meetings/{id}/join (or the
guest page) is the admission ticket, so the same endpoints serve people, guests and later the apps."""

from typing import Annotated, Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..db import SessionLocal
from ..errors import ApiError
from ..services import rtc
from ..services.meetings import BUILTIN_MAX, rtc_key
from ..services.office import jwt_decode

router = APIRouter(prefix="/api/rtc", tags=["meetings"])

_key: str | None = None


def _ticket(token: str) -> dict:
    global _key  # noqa: PLW0603 - read once from the database
    if _key is None:
        with SessionLocal() as db:
            _key = rtc_key(db)
    data = jwt_decode(token, _key)
    if not all(k in data for k in ("room", "who", "name")):
        raise ApiError(401, "invalid_token", "Invalid token.")
    return data


def _peer(token: str, peer_id: str) -> tuple[dict, rtc.Peer]:
    ticket = _ticket(token)
    peer = rtc.find(ticket["room"], peer_id, str(ticket["who"]))
    if peer is None:
        raise ApiError(410, "peer_gone", "Please join again.")
    return ticket, peer


Token = Annotated[str, Header(alias="X-Meeting-Token", max_length=2000)]


class PeerIn(BaseModel):
    peer_id: str = Field(max_length=32)


class SendIn(PeerIn):
    to: str | None = Field(None, max_length=32)
    type: Literal["signal", "state", "chat"]
    data: dict


class PollIn(PeerIn):
    after: int = 0


@router.post("/hello")
async def hello(token: Token) -> dict:
    ticket = _ticket(token)
    if rtc.count(ticket["room"]) >= BUILTIN_MAX:
        raise ApiError(409, "meeting_full", "This meeting is full.")
    peer, others = rtc.join(ticket["room"], str(ticket["who"]), ticket["name"], bool(ticket.get("host")))
    return {"peer_id": peer.id, "peers": [p.public() for p in others]}


@router.post("/send", status_code=204)
async def send(body: SendIn, token: Token) -> None:
    ticket, peer = _peer(token, body.peer_id)
    if len(str(body.data)) > 64_000:
        raise ApiError(413, "too_large", "Message too large.")
    if body.type == "chat":
        text = str(body.data.get("text", "")).strip()[:1000]
        if not text:
            return
        body.data = {"text": text}
    rtc.send(ticket["room"], peer, body.to, body.type, body.data)


@router.post("/poll")
async def poll(body: PollIn, token: Token) -> dict:
    _ticket_data, peer = _peer(token, body.peer_id)
    return {"messages": await rtc.poll(peer, body.after)}


@router.post("/bye", status_code=204)
async def bye(body: PeerIn, token: Token) -> None:
    ticket = _ticket(token)
    if rtc.find(ticket["room"], body.peer_id, str(ticket["who"])) is not None:
        rtc.leave(ticket["room"], body.peer_id)
