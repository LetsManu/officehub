"""Wiki pages in a space: Markdown text with a full history.

Several people can have a page open at once. Everyone sees who else is editing, and a save that would
overwrite someone else's newer changes is refused, so nothing gets lost.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select

from ..deps import DB, CurrentUser
from ..errors import ApiError, not_found
from ..models import User, WikiEditor, WikiPage, WikiRevision, utcnow
from ..schemas import UserBrief, UtcDateTime
from ..services.spaces import get_space

router = APIRouter(tags=["wiki"])

PRESENCE_SECONDS = 30
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Body = Annotated[str, StringConstraints(max_length=200_000)]


class PageSummary(BaseModel):
    id: int
    title: str
    parent_id: int | None
    updated_at: UtcDateTime
    updated_by: str | None


class PageOut(PageSummary):
    space_id: int
    body: str
    version: int
    editors: list[UserBrief]
    can_write: bool


class PageIn(BaseModel):
    title: Title
    body: Body = ""
    parent_id: int | None = None


class PageUpdate(PageIn):
    base_version: int


class Presence(BaseModel):
    version: int
    updated_by: str | None
    editors: list[UserBrief]


class RevisionOut(BaseModel):
    version: int
    title: str
    author: str | None
    created_at: UtcDateTime


class RevisionDetail(RevisionOut):
    body: str


def _page(db: DB, user: User, page_id: int, write: bool = False) -> WikiPage:
    page = db.get(WikiPage, page_id)
    if page is None or page.deleted_at is not None:
        raise not_found("Page")
    get_space(db, user, page.space_id, write=write)
    return page


def _editors(db: DB, page: WikiPage, user: User) -> list[UserBrief]:
    since = utcnow() - timedelta(seconds=PRESENCE_SECONDS)
    rows = db.scalars(select(WikiEditor).where(WikiEditor.page_id == page.id, WikiEditor.seen_at >= since,
                                               WikiEditor.user_id != user.id))
    return [UserBrief.model_validate(r.user) for r in rows]


def _summary(page: WikiPage) -> PageSummary:
    return PageSummary(id=page.id, title=page.title, parent_id=page.parent_id, updated_at=page.updated_at,
                       updated_by=page.updated_by.full_name if page.updated_by else None)


def _out(db: DB, page: WikiPage, user: User) -> PageOut:
    from ..models import Space

    space = db.get(Space, page.space_id)
    return PageOut(**_summary(page).model_dump(), space_id=page.space_id, body=page.body, version=page.version,
                   editors=_editors(db, page, user), can_write=not space.archived)


def _check_parent(db: DB, space_id: int, page: WikiPage | None, parent_id: int | None) -> None:
    current = db.get(WikiPage, parent_id) if parent_id else None
    if parent_id and (current is None or current.space_id != space_id or current.deleted_at is not None):
        raise ApiError(422, "page_invalid", "This page does not exist.")
    seen: set[int] = set()
    while current is not None and current.id not in seen:
        if page is not None and current.id == page.id:
            raise ApiError(422, "page_cycle", "A page cannot be placed under itself.")
        seen.add(current.id)
        current = db.get(WikiPage, current.parent_id) if current.parent_id else None


@router.get("/api/spaces/{space_id}/pages", response_model=list[PageSummary])
def list_pages(space_id: int, user: CurrentUser, db: DB) -> list[PageSummary]:
    space = get_space(db, user, space_id)
    pages = db.scalars(select(WikiPage).where(WikiPage.space_id == space.id, WikiPage.deleted_at.is_(None)).order_by(WikiPage.title))
    return [_summary(p) for p in pages]


@router.post("/api/spaces/{space_id}/pages", response_model=PageOut, status_code=201)
def create_page(space_id: int, body: PageIn, user: CurrentUser, db: DB) -> PageOut:
    space = get_space(db, user, space_id, write=True)
    _check_parent(db, space.id, None, body.parent_id)
    page = WikiPage(space_id=space.id, parent_id=body.parent_id, title=body.title, body=body.body, updated_by_id=user.id)
    db.add(page)
    db.flush()
    db.add(WikiRevision(page_id=page.id, version=1, title=page.title, body=page.body, author_id=user.id))
    db.commit()
    return _out(db, page, user)


@router.get("/api/wiki/{page_id}", response_model=PageOut)
def get_page(page_id: int, user: CurrentUser, db: DB) -> PageOut:
    return _out(db, _page(db, user, page_id), user)


@router.put("/api/wiki/{page_id}", response_model=PageOut)
def save_page(page_id: int, body: PageUpdate, user: CurrentUser, db: DB) -> PageOut:
    page = _page(db, user, page_id, write=True)
    if body.base_version != page.version:
        raise ApiError(409, "page_conflict", "Someone saved this page in the meantime.")
    _check_parent(db, page.space_id, page, body.parent_id)
    if body.title == page.title and body.body == page.body and body.parent_id == page.parent_id:
        return _out(db, page, user)
    page.title, page.body, page.parent_id = body.title, body.body, body.parent_id
    page.version += 1
    page.updated_at, page.updated_by_id = utcnow(), user.id
    db.add(WikiRevision(page_id=page.id, version=page.version, title=page.title, body=page.body, author_id=user.id))
    db.commit()
    return _out(db, page, user)


@router.delete("/api/wiki/{page_id}", status_code=204)
def delete_page(page_id: int, user: CurrentUser, db: DB) -> None:
    page = _page(db, user, page_id, write=True)
    for child in db.scalars(select(WikiPage).where(WikiPage.parent_id == page.id)):
        child.parent_id = page.parent_id
    page.deleted_at = utcnow()
    db.commit()


@router.post("/api/wiki/{page_id}/presence", response_model=Presence)
def presence(page_id: int, user: CurrentUser, db: DB) -> Presence:
    """Called every few seconds while the page is open in the editor."""
    page = _page(db, user, page_id)
    row = db.scalar(select(WikiEditor).where(WikiEditor.page_id == page.id, WikiEditor.user_id == user.id))
    if row is None:
        db.add(WikiEditor(page_id=page.id, user_id=user.id))
    else:
        row.seen_at = utcnow()
    db.commit()
    return Presence(version=page.version, updated_by=page.updated_by.full_name if page.updated_by else None,
                    editors=_editors(db, page, user))


@router.delete("/api/wiki/{page_id}/presence", status_code=204)
def leave(page_id: int, user: CurrentUser, db: DB) -> None:
    page = _page(db, user, page_id)
    row = db.scalar(select(WikiEditor).where(WikiEditor.page_id == page.id, WikiEditor.user_id == user.id))
    if row is not None:
        db.delete(row)
        db.commit()


@router.get("/api/wiki/{page_id}/revisions", response_model=list[RevisionOut])
def revisions(page_id: int, user: CurrentUser, db: DB) -> list[RevisionOut]:
    page = _page(db, user, page_id)
    rows = db.scalars(select(WikiRevision).where(WikiRevision.page_id == page.id).order_by(WikiRevision.version.desc()))
    return [RevisionOut(version=r.version, title=r.title, author=r.author.full_name if r.author else None,
                        created_at=r.created_at) for r in rows]


@router.get("/api/wiki/{page_id}/revisions/{version}", response_model=RevisionDetail)
def revision(page_id: int, version: int, user: CurrentUser, db: DB) -> RevisionDetail:
    page = _page(db, user, page_id)
    r = db.scalar(select(WikiRevision).where(WikiRevision.page_id == page.id, WikiRevision.version == version))
    if r is None:
        raise not_found("Version")
    return RevisionDetail(version=r.version, title=r.title, author=r.author.full_name if r.author else None,
                          created_at=r.created_at, body=r.body)
