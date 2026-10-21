"""Opening files in Collabora Online or ONLYOFFICE, and the endpoints those servers call back.

/wopi/... and /office-hooks/... are only reachable inside the Docker network (the frontend web server
forwards /api/ only). Every call carries a signed token that names the file, the person and whether they
may save.
"""

import urllib.request
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, StringConstraints

from ..config import settings
from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, not_found
from ..models import Space, SpaceFile, User, utcnow
from ..services.audit import audit
from ..services.office import (
    EDITABLE,
    ONLYOFFICE_KIND,
    available,
    collabora_action,
    default_engine,
    jwt_decode,
    jwt_encode,
    make_token,
    onlyoffice_download_url,
    read_token,
)
from ..services import craft
from ..services.settings import get_setting, set_setting
from ..services.spaces import add_version, checked_out_by_other, current_path, get_file, role_in

router = APIRouter(prefix="/api/office", tags=["office"])
wopi = APIRouter(prefix="/wopi", tags=["office (internal)"])
hooks = APIRouter(prefix="/office-hooks", tags=["office (internal)"])

LOCK_MINUTES = 30


class OfficeConfig(BaseModel):
    engines: list[str]
    default: str | None
    editable: dict[str, list[str]]
    craft: list[str] = []  # WordCraft / DeckCraft in the browser, when they run
    prefer_craft: bool = False  # Word and PowerPoint files open there instead of the office server


class EngineIn(BaseModel):
    engine: str | None = None
    prefer_craft: bool | None = None


class OpenIn(BaseModel):
    engine: str | None = None
    origin: Annotated[str, StringConstraints(max_length=200, pattern=r"^https?://[A-Za-z0-9.\-:\[\]]+$")]


class OpenOut(BaseModel):
    engine: str
    can_write: bool
    file_name: str
    # Collabora: the page is loaded by posting the token to action_url inside an iframe
    action_url: str | None = None
    access_token: str | None = None
    access_token_ttl: int | None = None
    # ONLYOFFICE: load the script, then start the editor with this configuration
    script: str | None = None
    config: dict | None = None


@router.get("/config", response_model=OfficeConfig)
def office_config(user: CurrentUser, db: DB) -> OfficeConfig:
    engines = available()
    return OfficeConfig(engines=engines, default=default_engine(db),
                        editable={e: sorted(EDITABLE[e]) for e in engines},
                        craft=craft.available(), prefer_craft=craft.preferred(db))


@router.put("/config", response_model=OfficeConfig)
def set_office_config(body: EngineIn, user: Admin, db: DB) -> OfficeConfig:
    stored = dict(get_setting(db, "office", {}))
    if body.engine is not None:
        if body.engine not in available():
            raise ApiError(422, "invalid_choice", "This office server is not set up.")
        stored["engine"] = body.engine
    if body.prefer_craft is not None:
        stored["prefer_craft"] = body.prefer_craft
    set_setting(db, "office", stored)
    audit(db, user, "settings_updated", "office", engine=stored.get("engine"), prefer_craft=stored.get("prefer_craft"))
    db.commit()
    return office_config(user, db)


