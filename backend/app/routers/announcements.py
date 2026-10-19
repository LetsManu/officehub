import json
from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import Announcement, AnnouncementRead, PollVote, User
from ..schemas import AnnouncementIn, AnnouncementOut, AnnouncementUpdate, PollOut, UtcDateTime
from ..services import notifications

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


class VoteIn(BaseModel):
    option: int = Field(ge=0, le=5)


class Reader(BaseModel):
    id: int
    full_name: str
    department: str
    read_at: UtcDateTime | None = None


class Confirmations(BaseModel):
    confirmed: list[Reader]
    missing: list[Reader]


def _visible(today: date):
    return (
        Announcement.archived.is_(False),
        Announcement.publish_date <= today,
        or_(Announcement.expiry_date.is_(None), Announcement.expiry_date >= today),
    )


def _check(item: Announcement) -> None:
    if item.expiry_date and item.expiry_date < item.publish_date:
        raise ApiError(422, "expiry_before_publish", "The expiry date must be after the publish date.")
    if item.category != "event":
        item.event_date = None
    if item.poll_question and not item.poll_options:
        error = ApiError(422, "poll_options_required", "Please add at least two answers to the poll.")
        error.field = "poll_options"  # type: ignore[attr-defined]
        raise error
    if not item.poll_question:
        item.poll_question, item.poll_options = None, None


def _poll(db: Session, item: Announcement, user: User) -> PollOut | None:
    if not item.poll_question or not item.poll_options:
        return None
    options = json.loads(item.poll_options)
    votes = dict(
        db.execute(
            select(PollVote.option, func.count()).where(PollVote.announcement_id == item.id).group_by(PollVote.option)
        ).all()
    )
    mine = db.scalar(select(PollVote.option).where(PollVote.announcement_id == item.id, PollVote.user_id == user.id))
    show = mine is not None or user.is_admin
    return PollOut(
        question=item.poll_question,
        options=options,
        my_vote=mine,
        counts=[votes.get(i, 0) for i in range(len(options))] if show else None,
        total=sum(votes.values()),
    )


def to_out(db: Session, item: Announcement, user: User) -> AnnouncementOut:
    out = AnnouncementOut.model_validate(item)
    if item.must_read:
        read = db.get(AnnouncementRead, (item.id, user.id))
        out.confirmed_at = read.read_at if read else None
    out.poll = _poll(db, item, user)
    return out


def _get_visible(db: Session, announcement_id: int, user: User) -> Announcement:
    item = db.get(Announcement, announcement_id)
    today = date.today()
    visible = item is not None and not item.archived and item.publish_date <= today and (
        item.expiry_date is None or item.expiry_date >= today
    )
    if item is None or not (visible or user.is_admin):
        raise not_found("Announcement")
    return item


def _announce_must_read(db: Session, item: Announcement, author: User) -> None:
    if item.must_read and not item.archived and item.publish_date <= date.today():
        people = db.scalars(select(User.id).where(User.is_active.is_(True)))
        notifications.notify_many(db, people, author, "must_read_new", {"title": item.title}, f"/announcements#a-{item.id}")


def open_must_read(db: Session, user: User) -> int:
    """Number of visible must-read announcements the person has not confirmed yet."""
    confirmed = select(AnnouncementRead.announcement_id).where(AnnouncementRead.user_id == user.id)
    return db.scalar(
        select(func.count())
        .select_from(Announcement)
        .where(*_visible(date.today()), Announcement.must_read.is_(True), Announcement.id.not_in(confirmed))
    ) or 0


