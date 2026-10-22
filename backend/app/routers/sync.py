"""Desktop sync API (the Windows app's "OfficeHub" folder in Explorer, like OneDrive). See services/sync.py.

Sign-in with the e-mail address and an app password (like the network drive), or the portal session. Files and
folders are addressed by id, so renames and moves on either side stay one item. Every save is a new version with the
usual rules: check-out, locks while someone edits, allowed file types, the space's trash for deletions.

    GET    /api/sync/changes?since=N&wait=25   what changed after change number N (long polling)
    GET    /api/sync/files/{id}                content (Range for resuming)
    PUT    /api/sync/files/{id}?base=V         new content, only if the file is still at version V (else 409)
    POST   /api/sync/files?space_id=&folder_id=&name=   a new file (body: content)
    PATCH  /api/sync/files/{id}                rename / move: {"name", "folder_id"}
    DELETE /api/sync/files/{id}                to the trash
    POST   /api/sync/folders                   {"space_id", "parent_id", "name"}
    PATCH  /api/sync/folders/{id}              {"name", "parent_id"}
    DELETE /api/sync/folders/{id}              to the trash
"""

import asyncio
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from ..config import settings
from ..deps import DB, get_current_user
from ..errors import ApiError, not_found
from ..files import MIME_TYPES, SPACE_TYPES, extension, matches_signature, safe_display_name
from ..models import Folder, Space, SpaceFile, SyncTombstone, User, utcnow
from ..services import sync
from ..services.spaces import (
    add_version,
    current_path,
    ensure_can_change,
    folder_path,
    get_file,
    get_folder,
    get_space,
    in_deleted_folder,
    locked_by_other,
    checked_out_by_other,
    my_space_ids,
    unique_name,
)
from .webdav import _user as app_password_user

router = APIRouter(prefix="/api/sync", tags=["sync"])

WAIT_SECONDS = 25
STEP_SECONDS = 1
PAGE = 2000


def sync_user(request: Request, db: DB) -> User:
    """App password (Basic), as the Windows app signs in; or the portal session."""
    if request.headers.get("authorization", "").lower().startswith("basic "):
        user = app_password_user(request, db)
        if user is None:
            raise ApiError(401, "unauthorized", "Wrong e-mail address or app password.")
        return user
    return get_current_user(request, db)


SyncUser = Annotated[User, Depends(sync_user)]


class SpaceItem(BaseModel):
    id: int
    name: str
    writable: bool


class Item(BaseModel):
    kind: Literal["folder", "file"]
    id: int
    space_id: int
    parent_id: int | None  # folder (None: the space's top level)
    name: str
    size: int = 0
    version: int = 0
    modified: datetime
    deleted: bool = False
    # Only the person who checked it out (or the one editing it right now) may change it
    read_only: bool = False
    seq: int


class Tombstone(BaseModel):
    kind: Literal["space", "folder", "file"]
    id: int
    space_id: int


class Changes(BaseModel):
    cursor: int
    reset: bool  # start over: the answer is the whole tree (first sync, or the client was away too long)
    more: bool  # ask again right away with the new cursor
    spaces: list[SpaceItem]
    items: list[Item]
    removed: list[Tombstone]


def _folder_item(f: Folder) -> Item:
    return Item(kind="folder", id=f.id, space_id=f.space_id, parent_id=f.parent_id, name=f.name, modified=f.created_at,
                deleted=f.deleted_at is not None, seq=f.sync_seq)


def _file_item(f: SpaceFile, user: User) -> Item:
    return Item(kind="file", id=f.id, space_id=f.space_id, parent_id=f.folder_id, name=f.name, size=f.size,
                version=f.version, modified=f.updated_at, deleted=f.deleted_at is not None,
                read_only=checked_out_by_other(f, user) or locked_by_other(f, user), seq=f.sync_seq)