@router.post("/open/{file_id}", response_model=OpenOut)
def open_file(file_id: int, body: OpenIn, user: CurrentUser, db: DB) -> OpenOut:
    item = get_file(db, user, file_id)
    engine = body.engine or default_engine(db)
    if engine not in available():
        raise ApiError(409, "office_unavailable", "Office editing is not set up.")
    space = db.get(Space, item.space_id)
    can_write = (role_in(db, user, space) is not None and not space.archived
                 and item.file_type in EDITABLE[engine] and not checked_out_by_other(item, user))
    token, expires = make_token(db, item.id, user.id, can_write, body.origin)
    if engine == "collabora":
        return OpenOut(engine=engine, can_write=can_write, file_name=item.name,
                       action_url=collabora_action(item.file_type, can_write) + f"lang={user.language}&WOPISrc="
                       + urllib.request.quote(f"{settings.backend_internal_url}/wopi/files/{item.id}", safe=""),
                       access_token=token, access_token_ttl=expires)
    kind = ONLYOFFICE_KIND.get(item.file_type)
    if kind is None:
        raise ApiError(409, "office_type", "This file type cannot be opened in the office editor.")
    internal = settings.backend_internal_url
    config = {
        "document": {
            "fileType": item.file_type,
            # A new key for every saved version, so the editor never shows an old copy
            "key": f"oh{item.id}v{item.version}u{int(item.updated_at.timestamp())}",
            "title": item.name,
            "url": f"{internal}/office-hooks/onlyoffice/file/{item.id}?token={token}",
            "permissions": {"edit": can_write, "download": True, "print": True, "comment": can_write},
        },
        "documentType": kind,
        "editorConfig": {
            "mode": "edit" if can_write else "view",
            "lang": user.language,
            "callbackUrl": f"{internal}/office-hooks/onlyoffice/callback/{item.id}?token={token}",
            "user": {"id": str(user.id), "name": user.full_name},
            "customization": {"forcesave": True, "compactHeader": True, "uiTheme": "theme-classic-light"},
        },
        "type": "desktop",
        "height": "100%",
        "width": "100%",
    }
    if settings.onlyoffice_jwt_secret:
        config["token"] = jwt_encode(config, settings.onlyoffice_jwt_secret)
    return OpenOut(engine=engine, can_write=can_write, file_name=item.name,
                   script="/onlyoffice/web-apps/apps/api/documents/api.js", config=config)


# ---------- WOPI (Collabora) ----------


def _wopi_file(db: DB, file_id: int, access_token: str) -> tuple[SpaceFile, User, dict]:
    data = read_token(db, access_token, file_id)
    item = db.get(SpaceFile, file_id)
    user = db.get(User, data["u"])
    if item is None or item.deleted_at is not None or user is None or not user.is_active:
        raise not_found("File")
    return item, user, data


def _lock_active(item: SpaceFile) -> bool:
    return bool(item.lock_id and item.lock_expires and item.lock_expires > utcnow())


def _conflict(item: SpaceFile) -> Response:
    return Response(status_code=409, headers={"X-WOPI-Lock": item.lock_id or ""})


@wopi.get("/files/{file_id}")
def check_file_info(file_id: int, db: DB, access_token: str = Query(...)) -> dict:
    item, user, data = _wopi_file(db, file_id, access_token)
    return {
        "BaseFileName": item.name,
        "Size": item.size,
        "Version": str(item.version),
        "OwnerId": str(item.created_by_id or 0),
        "UserId": str(user.id),
        "UserFriendlyName": user.full_name,
        "UserCanWrite": bool(data.get("w")),
        "UserCanNotWriteRelative": True,
        "SupportsLocks": True,
        "SupportsGetLock": True,
        "SupportsUpdate": True,
        "SupportsRename": bool(data.get("w")),
        "UserCanRename": bool(data.get("w")),
        "LastModifiedTime": item.updated_at.isoformat() + "Z",
        "PostMessageOrigin": data.get("o") or "",
        "HidePrintOption": False,
        "HideSaveOption": False,
        "DisableExport": False,
        "EnableOwnerTermination": False,
    }


@wopi.get("/files/{file_id}/contents")
def get_file_contents(file_id: int, db: DB, access_token: str = Query(...)) -> Response:
    item, _user, _data = _wopi_file(db, file_id, access_token)
    return Response(current_path(item).read_bytes(), media_type="application/octet-stream",
                    headers={"X-WOPI-ItemVersion": str(item.version)})


@wopi.post("/files/{file_id}/contents")
async def put_file(file_id: int, request: Request, db: DB, access_token: str = Query(...),
                   x_wopi_lock: str | None = Header(None), x_cool_wopi_timestamp: str | None = Header(None)) -> Response:
    item, user, data = _wopi_file(db, file_id, access_token)
    if not data.get("w") or checked_out_by_other(item, user):
        return Response(status_code=401)
    if _lock_active(item) and item.lock_id != x_wopi_lock:
        return _conflict(item)
    if x_cool_wopi_timestamp and x_cool_wopi_timestamp != item.updated_at.isoformat() + "Z":
        # Someone saved a newer version (e.g. uploaded one) while this editor was open
        return JSONResponse({"COOLStatusCode": 1010}, status_code=409)
    body = await request.body()
    if len(body) > settings.max_upload_bytes * 4:
        return Response(status_code=413)
    add_version(db, item, body, user, "editor")
    db.commit()
    return Response(status_code=200, headers={"X-WOPI-ItemVersion": str(item.version)})


