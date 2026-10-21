"""Open a file of a space in WordCraft or DeckCraft (browser version) and take Save back as a new version.

The app gets two same-site URLs with a ticket for this one file and person (like the office editors' WOPI token):
one to read the file and one to save it. Check-out, editor locks, file type and size are checked as for uploads.

While someone has a file open with saving allowed, it carries a short lock that the page renews every minute; it
ends when the page closes, or two minutes after the last renewal (closed laptop, lost network).

- Programs that edit together (DeckCraft) share one session lock ("craft:0:<token>"): everyone who opens the file
  joins the same live session (`services/collab.py`, endpoints below) and their changes reach the others at once.
- Programs that cannot yet (WordCraft) lock the file for one person ("craft:<user>:<token>"); everyone else opens it
  read-only and sees who is editing.

The office editors ("Edit together" in Collabora/ONLYOFFICE) and the network drive wait while either lock is held.
"""

import base64
import binascii

import secrets
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from ..config import settings
from ..deps import DB, CurrentUser
from ..errors import ApiError, not_found
from ..files import MIME_TYPES, extract_text, matches_signature, write_file
from ..models import Space, SpaceFile, User, utcnow
from ..services import collab, craft
from ..services.office import make_token, read_token
from ..services.spaces import add_version, checked_out_by_other, current_path, get_file, lock_owner_id, locked_by_other, role_in

router = APIRouter(prefix="/api/craft", tags=["office"])

LOCK_MINUTES = 2
AUTOSAVE_MINUTES = 15  # automatic saves while editing together go into one version for this long


class CraftConfig(BaseModel):
    apps: list[str]
    types: dict[str, list[str]]


class CraftOpen(BaseModel):
    app: str
    url: str
    can_write: bool
    lock: str | None = None
    # Name of the person editing it right now, when that is why it opened read-only ("" = an office editor)
    editing_by: str | None = None
    # Everyone who opens it edits together, live (DeckCraft)
    together: bool = False


class LockIn(BaseModel):
    lock: str


def _lock_holder(db: DB, item: SpaceFile) -> str:
    owner = lock_owner_id(item)
    person = db.get(User, owner) if owner else None
    return person.full_name if person else ""


SESSION = "craft:0:"


def _session_token(item: SpaceFile) -> str | None:
    """The token of the live editing session holding the file, if one does."""
    if item.lock_id and item.lock_id.startswith(SESSION) and item.lock_expires and item.lock_expires > utcnow():
        return item.lock_id.removeprefix(SESSION)
    return None


def _holds(item: SpaceFile, user: User, lock: str) -> bool:
    if not lock:
        return False
    if _session_token(item) == lock:
        return True
    return item.lock_id == f"craft:{user.id}:{lock}" and not locked_by_other(item, user)


def _set_lock(item: SpaceFile, value: str) -> None:
    item.lock_id, item.lock_expires = value, utcnow() + timedelta(minutes=LOCK_MINUTES)


@router.get("/config", response_model=CraftConfig)
def craft_config(user: CurrentUser) -> CraftConfig:
    apps = craft.available()
    return CraftConfig(apps=apps, types={a: sorted(craft.APPS[a]) for a in apps})


@router.post("/open/{file_id}", response_model=CraftOpen)
def open_in_app(file_id: int, user: CurrentUser, db: DB) -> CraftOpen:
    item = get_file(db, user, file_id)
    app = craft.app_for(item.file_type)
    if app is None or app not in craft.available():
        raise ApiError(409, "craft_unavailable", "This program is not available for this file.")
    space = db.get(Space, item.space_id)
    can_write = role_in(db, user, space) is not None and not space.archived and not checked_out_by_other(item, user)
    lock = editing_by = None
    together = craft.together(app)
    session = _session_token(item) if together else None
    if can_write and session is not None:
        lock = session  # join the people already editing it
        _set_lock(item, SESSION + lock)
        db.commit()
    elif can_write and locked_by_other(item, user):
        can_write, editing_by = False, _lock_holder(db, item)
    elif can_write:
        lock = secrets.token_urlsafe(12)
        _set_lock(item, (SESSION if together else f"craft:{user.id}:") + lock)
        db.commit()
    token, _expires = make_token(db, item.id, user.id, can_write)
    file_url = f"/api/craft/files/{item.id}?token={quote(token)}"
    params = f"src={quote(file_url, safe='')}&name={quote(item.name, safe='')}"
    if can_write:
        params += f"&save={quote(file_url, safe='')}"
    if together:
        # Live editing (also for people who may only look: they see the changes as they happen)
        params += f"&collab={quote(f'/api/craft/collab/{item.id}?token={quote(token)}', safe='')}"
    return CraftOpen(app=app, url=f"/{app}/?{params}", can_write=can_write, lock=lock, editing_by=editing_by,
                     together=together)


