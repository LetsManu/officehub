"""Team spaces: members, folders and files with versions and a trash."""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select

from ..config import settings
from ..deps import DB, CurrentUser
from ..errors import ApiError, not_found
from ..files import INLINE_TYPES, MIME_TYPES, SPACE_TYPES, delete_quietly, extension, matches_signature, resolve, safe_display_name
from ..models import (
    PROJECT_COLORS,
    Board,
    BoardColumn,
    Card,
    Channel,
    ChannelMember,
    Folder,
    Message,
    Project,
    Space,
    SpaceFile,
    SpaceMember,
    User,
    WikiPage,
    utcnow,
)
from ..schemas import UserBrief, UtcDateTime
from ..services.audit import audit
from ..services.notifications import notify
from ..services.spaces import (
    add_version,
    current_path,
    folder_path,
    get_file,
    get_folder,
    get_space,
    in_deleted_folder,
    purge_trash,
    role_in,
    setup_space,
    template_bytes,
    unique_name,
)

router = APIRouter(prefix="/api/spaces", tags=["spaces"])

Name80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Name200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text300 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class SpaceIn(BaseModel):
    name: Name80
    description: Text300 = ""
    color: str = "blue"
    project_id: int | None = None
    archived: bool = False


class MemberOut(BaseModel):
    person: UserBrief
    role: str


class SpaceOut(BaseModel):
    id: int
    name: str
    description: str
    color: str
    project_id: int | None
    archived: bool
    my_role: str | None
    member_count: int
    file_count: int
    open_cards: int
    unread: int
    updated_at: UtcDateTime | None


class SpaceDetail(SpaceOut):
    members: list[MemberOut]
    board_id: int | None


class MemberIn(BaseModel):
    user_id: int
    role: str = "member"


class FolderOut(BaseModel):
    id: int
    name: str
    parent_id: int | None
    deleted_at: UtcDateTime | None = None


class VersionOut(BaseModel):
    number: int
    size: int
    source: str
    created_by: str | None
    created_at: UtcDateTime


class FileOut(BaseModel):
    id: int
    space_id: int
    folder_id: int | None
    name: str
    file_type: str
    size: int
    version: int
    updated_by: str | None
    updated_at: UtcDateTime
    deleted_at: UtcDateTime | None = None
    locked: bool = False


class FileDetail(FileOut):
    versions: list[VersionOut]
    path: list[FolderOut]


class Listing(BaseModel):
    folder: FolderOut | None
    path: list[FolderOut]
    folders: list[FolderOut]
    files: list[FileOut]
    can_write: bool


class FolderIn(BaseModel):
    name: Name80
    parent_id: int | None = None


class MoveIn(BaseModel):
    name: Name200
    folder_id: int | None = None


class NewFileIn(BaseModel):
    kind: str  # docx, xlsx, pptx, md
    name: Name200
    folder_id: int | None = None


class Activity(BaseModel):
    kind: str  # file, card, page, message
    title: str
    person: str | None
    at: UtcDateTime
    link: str


class Overview(BaseModel):
    files: list[FileOut]
    cards: list[dict]
    pages: list[dict]
    activity: list[Activity]


# ---------- helpers ----------


def _field_error(field: str, code: str, message: str) -> ApiError:
    error = ApiError(422, code, message)
    error.field = field  # type: ignore[attr-defined]
    return error


def _folder_out(f: Folder) -> FolderOut:
    return FolderOut(id=f.id, name=f.name, parent_id=f.parent_id, deleted_at=f.deleted_at)


def _file_out(f: SpaceFile) -> FileOut:
    return FileOut(
        id=f.id, space_id=f.space_id, folder_id=f.folder_id, name=f.name, file_type=f.file_type, size=f.size,
        version=f.version, updated_by=f.updated_by.full_name if f.updated_by else None, updated_at=f.updated_at,
        deleted_at=f.deleted_at, locked=bool(f.lock_id and f.lock_expires and f.lock_expires > utcnow()),
    )


