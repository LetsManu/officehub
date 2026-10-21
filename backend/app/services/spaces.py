"""Team spaces: who may do what, storing file versions and the starter content of a new space."""

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError, forbidden, not_found
from ..files import extract_text, resolve, write_file
from ..models import (
    Board,
    BoardColumn,
    Channel,
    FileVersion,
    Folder,
    Space,
    SpaceFile,
    SpaceMember,
    User,
    WikiPage,
    WikiRevision,
    utcnow,
)

TRASH_DAYS = 30
TEMPLATES = Path(__file__).resolve().parent.parent / "office_templates"


def role_in(db: Session, user: User, space: Space) -> str | None:
    """"manager", "member" or None. HR/admins manage every space."""
    member = db.scalar(select(SpaceMember).where(SpaceMember.space_id == space.id, SpaceMember.user_id == user.id))
    if member is not None:
        return member.role
    return "manager" if user.is_admin else None


def get_space(db: Session, user: User, space_id: int, *, manage: bool = False, write: bool = False) -> Space:
    """The space if the user may see it (and manage it, or change content in it)."""
    space = db.get(Space, space_id)
    if space is None:
        raise not_found("Space")
    role = role_in(db, user, space)
    if role is None:
        raise not_found("Space")  # don't reveal that a private space exists
    if manage and role != "manager":
        raise forbidden("Only the managers of this space can do this.")
    if write and space.archived:
        raise ApiError(409, "space_archived", "This space is archived. Restore it to make changes.")
    return space


def member_ids(db: Session, space_id: int) -> list[int]:
    return list(db.scalars(select(SpaceMember.user_id).where(SpaceMember.space_id == space_id)))


def my_space_ids(db: Session, user: User) -> list[int]:
    return list(db.scalars(select(SpaceMember.space_id).where(SpaceMember.user_id == user.id)))


def get_file(db: Session, user: User, file_id: int, *, write: bool = False, include_deleted: bool = False) -> SpaceFile:
    item = db.get(SpaceFile, file_id)
    if item is None or (item.deleted_at is not None and not include_deleted):
        raise not_found("File")
    get_space(db, user, item.space_id, write=write)
    return item


def get_folder(db: Session, space_id: int, folder_id: int | None) -> Folder | None:
    if folder_id is None:
        return None
    folder = db.get(Folder, folder_id)
    if folder is None or folder.space_id != space_id or folder.deleted_at is not None:
        raise ApiError(422, "folder_invalid", "This folder does not exist.")
    return folder


def folder_path(db: Session, folder: Folder | None) -> list[Folder]:
    path: list[Folder] = []
    seen: set[int] = set()
    while folder is not None and folder.id not in seen:
        seen.add(folder.id)
        path.insert(0, folder)
        folder = db.get(Folder, folder.parent_id) if folder.parent_id else None
    return path


def in_deleted_folder(db: Session, folder_id: int | None) -> bool:
    for folder in folder_path(db, db.get(Folder, folder_id) if folder_id else None):
        if folder.deleted_at is not None:
            return True
    return False


def add_version(db: Session, item: SpaceFile, data: bytes, user: User | None, source: str) -> FileVersion:
    """Store new content as the next version and make it current."""
    number = (item.version or 0) + 1 if item.id and item.versions else 1
    version = FileVersion(
        number=number, path=write_file(f"spaces/{item.space_id}", item.file_type, data), size=len(data),
        source=source, created_by_id=user.id if user else None,
    )
    item.versions.append(version)
    item.version, item.size = number, len(data)
    item.updated_at, item.updated_by_id = utcnow(), user.id if user else None
    item.content_text = extract_text(item.file_type, data)[:200_000]
    return version


def checked_out_by_other(item: SpaceFile, user: User | None) -> bool:
    return item.checked_out_by_id is not None and (user is None or item.checked_out_by_id != user.id)


def ensure_can_change(item: SpaceFile, user: User | None) -> None:
    """Nobody but the person who checked a file out may save it, rename, move or delete it."""
    if checked_out_by_other(item, user):
        name = item.checked_out_by.full_name if item.checked_out_by else "?"
        raise ApiError(423, "file_checked_out", f"{name} has checked out this file. It can be changed again after check-in.")
    if item.lock_id and item.lock_expires and item.lock_expires > utcnow():
        raise ApiError(409, "file_locked", "Someone is editing this file right now. Please try again later.")


def current_path(item: SpaceFile) -> Path:
    version = next((v for v in item.versions if v.number == item.version), None)
    if version is None:
        raise ApiError(404, "file_missing", "The file could not be found.")
    return resolve(version.path)


def unique_name(db: Session, space_id: int, folder_id: int | None, name: str, ignore_id: int | None = None) -> str:
    """Add " (2)", " (3)" … so two files in one folder never share a name."""
    taken = set(db.scalars(select(SpaceFile.name).where(
        SpaceFile.space_id == space_id, SpaceFile.folder_id.is_(None) if folder_id is None else SpaceFile.folder_id == folder_id,
        SpaceFile.deleted_at.is_(None), SpaceFile.id != (ignore_id or 0),
    )))
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while True:
        candidate = f"{stem} ({n}){'.' + ext if ext else ''}"
        if candidate not in taken:
            return candidate
        n += 1


def template_bytes(kind: str) -> bytes:
    if kind in ("docx", "xlsx", "pptx"):
        return (TEMPLATES / f"blank.{kind}").read_bytes()
    return b""


def purge_trash(db: Session, space_id: int) -> None:
    """Remove files and folders that have been in the trash for more than 30 days."""
    from ..files import delete_quietly

    limit = utcnow() - timedelta(days=TRASH_DAYS)
    for item in db.scalars(select(SpaceFile).where(SpaceFile.space_id == space_id, SpaceFile.deleted_at < limit)):
        for v in item.versions:
            delete_quietly(v.path)
        db.delete(item)
    for folder in db.scalars(select(Folder).where(Folder.space_id == space_id, Folder.deleted_at < limit)):
        db.delete(folder)


def setup_space(db: Session, space: Space, creator: User, language: str) -> None:
    """A new space starts with a task board, a general chat channel and a welcome page."""
    de = language == "de"
    board = Board(space_id=space.id, name="Aufgaben" if de else "Tasks")
    db.add(board)
    db.flush()
    for i, (name_de, name_en, done) in enumerate((("Zu erledigen", "To do", False), ("In Arbeit", "In progress", False),
                                                  ("Erledigt", "Done", True))):
        db.add(BoardColumn(board_id=board.id, name=name_de if de else name_en, position=i, is_done=done))
    db.add(Channel(space_id=space.id, name="Allgemein" if de else "General"))
    body = (
        f"# {space.name}\n\nWillkommen im Bereich! Hier könnt ihr festhalten, was alle wissen sollten:\n\n"
        "- Wofür ist dieser Bereich da?\n- Wer ist wofür zuständig?\n- Wichtige Links und Abläufe\n"
        if de else
        f"# {space.name}\n\nWelcome to the space! Write down what everyone should know:\n\n"
        "- What is this space for?\n- Who is responsible for what?\n- Important links and routines\n"
    )
    page = WikiPage(space_id=space.id, title="Startseite" if de else "Start page", body=body, updated_by_id=creator.id)
    db.add(page)
    db.flush()
    db.add(WikiRevision(page_id=page.id, version=1, title=page.title, body=body, author_id=creator.id))
