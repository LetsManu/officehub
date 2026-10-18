from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import Announcement
from ..schemas import AnnouncementIn, AnnouncementOut, AnnouncementUpdate

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


def _check_dates(item: Announcement) -> None:
    if item.expiry_date and item.expiry_date < item.publish_date:
        raise ApiError(422, "expiry_before_publish", "The expiry date must be after the publish date.")
    if item.category != "event":
        item.event_date = None


@router.get("", response_model=list[AnnouncementOut])
def list_announcements(
    user: CurrentUser,
    db: DB,
    include: str = Query("active", pattern="^(active|all)$"),
    category: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[Announcement]:
    query = select(Announcement)
    if include == "all":
        if not user.is_admin:
            raise forbidden()
    else:
        today = date.today()
        query = query.where(
            Announcement.archived.is_(False),
            Announcement.publish_date <= today,
            or_(Announcement.expiry_date.is_(None), Announcement.expiry_date >= today),
        )
    if category:
        query = query.where(Announcement.category == category)
    query = query.order_by(Announcement.pinned.desc(), Announcement.publish_date.desc(), Announcement.id.desc())
    return list(db.scalars(query.limit(limit)))


@router.post("", response_model=AnnouncementOut, status_code=201)
def create_announcement(body: AnnouncementIn, user: Admin, db: DB) -> Announcement:
    item = Announcement(**body.model_dump(), author_id=user.id)
    item.publish_date = body.publish_date or date.today()
    _check_dates(item)
    db.add(item)
    db.commit()
    return item


@router.patch("/{announcement_id}", response_model=AnnouncementOut)
def update_announcement(announcement_id: int, body: AnnouncementUpdate, user: Admin, db: DB) -> Announcement:
    item = db.get(Announcement, announcement_id)
    if item is None:
        raise not_found("Announcement")
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in {"title", "body", "category", "publish_date", "pinned", "archived"} and value is None:
            continue  # these fields cannot be cleared
        setattr(item, field, value)
    _check_dates(item)
    db.commit()
    return item
