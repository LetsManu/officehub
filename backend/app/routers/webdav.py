"""WebDAV: the files of my spaces as a network drive, and the way desktop programs (WordCraft, DeckCraft, office
programs) open and save a file directly in the portal – like SharePoint libraries opened in Word.

    https://portal.example/dav/<space>/<folder>/<file>

Sign-in with the e-mail address and an app password (Profile → Programs and network drive). Every save becomes a new
version, check-out is respected, and deleted files go to the space's trash as usual. Only the parts of WebDAV that
Windows Explorer, macOS Finder, Linux file managers and office programs use are supported (class 1 and 2).
"""

import base64
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..errors import ApiError
from ..files import MIME_TYPES, SPACE_TYPES, extension, matches_signature, safe_display_name
from ..models import Folder, Space, SpaceFile, User, utcnow
from ..services import app_passwords
from ..services.spaces import add_version, checked_out_by_other, current_path, my_space_ids, unique_name

router = APIRouter(prefix="/dav", include_in_schema=False)

PREFIX = "/dav"
METHODS = ["OPTIONS", "PROPFIND", "PROPPATCH", "GET", "HEAD", "PUT", "DELETE", "MKCOL", "MOVE", "COPY", "LOCK", "UNLOCK"]
LOCK_SECONDS = 3600
# Files programs and file managers create on their own; accepted but not stored
IGNORED = re.compile(r"^(\._.*|\.DS_Store|desktop\.ini|Thumbs\.db|~\$.*|\.~lock\..*#|.*\.tmp)$", re.IGNORECASE)


# ---------- sign-in ----------


def _user(request: Request, db) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        login, _, secret = base64.b64decode(header[6:]).decode().partition(":")
    except ValueError:
        return None
    return app_passwords.verify(db, login, secret) if login and secret else None


def _challenge() -> Response:
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="OfficeHub", charset="UTF-8"'})


# ---------- paths ----------


def _space_names(db, user: User) -> dict[str, Space]:
    """Folder names for my spaces; two spaces with the same name get their number added."""
    spaces = [s for s in (db.get(Space, i) for i in my_space_ids(db, user)) if s is not None]
    names: dict[str, Space] = {}
    for space in sorted(spaces, key=lambda s: s.id):
        name = safe_display_name(space.name)
        names[name if name not in names else f"{name} ({space.id})"] = space
    return names


def drive_path(db, user: User, item: SpaceFile) -> str | None:
    """Where a file is on the network drive (/dav/<space>/<folders>/<file>), or None outside my spaces."""
    space_name = next((n for n, s in _space_names(db, user).items() if s.id == item.space_id), None)
    if space_name is None:
        return None
    return _href(space_name, *_path_parts(db, Target(folder=db.get(Folder, item.folder_id) if item.folder_id else None)),
                 item.name)


class Target:
    """What a path points to: the root, a space, a folder or a file (or a missing name in an existing folder)."""

    def __init__(self, space: Space | None = None, folder: Folder | None = None, file: SpaceFile | None = None,
                 missing: str | None = None, name: str = "") -> None:
        self.space, self.folder, self.file, self.missing, self.name = space, folder, file, missing, name

    @property
    def is_collection(self) -> bool:
        return self.file is None and self.missing is None

    @property
    def folder_id(self) -> int | None:
        return self.folder.id if self.folder else None


def _children(db, space: Space, folder_id: int | None) -> tuple[list[Folder], list[SpaceFile]]:
    folders = list(db.scalars(select(Folder).where(
        Folder.space_id == space.id, Folder.deleted_at.is_(None),
        Folder.parent_id.is_(None) if folder_id is None else Folder.parent_id == folder_id).order_by(Folder.name)))
    files = list(db.scalars(select(SpaceFile).where(
        SpaceFile.space_id == space.id, SpaceFile.deleted_at.is_(None),
        SpaceFile.folder_id.is_(None) if folder_id is None else SpaceFile.folder_id == folder_id).order_by(SpaceFile.name)))
    return folders, files