@wopi.post("/files/{file_id}")
def lock_operations(
    file_id: int, db: DB, access_token: str = Query(...),
    x_wopi_override: str = Header(""), x_wopi_lock: str | None = Header(None), x_wopi_oldlock: str | None = Header(None),
    x_wopi_requestedname: str | None = Header(None),
) -> Response:
    item, _user, data = _wopi_file(db, file_id, access_token)
    action = x_wopi_override.upper()
    now = utcnow()
    if action == "GET_LOCK":
        return Response(status_code=200, headers={"X-WOPI-Lock": item.lock_id if _lock_active(item) else ""})
    if action in ("LOCK", "REFRESH_LOCK", "UNLOCK") and not x_wopi_lock:
        return Response(status_code=400)
    if action == "LOCK" and x_wopi_oldlock:  # unlock and relock
        if not _lock_active(item) or item.lock_id != x_wopi_oldlock:
            return _conflict(item)
        item.lock_id, item.lock_expires = x_wopi_lock, now + timedelta(minutes=LOCK_MINUTES)
    elif action == "LOCK":
        if _lock_active(item) and item.lock_id != x_wopi_lock:
            return _conflict(item)
        item.lock_id, item.lock_expires = x_wopi_lock, now + timedelta(minutes=LOCK_MINUTES)
    elif action == "REFRESH_LOCK":
        if not _lock_active(item) or item.lock_id != x_wopi_lock:
            return _conflict(item)
        item.lock_expires = now + timedelta(minutes=LOCK_MINUTES)
    elif action == "UNLOCK":
        if not _lock_active(item) or item.lock_id != x_wopi_lock:
            return _conflict(item)
        item.lock_id, item.lock_expires = None, None
    elif action == "RENAME_FILE" and data.get("w") and x_wopi_requestedname:
        from ..files import safe_display_name
        from ..services.spaces import unique_name

        if _lock_active(item) and x_wopi_lock and item.lock_id != x_wopi_lock:
            return _conflict(item)
        name = unique_name(db, item.space_id, item.folder_id,
                           f"{safe_display_name(x_wopi_requestedname)}.{item.file_type}", ignore_id=item.id)
        item.name = name
        db.commit()
        return JSONResponse({"Name": name.rsplit(".", 1)[0]})
    else:
        return Response(status_code=501)
    db.commit()
    return Response(status_code=200, headers={"X-WOPI-ItemVersion": str(item.version)})


# ---------- ONLYOFFICE ----------


@hooks.get("/onlyoffice/file/{file_id}")
def onlyoffice_file(file_id: int, db: DB, token: str = Query(...), authorization: str | None = Header(None)) -> Response:
    if settings.onlyoffice_jwt_secret:
        jwt_decode((authorization or "").removeprefix("Bearer ").strip(), settings.onlyoffice_jwt_secret)
    data = read_token(db, token, file_id)
    item = db.get(SpaceFile, file_id)
    if item is None or item.deleted_at is not None or db.get(User, data["u"]) is None:
        raise not_found("File")
    return Response(current_path(item).read_bytes(), media_type="application/octet-stream")


@hooks.post("/onlyoffice/callback/{file_id}")
async def onlyoffice_callback(file_id: int, request: Request, db: DB, token: str = Query(...)) -> dict:
    body = await request.json()
    if settings.onlyoffice_jwt_secret:
        signed = body.get("token") or (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        payload = jwt_decode(signed, settings.onlyoffice_jwt_secret)
        body = payload.get("payload", payload)
    data = read_token(db, token, file_id)
    item = db.get(SpaceFile, file_id)
    if item is None or item.deleted_at is not None:
        return {"error": 1}
    status = body.get("status")
    if status in (2, 6) and body.get("url"):
        if not data.get("w"):
            return {"error": 1}
        users = body.get("users") or [data["u"]]
        author = db.get(User, int(users[0])) if str(users[0]).isdigit() else db.get(User, data["u"])
        if checked_out_by_other(item, author):
            return {"error": 1}
        with urllib.request.urlopen(onlyoffice_download_url(body["url"]), timeout=60) as response:  # noqa: S310
            content = response.read()
        add_version(db, item, content, author, "editor")
        db.commit()
    return {"error": 0}

