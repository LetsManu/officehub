"""Open a file of a space in WordCraft or DeckCraft (browser version) and take Save back as a new version.

The app gets two same-site URLs with a ticket for this one file and person (like the office editors' WOPI token):
one to read the file and one to save it. Check-out, editor locks, file type and size are checked as for uploads.

While someone has a file open with saving allowed, it carries a short lock ("craft:<user>:<token>") that the page
renews every minute. Everyone else opens it read-only and sees who is editing; the lock ends when the page closes, or
two minutes after the last renewal (closed laptop, lost network).
"""

import secrets
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from ..config import settings
from ..deps import DB, CurrentUser
from ..errors import ApiError, not_found
from ..files import MIME_TYPES, matches_signature
from ..models import Space, SpaceFile, User, utcnow
from ..services import craft
from ..services.office import make_token, read_token
from ..services.spaces import add_version, checked_out_by_other, current_path, get_file, lock_owner_id, locked_by_other, role_in

router = APIRouter(prefix="/api/craft", tags=["office"])

LOCK_MINUTES = 2


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


class LockIn(BaseModel):
    lock: str


def _lock_holder(db: DB, item: SpaceFile) -> str:
    owner = lock_owner_id(item)
    person = db.get(User, owner) if owner else None
    return person.full_name if person else ""


def _holds(item: SpaceFile, user: User, lock: str) -> bool:
    return bool(lock) and item.lock_id == f"craft:{user.id}:{lock}" and not locked_by_other(item, user)


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
    if can_write and locked_by_other(item, user):
        can_write, editing_by = False, _lock_holder(db, item)
    elif can_write:
        lock = secrets.token_urlsafe(12)
        item.lock_id, item.lock_expires = f"craft:{user.id}:{lock}", utcnow() + timedelta(minutes=LOCK_MINUTES)
        db.commit()
    token, _expires = make_token(db, item.id, user.id, can_write)
    file_url = f"/api/craft/files/{item.id}?token={quote(token)}"
    params = f"src={quote(file_url, safe='')}&name={quote(item.name, safe='')}"
    if can_write:
        params += f"&save={quote(file_url, safe='')}"
    return CraftOpen(app=app, url=f"/{app}/?{params}", can_write=can_write, lock=lock, editing_by=editing_by)


@router.post("/lock/{file_id}", status_code=204)
def renew_lock(file_id: int, body: LockIn, user: CurrentUser, db: DB) -> Response:
    """Keep editing: renew the lock. 409 when it was lost (expired and taken by someone else)."""
    item = get_file(db, user, file_id)
    if not _holds(item, user, body.lock) and (locked_by_other(item, user) or checked_out_by_other(item, user)):
        raise ApiError(409, "file_locked", f"{_lock_holder(db, item) or 'Someone'} is editing this file now.")
    item.lock_id, item.lock_expires = f"craft:{user.id}:{body.lock}", utcnow() + timedelta(minutes=LOCK_MINUTES)
    db.commit()
    return Response(status_code=204)


@router.delete("/lock/{file_id}", status_code=204)
def release_lock(file_id: int, user: CurrentUser, db: DB, lock: str = Query(...)) -> Response:
    item = get_file(db, user, file_id)
    if _holds(item, user, lock):
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
async def craft_save(file_id: int, request: Request, db: DB, token: str = Query(...)) -> Response:
    item, user, data = _ticket(db, file_id, token)
    space = db.get(Space, item.space_id)
    if not data.get("w") or space is None or space.archived or role_in(db, user, space) is None:
        raise ApiError(403, "forbidden", "You cannot change this file.")
    if checked_out_by_other(item, user):
        raise ApiError(423, "file_checked_out", "Someone else has checked out this file.")
    if locked_by_other(item, user):
        raise ApiError(409, "file_locked", f"{_lock_holder(db, item) or 'Someone'} is editing this file right now.")
    body = await request.body()
    if len(body) > settings.max_upload_bytes:
        raise ApiError(413, "file_too_large", f"The file is larger than {settings.max_upload_mb} MB.")
    if not body or not matches_signature(item.file_type, body):
        raise ApiError(422, "file_invalid", "The file content does not match its file type.")
    add_version(db, item, body, user, craft.app_for(item.file_type) or "editor")
    db.commit()
    return Response(status_code=204)