def _resolve(db, user: User, path: str) -> Target | None:
    """None when the path does not exist (and is not a new name in an existing folder)."""
    parts = [unquote(p) for p in path.strip("/").split("/") if p]
    if not parts:
        return Target()
    space = _space_names(db, user).get(parts[0])
    if space is None:
        return None
    target = Target(space=space, name=parts[0])
    for i, part in enumerate(parts[1:], start=1):
        last = i == len(parts) - 1
        folders, files = _children(db, space, target.folder_id)
        folder = next((f for f in folders if f.name == part), None)
        if folder is not None:
            target = Target(space=space, folder=folder, name=part)
            continue
        file = next((f for f in files if f.name == part), None)
        if file is not None and last:
            return Target(space=space, folder=target.folder, file=file, name=part)
        if last:
            return Target(space=space, folder=target.folder, missing=part, name=part)
        return None
    return target


def _href(*parts: str, collection: bool = False) -> str:
    path = "/".join(quote(p) for p in parts if p)
    return f"{PREFIX}/{path}{'/' if collection and path else ''}" if path else f"{PREFIX}/"


def _path_parts(db, target: Target) -> list[str]:
    parts: list[str] = []
    folder = target.folder
    seen: set[int] = set()
    while folder is not None and folder.id not in seen:
        seen.add(folder.id)
        parts.insert(0, folder.name)
        folder = db.get(Folder, folder.parent_id) if folder.parent_id else None
    return parts


# ---------- PROPFIND ----------


def _http_date(value: datetime) -> str:
    return format_datetime(value.replace(tzinfo=timezone.utc), usegmt=True)


def _iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lock_xml(item: SpaceFile | None) -> str:
    if item is None or not _dav_lock_active(item):
        return "<D:lockdiscovery/>"
    token = item.lock_id.split(":", 2)[2]
    return ("<D:lockdiscovery><D:activelock><D:locktype><D:write/></D:locktype><D:lockscope><D:exclusive/></D:lockscope>"
            f"<D:depth>0</D:depth><D:timeout>Second-{LOCK_SECONDS}</D:timeout>"
            f"<D:locktoken><D:href>opaquelocktoken:{escape(token)}</D:href></D:locktoken></D:activelock></D:lockdiscovery>")


SUPPORTED_LOCK = ("<D:supportedlock><D:lockentry><D:lockscope><D:exclusive/></D:lockscope><D:locktype><D:write/>"
                  "</D:locktype></D:lockentry></D:supportedlock>")


def _response(href: str, name: str, collection: bool, modified: datetime, created: datetime,
              item: SpaceFile | None = None) -> str:
    props = [f"<D:displayname>{escape(name)}</D:displayname>",
             f"<D:getlastmodified>{_http_date(modified)}</D:getlastmodified>",
             f"<D:creationdate>{_iso(created)}</D:creationdate>", SUPPORTED_LOCK]
    if collection:
        props.append("<D:resourcetype><D:collection/></D:resourcetype>")
    else:
        props += ["<D:resourcetype/>", f"<D:getcontentlength>{item.size}</D:getcontentlength>",
                  f"<D:getcontenttype>{escape(MIME_TYPES.get(item.file_type, 'application/octet-stream').split(';')[0])}</D:getcontenttype>",
                  f'<D:getetag>"f{item.id}-{item.version}"</D:getetag>', _lock_xml(item)]
    return (f"<D:response><D:href>{escape(href)}</D:href><D:propstat><D:prop>{''.join(props)}</D:prop>"
            "<D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>")


def _multistatus(responses: list[str]) -> Response:
    body = '<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:">' + "".join(responses) + "</D:multistatus>"
    return Response(body, status_code=207, media_type="application/xml; charset=utf-8")