def _space_out(db: DB, user: User, space: Space, cls=SpaceOut, **extra) -> SpaceOut:
    def count(query) -> int:
        return db.scalar(select(func.count()).select_from(query.subquery())) or 0

    boards = select(Board.id).where(Board.space_id == space.id)
    open_cards = count(select(Card.id).join(BoardColumn).where(BoardColumn.board_id.in_(boards), BoardColumn.is_done.is_(False)))
    channels = list(db.scalars(select(Channel.id).where(Channel.space_id == space.id)))
    unread = 0
    for cid in channels:
        last = db.scalar(select(ChannelMember.last_read_id).where(ChannelMember.channel_id == cid, ChannelMember.user_id == user.id)) or 0
        unread += count(select(Message.id).where(Message.channel_id == cid, Message.id > last, Message.author_id != user.id,
                                                 Message.deleted.is_(False)))
    updated = db.scalar(select(func.max(SpaceFile.updated_at)).where(SpaceFile.space_id == space.id))
    return cls(
        id=space.id, name=space.name, description=space.description, color=space.color, project_id=space.project_id,
        archived=space.archived, my_role=role_in(db, user, space),
        member_count=count(select(SpaceMember.id).where(SpaceMember.space_id == space.id)),
        file_count=count(select(SpaceFile.id).where(SpaceFile.space_id == space.id, SpaceFile.deleted_at.is_(None))),
        open_cards=open_cards, unread=unread, updated_at=updated or space.created_at, **extra,
    )


def _check_space_body(db: DB, body: SpaceIn) -> None:
    if body.color not in PROJECT_COLORS:
        raise _field_error("color", "invalid_choice", "Please choose one of the colours.")
    if body.project_id is not None and db.get(Project, body.project_id) is None:
        raise _field_error("project_id", "project_required", "Please choose a project.")


def _managers(db: DB, space_id: int) -> int:
    return db.scalar(select(func.count()).select_from(SpaceMember).where(
        SpaceMember.space_id == space_id, SpaceMember.role == "manager")) or 0


async def _read_upload(upload: UploadFile) -> tuple[str, str, bytes]:
    name = safe_display_name(upload.filename or "")
    file_type = extension(name)
    if file_type not in SPACE_TYPES:
        allowed = ", ".join(sorted(t.upper() for t in SPACE_TYPES))
        raise ApiError(422, "file_type", f"This file type is not supported. Allowed: {allowed}.")
    data = await upload.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ApiError(422, "file_too_large", f"The file is larger than {settings.max_upload_mb} MB.")
    if not data:
        raise ApiError(422, "file_empty", "The file is empty.")
    if not matches_signature(file_type, data):
        raise ApiError(422, "file_invalid", "The file content does not match its file type.")
    return name, file_type, data


# ---------- spaces ----------


@router.get("", response_model=list[SpaceOut])
def list_spaces(user: CurrentUser, db: DB, archived: bool = False) -> list[SpaceOut]:
    query = select(Space).where(Space.archived.is_(archived)).order_by(Space.name)
    if not user.is_admin:
        query = query.where(Space.id.in_(select(SpaceMember.space_id).where(SpaceMember.user_id == user.id)))
    return [_space_out(db, user, s) for s in db.scalars(query)]


@router.post("", response_model=SpaceOut, status_code=201)
def create_space(body: SpaceIn, user: CurrentUser, db: DB) -> SpaceOut:
    _check_space_body(db, body)
    space = Space(name=body.name, description=body.description, color=body.color, project_id=body.project_id,
                  created_by_id=user.id)
    db.add(space)
    db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id, role="manager"))
    setup_space(db, space, user, user.language)
    audit(db, user, "space_created", space.name)
    db.commit()
    return _space_out(db, user, space)


@router.get("/{space_id}", response_model=SpaceDetail)
def space_detail(space_id: int, user: CurrentUser, db: DB) -> SpaceDetail:
    space = get_space(db, user, space_id)
    members = db.scalars(select(SpaceMember).where(SpaceMember.space_id == space.id)).all()
    members = sorted(members, key=lambda m: (m.role != "manager", m.user.last_name, m.user.first_name))
    board_id = db.scalar(select(Board.id).where(Board.space_id == space.id).order_by(Board.id))
    return _space_out(db, user, space, SpaceDetail,
                      members=[MemberOut(person=UserBrief.model_validate(m.user), role=m.role) for m in members],
                      board_id=board_id)


@router.put("/{space_id}", response_model=SpaceOut)
def update_space(space_id: int, body: SpaceIn, user: CurrentUser, db: DB) -> SpaceOut:
    space = get_space(db, user, space_id, manage=True)
    _check_space_body(db, body)
    space.name, space.description, space.color = body.name, body.description, body.color
    space.project_id, space.archived = body.project_id, body.archived
    db.commit()
    return _space_out(db, user, space)


@router.delete("/{space_id}", status_code=204)
def delete_space(space_id: int, user: CurrentUser, db: DB) -> None:
    space = get_space(db, user, space_id, manage=True)
    if not space.archived:
        raise ApiError(409, "space_not_archived", "Archive the space first. Then it can be deleted.")
    for item in db.scalars(select(SpaceFile).where(SpaceFile.space_id == space.id)):
        for v in item.versions:
            delete_quietly(v.path)
    audit(db, user, "space_deleted", space.name)
    db.delete(space)
    db.commit()


