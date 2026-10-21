"""Notification centre, badge counts and the global search."""

import json
from datetime import date, timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update

from ..deps import DB, CurrentUser
from ..errors import not_found
from ..models import (
    PENDING_STATUSES,
    Announcement,
    Board,
    BoardColumn,
    Card,
    CardAssignee,
    Document,
    Notification,
    PersonalDocument,
    QuickLink,
    Request,
    Review,
    Space,
    SpaceFile,
    SpaceMember,
    Survey,
    SurveyParticipation,
    TimeMonth,
    User,
    Visitor,
    WikiPage,
    utcnow,
)
from ..schemas import UtcDateTime
from ..services.requests import deputy_for
from .announcements import open_must_read
from .directory import DirectoryEntry, to_entry
from .chat import unread_total
from .time_tracking import team_ids
from .trainings import open_trainings

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
    acting_deputy: bool
    trainings_due: int
    surveys_open: int
    time_months_pending: int = 0
    chat_unread: int = 0
    cards_due: int = 0


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
    deputy_managers = deputy_for(db, user)
    if user.is_approver:
        approvals = count(select(Request.id).where(Request.status.in_(PENDING_STATUSES), Request.requester_id != user.id))
    elif deputy_managers:
        team = select(User.id).where(User.manager_id.in_(deputy_managers), User.id != user.id)
        approvals = count(select(Request.id).where(Request.status.in_(PENDING_STATUSES), Request.requester_id.in_(team)))
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
    my_team = team_ids(db, user) - {user.id} if (user.is_approver or deputy_managers) else set()
    months_pending = count(select(TimeMonth.id).where(TimeMonth.status == "submitted", TimeMonth.user_id.in_(my_team))) if my_team else 0
    personal_new = count(select(PersonalDocument.id).where(PersonalDocument.user_id == user.id, PersonalDocument.opened_at.is_(None)))
    return Summary(
        unread=_unread(db, user),
        approvals_pending=approvals,
        reviews_todo=reviews,
        visitors_today=count(visitors),
        must_read_open=open_must_read(db, user),
        personal_documents_new=personal_new,
        acting_deputy=bool(deputy_managers),
        time_months_pending=months_pending,
        chat_unread=unread_total(db, user),
        cards_due=count(
            select(Card.id).join(CardAssignee, CardAssignee.card_id == Card.id).join(BoardColumn, BoardColumn.id == Card.column_id)
            .where(CardAssignee.user_id == user.id, BoardColumn.is_done.is_(False), Card.due_date.is_not(None),
                   Card.due_date <= date.today() + timedelta(days=2))
        ),
        trainings_due=open_trainings(db, user),
        surveys_open=count(
            select(Survey.id).where(
                Survey.status == "open",
                (Survey.closes_on.is_(None)) | (Survey.closes_on >= date.today()),
                Survey.id.not_in(select(SurveyParticipation.survey_id).where(SurveyParticipation.user_id == user.id)),
            )
        ),
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
    workspace: list[SearchHit] = []  # files, wiki pages and cards in the person's spaces


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

    spaces = {s.id: s.name for s in db.scalars(select(Space).where(
        Space.archived.is_(False), Space.id.in_(select(SpaceMember.space_id).where(SpaceMember.user_id == user.id))))}
    workspace: list[SearchHit] = []
    if spaces:
        for f in db.scalars(select(SpaceFile).where(SpaceFile.space_id.in_(spaces), SpaceFile.deleted_at.is_(None),
                                                    or_(like(SpaceFile.name), like(SpaceFile.content_text))).limit(SEARCH_LIMIT)):
            workspace.append(SearchHit(id=f.id, title=f.name, subtitle=f"file:{spaces[f.space_id]}",
                                       link=f"/spaces/{f.space_id}/files?file={f.id}"))
        for p in db.scalars(select(WikiPage).where(WikiPage.space_id.in_(spaces), WikiPage.deleted_at.is_(None),
                                                   or_(like(WikiPage.title), like(WikiPage.body))).limit(SEARCH_LIMIT)):
            workspace.append(SearchHit(id=p.id, title=p.title, subtitle=f"page:{spaces[p.space_id]}",
                                       link=f"/spaces/{p.space_id}/wiki/{p.id}"))
        for c, b in db.execute(select(Card, Board).join(BoardColumn, BoardColumn.id == Card.column_id)
                               .join(Board, Board.id == BoardColumn.board_id)
                               .where(Board.space_id.in_(spaces), like(Card.title)).limit(SEARCH_LIMIT)):
            workspace.append(SearchHit(id=c.id, title=c.title, subtitle=f"card:{spaces[b.space_id]}",
                                       link=f"/spaces/{b.space_id}/board?card={c.id}"))

    return SearchResults(
        workspace=workspace[: SEARCH_LIMIT * 2],
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