def _propfind(db, user: User, target: Target, depth: str) -> Response:
    now = utcnow()
    if target.space is None:
        responses = [_response(_href(), "OfficeHub", True, now, now)]
        if depth != "0":
            for name, space in _space_names(db, user).items():
                responses.append(_response(_href(name, collection=True), name, True, space.created_at, space.created_at))
        return _multistatus(responses)
    parts = _path_parts(db, target)
    space_name = next(n for n, s in _space_names(db, user).items() if s.id == target.space.id)
    if target.file is not None:
        return _multistatus([_response(_href(space_name, *parts, target.file.name), target.file.name, False,
                                       target.file.updated_at, target.file.created_at, target.file)])
    created = target.folder.created_at if target.folder else target.space.created_at
    responses = [_response(_href(space_name, *parts, collection=True), target.name, True, created, created)]
    if depth != "0":
        folders, files = _children(db, target.space, target.folder_id)
        for f in folders:
            responses.append(_response(_href(space_name, *parts, f.name, collection=True), f.name, True, f.created_at, f.created_at))
        for f in files:
            responses.append(_response(_href(space_name, *parts, f.name), f.name, False, f.updated_at, f.created_at, f))
    return _multistatus(responses)


# ---------- locks (stored like the office editors' locks, marked "dav:<user>:<token>") ----------


def _dav_lock_active(item: SpaceFile) -> bool:
    return bool(item.lock_id and item.lock_id.startswith("dav:") and item.lock_expires and item.lock_expires > utcnow())


def _lock_active(item: SpaceFile) -> bool:
    return bool(item.lock_id and item.lock_expires and item.lock_expires > utcnow())


def _held_by(item: SpaceFile, user: User) -> bool:
    return _dav_lock_active(item) and item.lock_id.split(":", 2)[1] == str(user.id)


def _blocked(item: SpaceFile, user: User) -> Response | None:
    """423 Locked when someone else checked the file out or has it open for editing."""
    if checked_out_by_other(item, user):
        return Response("Checked out by someone else", status_code=423)
    if _lock_active(item) and not _held_by(item, user):
        return Response("Locked", status_code=423)
    return None


# ---------- the handler ----------


def _writable(space: Space) -> bool:
    return not space.archived


@router.api_route("", methods=METHODS)
@router.api_route("/{path:path}", methods=METHODS)
async def dav(request: Request, path: str = "") -> Response:
    method = request.method
    if method == "OPTIONS":
        return Response(headers={"DAV": "1, 2", "MS-Author-Via": "DAV", "Allow": ", ".join(METHODS)})
    with SessionLocal() as db:
        user = _user(request, db)
        if user is None:
            return _challenge()
        try:
            return await _handle(request, db, user, method, path)
        except ApiError as e:
            return Response(e.detail if isinstance(e.detail, str) else "", status_code=e.status_code)


async def _handle(request: Request, db, user: User, method: str, path: str) -> Response:
    target = _resolve(db, user, path)
    if method == "PROPFIND":
        if target is None or target.missing is not None:
            return Response(status_code=404)
        return _propfind(db, user, target, request.headers.get("depth", "1"))
    if method == "PROPPATCH":
        return await _proppatch(request, path)
    if target is None:
        return Response(status_code=409 if method in ("PUT", "MKCOL") else 404)

    if method in ("GET", "HEAD"):
        if target.file is None:
            if target.missing is not None:
                return Response(status_code=404)
            return Response("OfficeHub WebDAV", media_type="text/plain")
        item = target.file
        data = b"" if method == "HEAD" or not item.versions else current_path(item).read_bytes()
        return Response(data, media_type=MIME_TYPES.get(item.file_type, "application/octet-stream"), headers={
            "ETag": f'"f{item.id}-{item.version}"', "Last-Modified": _http_date(item.updated_at),
            "Content-Length": str(item.size if method == "HEAD" else len(data)),
        })

    if target.space is None:
        return Response(status_code=403)  # the list of spaces itself cannot be changed
    if not _writable(target.space):
        return Response("This space is archived.", status_code=403)

    if method == "PUT":
        return await _put(request, db, user, target)
    if method == "MKCOL":
        if target.missing is None:
            return Response(status_code=405)
        db.add(Folder(space_id=target.space.id, parent_id=target.folder_id, name=safe_display_name(target.missing)[:80],
                      created_by_id=user.id))
        db.commit()
        return Response(status_code=201)
    if method == "DELETE":
        if target.missing is not None:
            return Response(status_code=404)
        if target.file is not None:
            if (blocked := _blocked(target.file, user)) is not None:
                return blocked
            target.file.deleted_at = utcnow()
        elif target.folder is not None:
            target.folder.deleted_at = utcnow()
        else:
            return Response(status_code=403)  # a whole space cannot be deleted from here
        db.commit()
        return Response(status_code=204)
    if method in ("MOVE", "COPY"):
        return _move_or_copy(request, db, user, target, copy=method == "COPY")
    if method == "LOCK":
        return await _lock(request, db, user, target)
    if method == "UNLOCK":
        if target.file is not None and _held_by(target.file, user):
            target.file.lock_id, target.file.lock_expires = None, None
            db.commit()
        return Response(status_code=204)
    return Response(status_code=405)


