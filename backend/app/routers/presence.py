"""Presence: who is reachable right now, and setting my own status (see services/presence.py)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, StringConstraints

from ..deps import DB, CurrentUser
from ..errors import ApiError
from ..services.presence import state_of, states

router = APIRouter(prefix="/api", tags=["presence"])


class PresenceOut(BaseModel):
    state: str  # available, busy, in_meeting, dnd, away, ooo, offline
    text: str
    manual: str  # what the person chose ("auto" = OfficeHub decides)
    activity: dict | None = None  # {kind: editing | meeting, label, link} – what they are doing in OfficeHub


class PresenceIn(BaseModel):
    presence: Literal["auto", "available", "busy", "dnd", "away", "offline"]
    status_text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


@router.get("/presence", response_model=dict[int, PresenceOut])
def presence(user: CurrentUser, db: DB, ids: str = Query(..., max_length=2000)) -> dict[int, PresenceOut]:
    try:
        wanted = sorted({int(x) for x in ids.split(",") if x.strip()})[:200]
    except ValueError:
        raise ApiError(422, "invalid_ids", "Please send person numbers.") from None
    return {uid: PresenceOut(**s) for uid, s in states(db, wanted, user).items()}


@router.put("/me/presence", response_model=PresenceOut)
def set_presence(body: PresenceIn, user: CurrentUser, db: DB) -> PresenceOut:
    user.presence, user.status_text = body.presence, body.status_text
    db.commit()
    return PresenceOut(**state_of(db, user))
