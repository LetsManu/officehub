"""Opening files in ONLYOFFICE (optional office server), and the endpoints it calls back.

/office-hooks/... is only reachable inside the Docker network (the frontend web server forwards /api/ only).
Every call carries a signed token that names the file, the person and whether they may save.
"""

import urllib.request
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, StringConstraints

from ..config import settings
from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, not_found
from ..models import Space, SpaceFile, User
from ..services.audit import audit
from ..services.office import (
    EDITABLE,
    ONLYOFFICE_KIND,
    available,
    default_engine,
    jwt_decode,
    jwt_encode,
    make_token,
    onlyoffice_download_url,
    read_token,
)
from ..services import craft
from ..services.settings import get_setting, set_setting
from ..services.spaces import add_version, checked_out_by_other, current_path, get_file, lock_owner_id, role_in

router = APIRouter(prefix="/api/office", tags=["office"])
hooks = APIRouter(prefix="/office-hooks", tags=["office (internal)"])


class OfficeConfig(BaseModel):
    engines: list[str]
    default: str | None
    editable: dict[str, list[str]]
    craft: list[str] = []  # WordCraft / DeckCraft / GridCraft in the browser, when they run
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
    # Who has it open in WordCraft/DeckCraft or on the network drive, when that is why it opened read-only
    editing_by: str | None = None
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
    # Editing together works only inside the office editor; someone in WordCraft/DeckCraft or on the drive blocks it
    owner = lock_owner_id(item)
    editing_by = None
    if can_write and owner is not None and owner != user.id:
        person = db.get(User, owner)
        can_write, editing_by = False, person.full_name if person else ""
    token, _expires = make_token(db, item.id, user.id, can_write, body.origin)
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
    return OpenOut(engine=engine, can_write=can_write, file_name=item.name, editing_by=editing_by,
                   script="/onlyoffice/web-apps/apps/api/documents/api.js", config=config)


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