async def _body(request: Request) -> bytes | None:
    data = b""
    async for chunk in request.stream():
        data += chunk
        if len(data) > settings.max_upload_bytes:
            return None
    return data


async def _put(request: Request, db, user: User, target: Target) -> Response:
    name = target.file.name if target.file else (target.missing or "")
    if not name or target.is_collection:
        return Response(status_code=405)
    data = await _body(request)
    if data is None:
        return Response(f"Larger than {settings.max_upload_mb} MB.", status_code=413)
    if IGNORED.match(name):
        return Response(status_code=201)  # helper files of programs and file managers are not kept
    if target.file is not None:
        item = target.file
        if (blocked := _blocked(item, user)) is not None:
            return blocked
        if data and not matches_signature(item.file_type, data):
            return Response("The content does not match the file type.", status_code=415)
        add_version(db, item, data, user, "drive")
        db.commit()
        return Response(status_code=204, headers={"ETag": f'"f{item.id}-{item.version}"'})
    file_type = extension(name)
    if file_type not in SPACE_TYPES:
        return Response("This file type is not supported here.", status_code=415)
    if data and not matches_signature(file_type, data):
        return Response("The content does not match the file type.", status_code=415)
    item = SpaceFile(space_id=target.space.id, folder_id=target.folder_id, file_type=file_type, created_by_id=user.id,
                     name=unique_name(db, target.space.id, target.folder_id, safe_display_name(name)))
    db.add(item)
    add_version(db, item, data, user, "drive")
    db.commit()
    return Response(status_code=201, headers={"ETag": f'"f{item.id}-{item.version}"'})


def _move_or_copy(request: Request, db, user: User, source: Target, copy: bool) -> Response:
    if source.missing is not None:
        return Response(status_code=404)
    destination = urlparse(request.headers.get("destination", "")).path
    if not destination.startswith(PREFIX + "/"):
        return Response(status_code=400)
    dest = _resolve(db, user, destination[len(PREFIX):])
    if dest is None or dest.space is None or dest.space.id != source.space.id:
        return Response("Only within the same space.", status_code=502)
    overwrite = request.headers.get("overwrite", "T").upper() != "F"
    if dest.file is not None:
        if not overwrite:
            return Response(status_code=412)
        if dest.file is not source.file:
            if (blocked := _blocked(dest.file, user)) is not None:
                return blocked
            if not copy and source.file is not None and source.file.file_type == dest.file.file_type:
                # "Save" of many programs: write a temporary file, then move it over the original. Keep the original
                # (and its history) and store the new content as its next version.
                add_version(db, dest.file, current_path(source.file).read_bytes(), user, "drive")
                source.file.deleted_at = utcnow()
                db.commit()
                return Response(status_code=204)
            dest.file.deleted_at = utcnow()
    elif dest.missing is None:
        return Response(status_code=403)  # moving onto a folder
    new_name = safe_display_name(dest.missing or dest.file.name)
    if source.file is not None:
        if (blocked := _blocked(source.file, user)) is not None:
            return blocked
        if extension(new_name) != source.file.file_type:
            return Response("The file type cannot change.", status_code=403)
        if copy:
            item = SpaceFile(space_id=source.space.id, folder_id=dest.folder_id, file_type=source.file.file_type,
                             created_by_id=user.id, name=unique_name(db, source.space.id, dest.folder_id, new_name))
            db.add(item)
            add_version(db, item, current_path(source.file).read_bytes(), user, "drive")
        else:
            source.file.folder_id = dest.folder_id
            source.file.name = unique_name(db, source.space.id, dest.folder_id, new_name, ignore_id=source.file.id)
    elif source.folder is not None and not copy:
        # A folder cannot move into itself or below itself
        walk = dest.folder
        while walk is not None:
            if walk.id == source.folder.id:
                return Response(status_code=403)
            walk = db.get(Folder, walk.parent_id) if walk.parent_id else None
        source.folder.parent_id = dest.folder_id
        source.folder.name = new_name[:80]
    else:
        return Response(status_code=403)
    db.commit()
    return Response(status_code=201 if dest.file is None else 204)