def _changes(db, user: User, since: int, space_id: int | None) -> Changes:
    spaces = [s for s in db.scalars(select(Space).where(Space.id.in_(my_space_ids(db, user))).order_by(Space.name))]
    ids = [s.id for s in spaces if space_id is None or s.id == space_id]
    reset = since <= 0 or since < sync.oldest_kept(db) - 1
    after = 0 if reset else since
    cursor = sync.current(db)
    rows: list[tuple[int, Item]] = []
    folders = select(Folder).where(Folder.space_id.in_(ids), Folder.sync_seq > after)
    files = select(SpaceFile).where(SpaceFile.space_id.in_(ids), SpaceFile.sync_seq > after)
    if reset:  # a full tree: only what exists
        folders = folders.where(Folder.deleted_at.is_(None))
        files = files.where(SpaceFile.deleted_at.is_(None))
    rows += [(f.sync_seq, _folder_item(f)) for f in db.scalars(folders.order_by(Folder.sync_seq).limit(PAGE + 1))]
    rows += [(f.sync_seq, _file_item(f, user)) for f in db.scalars(files.order_by(SpaceFile.sync_seq).limit(PAGE + 1))]
    rows.sort(key=lambda r: (r[0], r[1].kind != "folder"))  # parents before their content
    more = len(rows) > PAGE
    if more:
        # Everything with the last number shown goes out together, so the next page starts cleanly after it
        last = rows[PAGE - 1][0]
        rows = [r for r in rows if r[0] <= last]
        cursor = last
    removed = []
    if not reset:
        tombs = db.scalars(select(SyncTombstone).where(SyncTombstone.seq > after, SyncTombstone.seq <= cursor,
                                                       or_(SyncTombstone.space_id.in_(ids), SyncTombstone.kind == "space")))
        removed = [Tombstone(kind=t.kind, id=t.item_id, space_id=t.space_id) for t in tombs]
    return Changes(
        cursor=cursor,
        reset=reset,
        more=more,
        spaces=[SpaceItem(id=s.id, name=s.name, writable=not s.archived) for s in spaces],
        items=[item for _, item in rows],
        removed=removed,
    )


@router.get("/changes", response_model=Changes)
async def changes(
    user: SyncUser,
    db: DB,
    since: int = Query(0, ge=0),
    wait: int = Query(0, ge=0, le=WAIT_SECONDS),
    space_id: int | None = None,
) -> Changes:
    """What changed after change number `since`; with `wait`, holds the answer until something changes."""
    waited = 0
    while since > 0 and wait and waited < wait and sync.current(db) <= since:
        await asyncio.sleep(STEP_SECONDS)
        waited += STEP_SECONDS
        db.expire_all()
    return _changes(db, user, since, space_id)


# ---------- files ----------


def _payload_limit(request: Request) -> None:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_upload_bytes:
        raise ApiError(413, "file_too_large", f"Larger than {settings.max_upload_mb} MB.")


async def _content(request: Request, file_type: str) -> bytes:
    _payload_limit(request)
    data = await request.body()
    if len(data) > settings.max_upload_bytes:
        raise ApiError(413, "file_too_large", f"Larger than {settings.max_upload_mb} MB.")
    if data and not matches_signature(file_type, data):
        raise ApiError(415, "file_content_mismatch", "The content does not match the file type.")
    return data


@router.get("/files/{file_id}")
def download(file_id: int, user: SyncUser, db: DB) -> FileResponse:
    item = get_file(db, user, file_id)
    return FileResponse(current_path(item), media_type=MIME_TYPES.get(item.file_type, "application/octet-stream"),
                        headers={"ETag": f'"{item.version}"', "X-File-Version": str(item.version)})