@router.get("", response_model=list[AnnouncementOut])
def list_announcements(
    user: CurrentUser,
    db: DB,
    include: str = Query("active", pattern="^(active|all)$"),
    category: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[AnnouncementOut]:
    query = select(Announcement)
    if include == "all":
        if not user.is_admin:
            raise forbidden()
    else:
        query = query.where(*_visible(date.today()))
    if category:
        query = query.where(Announcement.category == category)
    query = query.order_by(Announcement.pinned.desc(), Announcement.publish_date.desc(), Announcement.id.desc())
    return [to_out(db, item, user) for item in db.scalars(query.limit(limit))]


@router.post("", response_model=AnnouncementOut, status_code=201)
def create_announcement(body: AnnouncementIn, user: Admin, db: DB) -> AnnouncementOut:
    values = body.model_dump()
    values["poll_options"] = json.dumps(values["poll_options"]) if values["poll_options"] else None
    item = Announcement(**values, author_id=user.id)
    item.publish_date = body.publish_date or date.today()
    _check(item)
    db.add(item)
    db.flush()
    _announce_must_read(db, item, user)
    db.commit()
    return to_out(db, item, user)


@router.patch("/{announcement_id}", response_model=AnnouncementOut)
def update_announcement(announcement_id: int, body: AnnouncementUpdate, user: Admin, db: DB) -> AnnouncementOut:
    item = db.get(Announcement, announcement_id)
    if item is None:
        raise not_found("Announcement")
    was_must_read = item.must_read
    old_options = item.poll_options
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in {"title", "body", "category", "publish_date", "pinned", "archived", "must_read"} and value is None:
            continue  # these fields cannot be cleared
        if field == "poll_options":
            value = json.dumps(value) if value else None
        setattr(item, field, value)
    _check(item)
    if old_options and item.poll_options != old_options:
        # Changed answers would make existing votes point to the wrong option.
        db.query(PollVote).filter(PollVote.announcement_id == item.id).delete()
    if item.must_read and not was_must_read:
        _announce_must_read(db, item, user)
    db.commit()
    return to_out(db, item, user)


@router.post("/{announcement_id}/confirm", response_model=AnnouncementOut)
def confirm_read(announcement_id: int, user: CurrentUser, db: DB) -> AnnouncementOut:
    item = _get_visible(db, announcement_id, user)
    if not item.must_read:
        raise ApiError(409, "not_must_read", "This announcement does not need a confirmation.")
    if db.get(AnnouncementRead, (item.id, user.id)) is None:
        db.add(AnnouncementRead(announcement_id=item.id, user_id=user.id))
        db.commit()
    return to_out(db, item, user)


@router.post("/{announcement_id}/vote", response_model=AnnouncementOut)
def vote(announcement_id: int, body: VoteIn, user: CurrentUser, db: DB) -> AnnouncementOut:
    item = _get_visible(db, announcement_id, user)
    poll = _poll(db, item, user)
    if poll is None:
        raise not_found("Poll")
    if body.option >= len(poll.options):
        raise ApiError(422, "poll_option_invalid", "Please choose one of the answers.")
    existing = db.get(PollVote, (item.id, user.id))
    if existing:
        existing.option = body.option  # people may change their mind
    else:
        db.add(PollVote(announcement_id=item.id, user_id=user.id, option=body.option))
    db.commit()
    return to_out(db, item, user)


def _confirmations(db: Session, item: Announcement) -> Confirmations:
    reads = {r.user_id: r.read_at for r in db.scalars(select(AnnouncementRead).where(AnnouncementRead.announcement_id == item.id))}
    people = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.last_name, User.first_name)).all()
    confirmed = [Reader(id=p.id, full_name=p.full_name, department=p.department, read_at=reads[p.id]) for p in people if p.id in reads]
    missing = [Reader(id=p.id, full_name=p.full_name, department=p.department) for p in people if p.id not in reads]
    return Confirmations(confirmed=confirmed, missing=missing)


@router.get("/{announcement_id}/confirmations", response_model=Confirmations)
def confirmations(announcement_id: int, user: Admin, db: DB) -> Confirmations:
    item = db.get(Announcement, announcement_id)
    if item is None or not item.must_read:
        raise not_found("Announcement")
    return _confirmations(db, item)


@router.post("/{announcement_id}/remind")
def remind(announcement_id: int, user: Admin, db: DB) -> dict:
    """Sends a reminder to everyone who has not confirmed yet."""
    item = _get_visible(db, announcement_id, user)
    if not item.must_read:
        raise not_found("Announcement")
    missing = [p.id for p in _confirmations(db, item).missing]
    notifications.notify_many(db, missing, user, "must_read_reminder", {"title": item.title}, f"/announcements#a-{item.id}")
    db.commit()
    return {"reminded": len([m for m in missing if m != user.id])}
