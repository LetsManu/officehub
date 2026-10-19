"""Notification centre, badge counts and the global search."""

import json
from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update

from ..deps import DB, CurrentUser
from ..errors import not_found
from ..models import (
    PENDING_STATUSES,
    Announcement,
    Document,
    Notification,
    PersonalDocument,
    QuickLink,
    Request,
    Review,
    User,
    Visitor,
    utcnow,
)
from ..schemas import UtcDateTime
from .announcements import open_must_read
from .directory import DirectoryEntry, to_entry

router = APIRouter(prefix="/api", tags=["notifications"])

SEARCH_LIMIT = 5


class NotificationOut(BaseModel):
    id: int
    kind: str
    params: dict
    link: str
    read: bool
    created_at: UtcDateTime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


class Summary(BaseModel):
    unread: int
    approvals_pending: int
    reviews_todo: int
    visitors_today: int
    must_read_open: int
    personal_documents_new: int


def _out(item: Notification) -> NotificationOut:
    return NotificationOut(
        id=item.id,
        kind=item.kind,
        params=json.loads(item.params or "{}"),
        link=item.link,
        read=item.read_at is not None,
        created_at=item.created_at,
    )


def _unread(db, user: User) -> int:
    return db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    ) or 0


@router.get("/notifications", response_model=NotificationList)
def list_notifications(user: CurrentUser, db: DB, limit: int = Query(30, ge=1, le=100)) -> NotificationList:
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    ).all()
    return NotificationList(items=[_out(r) for r in rows], unread=_unread(db, user))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, user: CurrentUser, db: DB) -> NotificationOut:
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != user.id:
        raise not_found("Notification")
    if item.read_at is None:
        item.read_at = utcnow()
        db.commit()
    return _out(item)


@router.post("/notifications/read-all", status_code=204)
def mark_all_read(user: CurrentUser, db: DB) -> None:
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()


@router.get("/me/summary", response_model=Summary)
def summary(user: CurrentUser, db: DB) -> Summary:
    """Small counts for the badges in the navigation."""

    def count(query) -> int:
        return db.scalar(select(func.count()).select_from(query.subquery())) or 0

    approvals = 0
    if user.is_approver:
        approvals = count(select(Request.id).where(Request.status.in_(PENDING_STATUSES), Request.requester_id != user.id))
    reviews = count(
        select(Review.id).where(
            Review.status == "preparation",
            or_(
                (Review.employee_id == user.id) & Review.employee_prep_done.is_(False),
                (Review.reviewer_id == user.id) & Review.reviewer_prep_done.is_(False),
            ),
        )
    )
    visitors = select(Visitor.id).where(Visitor.visit_date == date.today(), Visitor.status == "expected")
    if not user.is_approver:
        visitors = visitors.where(Visitor.host_id == user.id)
    personal_new = count(select(PersonalDocument.id).where(PersonalDocument.user_id == user.id, PersonalDocument.opened_at.is_(None)))
    return Summary(
        unread=_unread(db, user),
        approvals_pending=approvals,
        reviews_todo=reviews,
        visitors_today=count(visitors),
        must_read_open=open_must_read(db, user),
        personal_documents_new=personal_new,
    )


# ---------- Global search ----------


class SearchHit(BaseModel):
    id: int
    title: str
    subtitle: str = ""
    link: str


class SearchResults(BaseModel):
    people: list[DirectoryEntry]
    documents: list[SearchHit]
    announcements: list[SearchHit]
    requests: list[SearchHit]
    links: list[SearchHit]


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/search", response_model=SearchResults)
def search(user: CurrentUser, db: DB, q: str = Query(..., min_length=2, max_length=100)) -> SearchResults:
    pattern = _like(q.strip())
    today = date.today()

    def like(column):
        return column.ilike(pattern, escape="\\")

    people = db.scalars(
        select(User)
        .where(
            User.is_active.is_(True),
            or_(
                like(User.first_name),
                like(User.last_name),
                like(User.first_name + " " + User.last_name),
                like(User.department),
                like(User.job_title),
                like(User.email),
            ),
        )
        .order_by(User.last_name, User.first_name)
        .limit(SEARCH_LIMIT)
    ).all()

    documents = db.scalars(
        select(Document)
        .where(Document.archived.is_(False), or_(like(Document.title), like(Document.description), like(Document.content_text)))
        .order_by(Document.title)
        .limit(SEARCH_LIMIT)
    ).all()

    announcements = db.scalars(
        select(Announcement)
        .where(
            Announcement.archived.is_(False),
            Announcement.publish_date <= today,
            or_(Announcement.expiry_date.is_(None), Announcement.expiry_date >= today),
            or_(like(Announcement.title), like(Announcement.body)),
        )
        .order_by(Announcement.publish_date.desc())
        .limit(SEARCH_LIMIT)
    ).all()

    requests_query = select(Request).where(like(Request.title))
    if user.is_approver:
        requests_query = requests_query.where((Request.status != "draft") | (Request.requester_id == user.id))
    else:
        requests_query = requests_query.where(Request.requester_id == user.id)
    requests = db.scalars(requests_query.order_by(Request.updated_at.desc()).limit(SEARCH_LIMIT)).all()

    links = db.scalars(
        select(QuickLink)
        .where(QuickLink.active.is_(True), or_(like(QuickLink.title), like(QuickLink.description)))
        .order_by(QuickLink.sort_order)
        .limit(SEARCH_LIMIT)
    ).all()

    return SearchResults(
        people=[to_entry(p, user) for p in people],
        documents=[SearchHit(id=d.id, title=d.title, subtitle=d.category, link=f"/documents/{d.id}") for d in documents],
        announcements=[
            SearchHit(id=a.id, title=a.title, subtitle=a.publish_date.isoformat(), link=f"/announcements#a-{a.id}")
            for a in announcements
        ],
        requests=[
            SearchHit(id=r.id, title=r.title, subtitle=f"{r.type}:{r.status}", link=f"/requests/{r.id}") for r in requests
        ],
        links=[SearchHit(id=link.id, title=link.title, subtitle=link.description, link=link.url) for link in links],
    )