@router.put("/files/{file_id}", response_model=Item)
async def save(file_id: int, request: Request, user: SyncUser, db: DB, base: int = Query(..., ge=0)) -> Item:
    item = get_file(db, user, file_id, write=True)
    ensure_can_change(item, user)
    if item.version != base:
        raise ApiError(409, "sync_conflict", "Someone else saved a newer version in the meantime.")
    data = await _content(request, item.file_type)
    add_version(db, item, data, user, "sync")
    db.commit()
    return _file_item(item, user)


@router.post("/files", response_model=Item, status_code=201)
async def create(
    request: Request,
    user: SyncUser,
    db: DB,
    space_id: int,
    name: str = Query(..., min_length=1, max_length=200),
    folder_id: int | None = None,
) -> Item:
    space = get_space(db, user, space_id, write=True)
    folder = get_folder(db, space.id, folder_id)
    if folder is not None and (folder.deleted_at is not None or in_deleted_folder(db, folder.id)):
        raise not_found("Folder")
    clean = safe_display_name(name)
    file_type = extension(clean)
    if file_type not in SPACE_TYPES:
        raise ApiError(415, "file_type_not_allowed", "This file type is not supported here.")
    data = await _content(request, file_type)
    item = SpaceFile(space_id=space.id, folder_id=folder_id, file_type=file_type, created_by_id=user.id,
                     name=unique_name(db, space.id, folder_id, clean))
    db.add(item)
    add_version(db, item, data, user, "sync")
    db.commit()
    return _file_item(item, user)


class Move(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    folder_id: int | None = None


@router.patch("/files/{file_id}", response_model=Item)
def move_file(file_id: int, body: Move, user: SyncUser, db: DB) -> Item:
    item = get_file(db, user, file_id, write=True)
    ensure_can_change(item, user)
    get_folder(db, item.space_id, body.folder_id)
    name = safe_display_name(body.name)
    if extension(name) != item.file_type:
        raise ApiError(422, "file_type_change", "The file type cannot change.")
    item.folder_id = body.folder_id
    item.name = unique_name(db, item.space_id, body.folder_id, name, ignore_id=item.id)
    db.commit()
    return _file_item(item, user)


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: int, user: SyncUser, db: DB) -> None:
    item = get_file(db, user, file_id, write=True)
    ensure_can_change(item, user)
    item.deleted_at = utcnow()
    db.commit()


# ---------- folders ----------


class FolderIn(BaseModel):
    space_id: int
    parent_id: int | None = None
    name: str = Field(..., min_length=1, max_length=120)


class FolderMove(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    parent_id: int | None = None


def _live_folder(db, user: User, folder_id: int) -> Folder:
    folder = db.get(Folder, folder_id)
    if folder is None or folder.deleted_at is not None:
        raise not_found("Folder")
    get_space(db, user, folder.space_id, write=True)
    return folder


@router.post("/folders", response_model=Item, status_code=201)
def create_folder(body: FolderIn, user: SyncUser, db: DB) -> Item:
    space = get_space(db, user, body.space_id, write=True)
    get_folder(db, space.id, body.parent_id)
    folder = Folder(space_id=space.id, parent_id=body.parent_id, name=safe_display_name(body.name)[:120],
                    created_by_id=user.id)
    db.add(folder)
    db.commit()
    return _folder_item(folder)


@router.patch("/folders/{folder_id}", response_model=Item)
def move_folder(folder_id: int, body: FolderMove, user: SyncUser, db: DB) -> Item:
    folder = _live_folder(db, user, folder_id)
    parent = get_folder(db, folder.space_id, body.parent_id)
    if parent is not None and any(f.id == folder.id for f in folder_path(db, parent)):
        raise ApiError(422, "folder_cycle", "A folder cannot be moved into itself.")
    folder.name, folder.parent_id = safe_display_name(body.name)[:120], body.parent_id
    db.commit()
    return _folder_item(folder)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: int, user: SyncUser, db: DB) -> Response:
    folder = _live_folder(db, user, folder_id)
    folder.deleted_at = utcnow()
    db.commit()
    return Response(status_code=204)
