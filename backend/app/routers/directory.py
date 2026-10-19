"""Colleague directory, org chart and phone list (one data source for all three)."""

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_, select

from ..deps import DB, CurrentUser
from ..errors import not_found
from ..files import MIME_TYPES, resolve
from ..models import User

router = APIRouter(prefix="/api/directory", tags=["directory"])


class DirectoryEntry(BaseModel):
    id: int
    first_name: str
    last_name: str
    full_name: str
    department: str
    job_title: str
    office_location: str
    email: str
    phone: str
    mobile: str
    manager_id: int | None
    photo_version: str | None = None


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def to_entry(person: User, viewer: User) -> DirectoryEntry:
    # People decide which numbers others see; HR always sees them.
    is_self_or_hr = viewer.id == person.id or viewer.is_admin
    return DirectoryEntry(
        id=person.id,
        first_name=person.first_name,
        last_name=person.last_name,
        full_name=person.full_name,
        department=person.department,
        job_title=person.job_title,
        office_location=person.office_location,
        email=person.email,
        phone=person.phone if (person.show_phone or is_self_or_hr) else "",
        mobile=person.mobile if (person.show_mobile or is_self_or_hr) else "",
        manager_id=person.manager_id,
        photo_version=person.photo_version,
    )


@router.get("", response_model=list[DirectoryEntry])
def list_people(
    user: CurrentUser,
    db: DB,
    q: str | None = Query(None, max_length=100),
    department: str | None = Query(None, max_length=80),
) -> list[DirectoryEntry]:
    query = select(User).where(User.is_active.is_(True))
    if department:
        query = query.where(User.department == department)
    term = (q or "").strip()
    if term:
        pattern = f"%{_escape_like(term)}%"
        query = query.where(
            or_(
                User.first_name.ilike(pattern, escape="\\"),
                User.last_name.ilike(pattern, escape="\\"),
                User.department.ilike(pattern, escape="\\"),
                User.job_title.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
                User.phone.ilike(pattern, escape="\\"),
            )
        )
    people = db.scalars(query.order_by(User.last_name, User.first_name)).all()
    return [to_entry(p, user) for p in people]


@router.get("/departments", response_model=list[str])
def departments(user: CurrentUser, db: DB) -> list[str]:
    rows = db.scalars(select(User.department).where(User.is_active.is_(True), User.department != "").distinct())
    return sorted(rows)


@router.get("/{person_id}/photo")
def photo(person_id: int, user: CurrentUser, db: DB) -> FileResponse:
    person = db.get(User, person_id)
    if person is None or not person.photo_path:
        raise not_found("Photo")
    file_type = person.photo_path.rsplit(".", 1)[-1]
    # The URL carries the photo version, so the browser may keep it for a day.
    return FileResponse(resolve(person.photo_path), media_type=MIME_TYPES.get(file_type), headers={"Cache-Control": "private, max-age=86400"})