@router.get("/{space_id}/overview", response_model=Overview)
def overview(space_id: int, user: CurrentUser, db: DB) -> Overview:
    space = get_space(db, user, space_id)
    files = db.scalars(select(SpaceFile).where(SpaceFile.space_id == space.id, SpaceFile.deleted_at.is_(None))
                       .order_by(SpaceFile.updated_at.desc()).limit(6)).all()
    boards = select(Board.id).where(Board.space_id == space.id)
    cards = db.scalars(
        select(Card).join(BoardColumn).where(BoardColumn.board_id.in_(boards), BoardColumn.is_done.is_(False))
        .order_by(Card.due_date.is_(None), Card.due_date, Card.updated_at.desc()).limit(6)
    ).all()
    pages = db.scalars(select(WikiPage).where(WikiPage.space_id == space.id, WikiPage.deleted_at.is_(None))
                       .order_by(WikiPage.updated_at.desc()).limit(5)).all()
    activity: list[Activity] = []
    for f in files:
        activity.append(Activity(kind="file", title=f.name, person=f.updated_by.full_name if f.updated_by else None,
                                 at=f.updated_at, link=f"/spaces/{space.id}/files?file={f.id}"))
    for p in pages:
        activity.append(Activity(kind="page", title=p.title, person=p.updated_by.full_name if p.updated_by else None,
                                 at=p.updated_at, link=f"/spaces/{space.id}/wiki/{p.id}"))
    for c in cards:
        activity.append(Activity(kind="card", title=c.title, person=None, at=c.updated_at,
                                 link=f"/spaces/{space.id}/board?card={c.id}"))
    activity.sort(key=lambda a: a.at, reverse=True)
    return Overview(
        files=[_file_out(f) for f in files],
        cards=[{"id": c.id, "title": c.title, "due_date": c.due_date, "column": c.column.name,
                "assignees": [a.user.full_name for a in c.assignees]} for c in cards],
        pages=[{"id": p.id, "title": p.title, "updated_at": p.updated_at.isoformat() + "Z"} for p in pages],
        activity=activity[:10],
    )


# ---------- members ----------


@router.post("/{space_id}/members", response_model=SpaceDetail)
def add_member(space_id: int, body: MemberIn, user: CurrentUser, db: DB) -> SpaceDetail:
    space = get_space(db, user, space_id, manage=True, write=True)
    person = db.get(User, body.user_id)
    if person is None or not person.is_active:
        raise _field_error("user_id", "person_required", "Please choose a person.")
    if body.role not in ("manager", "member"):
        raise _field_error("role", "invalid_choice", "Please choose a role.")
    member = db.scalar(select(SpaceMember).where(SpaceMember.space_id == space.id, SpaceMember.user_id == person.id))
    if member is None:
        db.add(SpaceMember(space_id=space.id, user_id=person.id, role=body.role))
        if person.id != user.id:
            notify(db, person.id, "space_added", {"name": user.full_name, "space": space.name}, link=f"/spaces/{space.id}")
    else:
        member.role = body.role
    db.commit()
    return space_detail(space_id, user, db)


@router.delete("/{space_id}/members/{user_id}", response_model=SpaceDetail | None)
def remove_member(space_id: int, user_id: int, user: CurrentUser, db: DB) -> SpaceDetail | None:
    leaving = user_id == user.id
    space = get_space(db, user, space_id, manage=not leaving)
    member = db.scalar(select(SpaceMember).where(SpaceMember.space_id == space.id, SpaceMember.user_id == user_id))
    if member is None:
        raise not_found("Member")
    if member.role == "manager" and _managers(db, space.id) <= 1:
        raise ApiError(409, "last_manager", "A space needs at least one manager. Make someone else manager first.")
    db.delete(member)
    db.commit()
    return None if leaving else space_detail(space_id, user, db)


# ---------- folders and files ----------


@router.get("/{space_id}/files", response_model=Listing)
def list_files(space_id: int, user: CurrentUser, db: DB, folder_id: int | None = None) -> Listing:
    space = get_space(db, user, space_id)
    folder = get_folder(db, space.id, folder_id)
    folders = db.scalars(select(Folder).where(
        Folder.space_id == space.id, Folder.deleted_at.is_(None),
        Folder.parent_id.is_(None) if folder is None else Folder.parent_id == folder.id,
    ).order_by(func.lower(Folder.name))).all()
    files = db.scalars(select(SpaceFile).where(
        SpaceFile.space_id == space.id, SpaceFile.deleted_at.is_(None),
        SpaceFile.folder_id.is_(None) if folder is None else SpaceFile.folder_id == folder.id,
    ).order_by(func.lower(SpaceFile.name))).all()
    return Listing(
        folder=_folder_out(folder) if folder else None, path=[_folder_out(f) for f in folder_path(db, folder)],
        folders=[_folder_out(f) for f in folders], files=[_file_out(f) for f in files], can_write=not space.archived,
    )