@router.post("/lock/{file_id}", status_code=204)
def renew_lock(file_id: int, body: LockIn, user: CurrentUser, db: DB) -> Response:
    """Keep editing: renew the lock. 409 when it was lost (expired and taken by someone else)."""
    item = get_file(db, user, file_id)
    if not _holds(item, user, body.lock) and (locked_by_other(item, user) or checked_out_by_other(item, user)):
        raise ApiError(409, "file_locked", f"{_lock_holder(db, item) or 'Someone'} is editing this file now.")
    together = craft.together(craft.app_for(item.file_type))
    _set_lock(item, (SESSION if together else f"craft:{user.id}:") + body.lock)
    db.commit()
    return Response(status_code=204)


@router.delete("/lock/{file_id}", status_code=204)
def release_lock(file_id: int, user: CurrentUser, db: DB, lock: str = Query(...)) -> Response:
    item = get_file(db, user, file_id)
    # A live session stays locked while others are still in it (the leaving page may still be counted)
    if _holds(item, user, lock) and not (_session_token(item) == lock and collab.count(item.id) > 1):
        item.lock_id, item.lock_expires = None, None
        db.commit()
    return Response(status_code=204)


def _ticket(db: DB, file_id: int, token: str) -> tuple[SpaceFile, User, dict]:
    data = read_token(db, token, file_id)
    item = db.get(SpaceFile, file_id)
    user = db.get(User, data["u"])
    if item is None or item.deleted_at is not None or user is None or not user.is_active:
        raise not_found("File")
    return item, user, data


@router.get("/files/{file_id}")
def craft_file(file_id: int, db: DB, token: str = Query(...)) -> Response:
    item, _user, _data = _ticket(db, file_id, token)
    return Response(current_path(item).read_bytes(), media_type=MIME_TYPES.get(item.file_type, "application/octet-stream"),
                    headers={"Cache-Control": "no-store"})


@router.put("/files/{file_id}", status_code=204)
async def craft_save(file_id: int, request: Request, db: DB, token: str = Query(...), auto: bool = False) -> Response:
    item, user, data = _ticket(db, file_id, token)
    space = db.get(Space, item.space_id)
    if not data.get("w") or space is None or space.archived or role_in(db, user, space) is None:
        raise ApiError(403, "forbidden", "You cannot change this file.")
    if checked_out_by_other(item, user):
        raise ApiError(423, "file_checked_out", "Someone else has checked out this file.")
    if locked_by_other(item, user) and _session_token(item) is None:
        raise ApiError(409, "file_locked", f"{_lock_holder(db, item) or 'Someone'} is editing this file right now.")
    body = await request.body()
    if len(body) > settings.max_upload_bytes:
        raise ApiError(413, "file_too_large", f"The file is larger than {settings.max_upload_mb} MB.")
    if not body or not matches_signature(item.file_type, body):
        raise ApiError(422, "file_invalid", "The file content does not match its file type.")
    app = craft.app_for(item.file_type) or "editor"
    current = next((v for v in item.versions if v.number == item.version), None)
    if (auto and current is not None and current.source == "together"
            and current.created_at > utcnow() - timedelta(minutes=AUTOSAVE_MINUTES)):
        # Saved automatically while editing together: keep one version per stretch of work, not one per pause
        current.path, current.size = write_file(f"spaces/{item.space_id}", item.file_type, body), len(body)
        current.created_by_id = user.id
        item.size, item.updated_at, item.updated_by_id = len(body), utcnow(), user.id
        item.content_text = extract_text(item.file_type, body)[:200_000]
    else:
        add_version(db, item, body, user, "together" if auto else app)
    db.commit()
    return Response(status_code=204)