async def _lock(request: Request, db, user: User, target: Target) -> Response:
    item = target.file
    if target.is_collection:
        return Response(status_code=403)
    if item is None:
        # Programs lock a new name before writing it: create the (empty) file so the lock has something to hold
        file_type = extension(target.missing or "")
        if IGNORED.match(target.missing or "") or file_type not in SPACE_TYPES:
            token = uuid.uuid4().hex
            return _lock_response(token, created=True)
        item = SpaceFile(space_id=target.space.id, folder_id=target.folder_id, file_type=file_type, created_by_id=user.id,
                         name=unique_name(db, target.space.id, target.folder_id, safe_display_name(target.missing or "")))
        db.add(item)
        add_version(db, item, b"", user, "drive")
        db.flush()
    if (blocked := _blocked(item, user)) is not None:
        return blocked
    token = item.lock_id.split(":", 2)[2] if _held_by(item, user) else uuid.uuid4().hex
    item.lock_id = f"dav:{user.id}:{token}"
    item.lock_expires = utcnow() + timedelta(seconds=LOCK_SECONDS)
    db.commit()
    return _lock_response(token, created=target.file is None)


def _lock_response(token: str, created: bool) -> Response:
    body = ('<?xml version="1.0" encoding="utf-8"?><D:prop xmlns:D="DAV:"><D:lockdiscovery><D:activelock>'
            "<D:locktype><D:write/></D:locktype><D:lockscope><D:exclusive/></D:lockscope><D:depth>0</D:depth>"
            f"<D:timeout>Second-{LOCK_SECONDS}</D:timeout><D:locktoken><D:href>opaquelocktoken:{token}</D:href>"
            "</D:locktoken></D:activelock></D:lockdiscovery></D:prop>")
    return Response(body, status_code=201 if created else 200, media_type="application/xml; charset=utf-8",
                    headers={"Lock-Token": f"<opaquelocktoken:{token}>"})


async def _proppatch(request: Request, path: str) -> Response:
    """Programs set times and attributes; they are accepted (the portal keeps its own) so saving does not fail."""
    body = await request.body()
    names: list[str] = []
    if 0 < len(body) <= 64_000:
        try:
            root = ElementTree.fromstring(body)
            for prop in root.iter("{DAV:}prop"):
                names += [child.tag for child in prop]
        except ElementTree.ParseError:
            pass
    props = "".join(_empty_prop(tag) for tag in names)
    href = f"{PREFIX}/{quote(path.strip('/'))}"
    return _multistatus([f"<D:response><D:href>{escape(href)}</D:href><D:propstat><D:prop>{props}</D:prop>"
                         "<D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"])


def _empty_prop(tag: str) -> str:
    if tag.startswith("{"):
        namespace, _, local = tag[1:].partition("}")
        return f'<p:{escape(local)} xmlns:p="{escape(namespace)}"/>'
    return f"<{escape(tag)}/>"