@router.post("/{space_id}/folders", response_model=FolderOut, status_code=201)
def create_folder(space_id: int, body: FolderIn, user: CurrentUser, db: DB) -> FolderOut:
    space = get_space(db, user, space_id, write=True)
    get_folder(db, space.id, body.parent_id)
    folder = Folder(space_id=space.id, parent_id=body.parent_id, name=safe_display_name(body.name), created_by_id=user.id)
    db.add(folder)
    db.commit()
    return _folder_out(folder)


@router.put("/folders/{folder_id}", response_model=FolderOut)
def rename_folder(folder_id: int, body: FolderIn, user: CurrentUser, db: DB) -> FolderOut:
    folder = db.get(Folder, folder_id)
    if folder is None or folder.deleted_at is not None:
        raise not_found("Folder")
    get_space(db, user, folder.space_id, write=True)
    parent = get_folder(db, folder.space_id, body.parent_id)
    if parent is not None and any(f.id == folder.id for f in folder_path(db, parent)):
        raise _field_error("parent_id", "folder_cycle", "A folder cannot be moved into itself.")
    folder.name, folder.parent_id = safe_display_name(body.name), body.parent_id
    db.commit()
    return _folder_out(folder)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: int, user: CurrentUser, db: DB) -> None:
    folder = db.get(Folder, folder_id)
    if folder is None or folder.deleted_at is not None:
        raise not_found("Folder")
    get_space(db, user, folder.space_id, write=True)
    folder.deleted_at = utcnow()
    db.commit()


@router.post("/{space_id}/files", response_model=FileOut, status_code=201)
async def upload_file(space_id: int, user: CurrentUser, db: DB, file: UploadFile = File(...),
                      folder_id: int | None = Form(None)) -> FileOut:
    space = get_space(db, user, space_id, write=True)
    get_folder(db, space.id, folder_id)
    name, file_type, data = await _read_upload(file)
    # Uploading a file with the same name again adds a new version, like in other file shares.
    existing = db.scalar(select(SpaceFile).where(
        SpaceFile.space_id == space.id, SpaceFile.name == name, SpaceFile.deleted_at.is_(None),
        SpaceFile.folder_id.is_(None) if folder_id is None else SpaceFile.folder_id == folder_id,
    ))
    if existing is not None:
        if existing.lock_id and existing.lock_expires and existing.lock_expires > utcnow():
            raise ApiError(409, "file_locked", "Someone is editing this file right now. Please try again later.")
        add_version(db, existing, data, user, "upload")
        db.commit()
        return _file_out(existing)
    item = SpaceFile(space_id=space.id, folder_id=folder_id, name=name, file_type=file_type, created_by_id=user.id)
    db.add(item)
    add_version(db, item, data, user, "upload")
    db.commit()
    return _file_out(item)


@router.post("/{space_id}/files/new", response_model=FileOut, status_code=201)
def new_file(space_id: int, body: NewFileIn, user: CurrentUser, db: DB) -> FileOut:
    space = get_space(db, user, space_id, write=True)
    get_folder(db, space.id, body.folder_id)
    if body.kind not in ("docx", "xlsx", "pptx", "md"):
        raise _field_error("kind", "invalid_choice", "Please choose a type.")
    base = safe_display_name(body.name)
    name = base if base.lower().endswith(f".{body.kind}") else f"{base}.{body.kind}"
    item = SpaceFile(space_id=space.id, folder_id=body.folder_id, name=unique_name(db, space.id, body.folder_id, name),
                     file_type=body.kind, created_by_id=user.id)
    db.add(item)
    add_version(db, item, template_bytes(body.kind) or f"# {base}\n".encode(), user, "new")
    db.commit()
    return _file_out(item)


@router.get("/files/{file_id}", response_model=FileDetail)
def file_detail(file_id: int, user: CurrentUser, db: DB) -> FileDetail:
    item = get_file(db, user, file_id)
    out = _file_out(item)
    return FileDetail(
        **out.model_dump(),
        versions=[VersionOut(number=v.number, size=v.size, source=v.source,
                             created_by=v.created_by.full_name if v.created_by else None, created_at=v.created_at)
                  for v in item.versions],
        path=[_folder_out(f) for f in folder_path(db, db.get(Folder, item.folder_id) if item.folder_id else None)],
    )