# ---------- live editing together (DeckCraft) ----------

MAX_UPDATE_BYTES = 150 * 1024 * 1024  # the first update carries the whole presentation with its pictures


class PeerIn(BaseModel):
    peer_id: str = Field(max_length=32)


class UpdateIn(PeerIn):
    data: str  # base64


class CompactIn(UpdateIn):
    upto: int = Field(ge=1)


class PresenceIn(PeerIn):
    state: dict


class PollIn(PeerIn):
    after: int = 0


def _collab_peer(db: DB, file_id: int, token: str, peer_id: str) -> tuple[SpaceFile, dict, collab.Peer]:
    item, user, data = _ticket(db, file_id, token)
    peer = collab.find(item.id, peer_id, user.id)
    if peer is None:
        raise ApiError(410, "collab_gone", "You are no longer in this editing session. Please open the file again.")
    return item, data, peer


def _checked(data: str) -> str:
    if len(data) > MAX_UPDATE_BYTES * 4 // 3 + 4:
        raise ApiError(413, "file_too_large", "This change is too large.")
    try:
        base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(422, "invalid_message", "Unknown message.") from None
    return data


@router.post("/collab/{file_id}/hello")
def collab_hello(file_id: int, db: DB, token: str = Query(...)) -> dict:
    """Join the file's live session: everything changed so far, and whether to start it (seed)."""
    item, user, data = _ticket(db, file_id, token)
    if not craft.together(craft.app_for(item.file_type)):
        raise ApiError(409, "craft_unavailable", "Editing together is not available for this file.")
    peer, room, seed = collab.join(item.id, user.id, user.full_name, bool(data.get("w")))
    return {"peer_id": peer.id, "slot": peer.slot, "color": peer.color, "name": peer.name, "seed": seed,
            "log": list(room.log), "peers": [p.public() for p in room.peers.values() if p is not peer]}


@router.post("/collab/{file_id}/update", status_code=204)
def collab_update(file_id: int, body: UpdateIn, db: DB, token: str = Query(...)) -> Response:
    item, data, peer = _collab_peer(db, file_id, token, body.peer_id)
    if not data.get("w") or not peer.can_write:
        raise ApiError(403, "forbidden", "You cannot change this file.")
    collab.update(item.id, peer, _checked(body.data))
    return Response(status_code=204)


@router.post("/collab/{file_id}/compact", status_code=204)
def collab_compact(file_id: int, body: CompactIn, db: DB, token: str = Query(...)) -> Response:
    item, _data, peer = _collab_peer(db, file_id, token, body.peer_id)
    collab.compact(item.id, peer, _checked(body.data), body.upto)
    return Response(status_code=204)


@router.post("/collab/{file_id}/presence", status_code=204)
def collab_presence(file_id: int, body: PresenceIn, db: DB, token: str = Query(...)) -> Response:
    item, _data, peer = _collab_peer(db, file_id, token, body.peer_id)
    if len(str(body.state)) > 4000:
        raise ApiError(413, "too_large", "Message too large.")
    collab.presence(item.id, peer, body.state)
    return Response(status_code=204)


@router.post("/collab/{file_id}/poll")
async def collab_poll(file_id: int, body: PollIn, db: DB, token: str = Query(...)) -> dict:
    _item, _data, peer = _collab_peer(db, file_id, token, body.peer_id)
    db.close()  # do not hold a database connection while waiting
    return {"messages": await collab.poll(peer, body.after)}


@router.post("/collab/{file_id}/bye", status_code=204)
def collab_bye(file_id: int, body: PeerIn, db: DB, token: str = Query(...)) -> Response:
    item, user, _data = _ticket(db, file_id, token)
    if collab.find(item.id, body.peer_id, user.id) is not None:
        collab.leave(item.id, body.peer_id)
    return Response(status_code=204)
