"""Visitor registration: employees announce guests, reception checks them in and out.

Reception is done by managers and HR / admins.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import or_, select

from ..deps import DB, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import User, Visitor, utcnow
from ..schemas import UtcDateTime
from ..services import notifications

router = APIRouter(prefix="/api/visitors", tags=["visitors"])

Time = Annotated[str, StringConstraints(pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")]


class VisitorIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    company: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""
    visit_date: date
    expected_time: Time = ""
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    host_id: int | None = None


class VisitorAction(BaseModel):
    action: Literal["check_in", "check_out", "cancel"]


class VisitorOut(BaseModel):
    id: int
    name: str
    company: str
    visit_date: date
    expected_time: str
    note: str
    status: str
    host_id: int
    host_name: str
    checked_in_at: UtcDateTime | None
    checked_out_at: UtcDateTime | None
    can_cancel: bool
    can_check_in: bool


def _is_reception(user: User) -> bool:
    return user.is_approver


def _out(visitor: Visitor, user: User) -> VisitorOut:
    own = user.id in (visitor.host_id, visitor.created_by_id)
    return VisitorOut(
        id=visitor.id,
        name=visitor.name,
        company=visitor.company,
        visit_date=visitor.visit_date,
        expected_time=visitor.expected_time,
        note=visitor.note,
        status=visitor.status,
        host_id=visitor.host_id,
        host_name=visitor.host.full_name,
        checked_in_at=visitor.checked_in_at,
        checked_out_at=visitor.checked_out_at,
        can_cancel=visitor.status == "expected" and (own or user.is_hr),
        can_check_in=_is_reception(user) and visitor.status in ("expected", "checked_in"),
    )


@router.get("", response_model=list[VisitorOut])
def list_visitors(
    user: CurrentUser,
    db: DB,
    scope: Literal["mine", "day"] = "mine",
    day: date | None = Query(None),
) -> list[VisitorOut]:
    query = select(Visitor)
    if scope == "day":
        if not _is_reception(user):
            raise forbidden()
        query = query.where(Visitor.visit_date == (day or date.today()))
    else:
        query = query.where(
            or_(Visitor.host_id == user.id, Visitor.created_by_id == user.id),
            Visitor.visit_date >= date.today(),
        )
    rows = db.scalars(query.order_by(Visitor.visit_date, Visitor.expected_time, Visitor.name))
    return [_out(v, user) for v in rows]


@router.post("", response_model=VisitorOut, status_code=201)
def register_visitor(body: VisitorIn, user: CurrentUser, db: DB) -> VisitorOut:
    if body.visit_date < date.today():
        error = ApiError(422, "day_past", "Please choose today or a later day.")
        error.field = "visit_date"  # type: ignore[attr-defined]
        raise error
    host_id = body.host_id or user.id
    host = db.get(User, host_id)
    if host is None or not host.is_active:
        raise ApiError(422, "host_invalid", "Please choose who the visitor is meeting.")
    visitor = Visitor(**body.model_dump(exclude={"host_id"}), host_id=host_id, created_by_id=user.id)
    db.add(visitor)
    db.commit()
    db.refresh(visitor)
    return _out(visitor, user)


@router.post("/{visitor_id}/status", response_model=VisitorOut)
def change_status(visitor_id: int, body: VisitorAction, user: CurrentUser, db: DB) -> VisitorOut:
    visitor = db.get(Visitor, visitor_id)
    if visitor is None or not (_is_reception(user) or user.id in (visitor.host_id, visitor.created_by_id)):
        raise not_found("Visitor")
    current = _out(visitor, user)
    if body.action == "cancel":
        if not current.can_cancel:
            raise forbidden("This visit can no longer be cancelled.")
        visitor.status = "cancelled"
    elif body.action == "check_in":
        if not _is_reception(user) or visitor.status != "expected":
            raise ApiError(409, "invalid_status", "This visitor cannot be checked in.")
        visitor.status, visitor.checked_in_at = "checked_in", utcnow()
        notifications.notify_many(
            db, [visitor.host_id], user, "visitor_arrived", {"name": visitor.name, "company": visitor.company}, "/visitors"
        )
    else:
        if not _is_reception(user) or visitor.status != "checked_in":
            raise ApiError(409, "invalid_status", "This visitor cannot be checked out.")
        visitor.status, visitor.checked_out_at = "checked_out", utcnow()
    db.commit()
    return _out(visitor, user)