@router.get("/files/{file_id}/download")
def download(file_id: int, user: CurrentUser, db: DB, version: int | None = None, inline: bool = False) -> FileResponse:
    item = get_file(db, user, file_id)
    if version is None:
        path = current_path(item)
    else:
        match = next((v for v in item.versions if v.number == version), None)
        if match is None:
            raise not_found("Version")
        path = resolve(match.path)
    disposition = "inline" if inline and item.file_type in INLINE_TYPES else "attachment"
    response = FileResponse(path, media_type=MIME_TYPES.get(item.file_type, "application/octet-stream"),
                            filename=item.name, content_disposition_type=disposition)
    if item.file_type != "pdf":  # browsers' PDF viewers do not run in a sandbox
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.put("/files/{file_id}", response_model=FileOut)
def move_file(file_id: int, body: MoveIn, user: CurrentUser, db: DB) -> FileOut:
    item = get_file(db, user, file_id, write=True)
    get_folder(db, item.space_id, body.folder_id)
    name = safe_display_name(body.name)
    if extension(name) != item.file_type:
        name = f"{name}.{item.file_type}"
    item.folder_id = body.folder_id
    item.name = unique_name(db, item.space_id, body.folder_id, name, ignore_id=item.id)
    db.commit()
    return _file_out(item)


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: int, user: CurrentUser, db: DB) -> None:
    item = get_file(db, user, file_id, write=True)
    if item.lock_id and item.lock_expires and item.lock_expires > utcnow():
        raise ApiError(409, "file_locked", "Someone is editing this file right now. Please try again later.")
    item.deleted_at = utcnow()
    db.commit()


@router.post("/files/{file_id}/restore-version", response_model=FileOut)
def restore_version(file_id: int, user: CurrentUser, db: DB, version: int) -> FileOut:
    item = get_file(db, user, file_id, write=True)
    match = next((v for v in item.versions if v.number == version), None)
    if match is None:
        raise not_found("Version")
    if item.lock_id and item.lock_expires and item.lock_expires > utcnow():
        raise ApiError(409, "file_locked", "Someone is editing this file right now. Please try again later.")
    add_version(db, item, resolve(match.path).read_bytes(), user, "restore")
    db.commit()
    return _file_out(item)


# ---------- trash ----------


class Trash(BaseModel):
    folders: list[FolderOut]
    files: list[FileOut]


@router.get("/{space_id}/trash", response_model=Trash)
def trash(space_id: int, user: CurrentUser, db: DB) -> Trash:
    space = get_space(db, user, space_id)
    purge_trash(db, space.id)
    db.commit()
    folders = db.scalars(select(Folder).where(Folder.space_id == space.id, Folder.deleted_at.is_not(None))
                         .order_by(Folder.deleted_at.desc())).all()
    files = db.scalars(select(SpaceFile).where(SpaceFile.space_id == space.id, SpaceFile.deleted_at.is_not(None))
                       .order_by(SpaceFile.deleted_at.desc())).all()
    return Trash(folders=[_folder_out(f) for f in folders], files=[_file_out(f) for f in files])


@router.post("/files/{file_id}/restore", response_model=FileOut)
def restore_file(file_id: int, user: CurrentUser, db: DB) -> FileOut:
    item = get_file(db, user, file_id, include_deleted=True, write=True)
    if in_deleted_folder(db, item.folder_id):
        item.folder_id = None  # the folder is gone: put the file back at the top
    item.deleted_at = None
    item.name = unique_name(db, item.space_id, item.folder_id, item.name, ignore_id=item.id)
    db.commit()
    return _file_out(item)


@router.post("/folders/{folder_id}/restore", response_model=FolderOut)
def restore_folder(folder_id: int, user: CurrentUser, db: DB) -> FolderOut:
    folder = db.get(Folder, folder_id)
    if folder is None:
        raise not_found("Folder")
    get_space(db, user, folder.space_id, write=True)
    if in_deleted_folder(db, folder.parent_id):
        folder.parent_id = None
    folder.deleted_at = None
    db.commit()
    return _folder_out(folder)


@router.delete("/files/{file_id}/forever", status_code=204)
def delete_forever(file_id: int, user: CurrentUser, db: DB) -> None:
    item = get_file(db, user, file_id, include_deleted=True)
    get_space(db, user, item.space_id, manage=True)
    if item.deleted_at is None:
        raise ApiError(409, "not_in_trash", "Move the file to the trash first.")
    for v in item.versions:
        delete_quietly(v.path)
    db.delete(item)
    db.commit()
