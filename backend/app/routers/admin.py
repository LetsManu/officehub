import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import delete, func, select

from ..deps import DB, Admin, Approver
from ..errors import ApiError, not_found
from ..models import PENDING_STATUSES, REQUEST_TYPES, AuthSession, Request, User, utcnow
from ..schemas import PasswordReset, UserAdminUpdate, UserCreate, UserOut
from ..security import hash_password
from ..services.people import check_manager, start_onboarding

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
def stats(user: Approver, db: DB) -> dict:
    by_status = dict(
        db.execute(select(Request.status, func.count()).where(Request.status != "draft").group_by(Request.status)).all()
    )
    pending_by_type = dict(
        db.execute(
            select(Request.type, func.count()).where(Request.status.in_(PENDING_STATUSES)).group_by(Request.type)
        ).all()
    )
    month_start = datetime.combine(date.today().replace(day=1), time.min)
    year_start = date.today().replace(month=1, day=1)
    decided = db.execute(
        select(Request.submitted_at, Request.decided_at).where(
            Request.decided_at.is_not(None), Request.submitted_at.is_not(None), Request.decided_at >= month_start - timedelta(days=90)
        )
    ).all()
    hours = [(d - s).total_seconds() / 3600 for s, d in decided if d >= s]
    vacation_days = db.scalar(
        select(func.coalesce(func.sum(Request.working_days), 0)).where(
            Request.type == "vacation", Request.status == "approved", Request.start_date >= year_start
        )
    )
    return {
        "pending": sum(by_status.get(s, 0) for s in PENDING_STATUSES),
        "by_status": by_status,
        "pending_by_type": {t: pending_by_type.get(t, 0) for t in REQUEST_TYPES},
        "decided_this_month": db.scalar(select(func.count()).where(Request.decided_at >= month_start)) or 0,
        "average_decision_hours": round(sum(hours) / len(hours), 1) if hours else None,
        "approved_vacation_days_this_year": int(vacation_days or 0),
        "active_employees": db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0,
    }


def _csv_cell(value) -> str:
    """Neutralise spreadsheet formulas (CSV injection)."""
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


@router.get("/requests/export.csv")
def export_requests(
    user: Approver,
    db: DB,
    type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    query = select(Request).where(Request.status == "approved")
    if type:
        if type not in REQUEST_TYPES:
            raise ApiError(422, "invalid_filter", f"Unknown request type: {type}.")
        query = query.where(Request.type == type)
    if date_from:
        query = query.where(Request.decided_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.where(Request.decided_at < datetime.combine(date_to + timedelta(days=1), time.min))

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([
        "ID", "Type", "Title", "Employee", "Department", "Start date", "End date", "Working days",
        "Amount", "Currency", "Category", "Item", "Submitted", "Approved on", "Approved by", "Decision comment",
    ])
    for r in db.scalars(query.order_by(Request.decided_at)):
        writer.writerow([_csv_cell(v) for v in (
            r.id, r.type, r.title, r.requester.full_name, r.requester.department,
            r.start_date, r.end_date, r.working_days,
            f"{Decimal(r.amount_cents) / 100:.2f}" if r.amount_cents is not None else "",
            r.currency, r.category, r.item,
            r.submitted_at.date() if r.submitted_at else "",
            r.decided_at.date() if r.decided_at else "",
            r.decided_by.full_name if r.decided_by else "",
            r.decision_comment,
        )])
    filename = f"approved-requests-{utcnow():%Y-%m-%d}.csv"
    # UTF-8 BOM so spreadsheet programs show umlauts correctly.
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/users", response_model=list[UserOut])
def list_users(user: Approver, db: DB) -> list[User]:
    return list(db.scalars(select(User).order_by(User.last_name, User.first_name)))


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, user: Admin, db: DB) -> User:
    if db.scalar(select(User).where(User.email == body.email)):
        raise ApiError(409, "email_taken", "A person with this email address already exists.")
    check_manager(db, None, body.manager_id)
    data = body.model_dump(exclude={"password", "start_onboarding"})
    new_user = User(**data, password_hash=hash_password(body.password))
    db.add(new_user)
    db.flush()
    if body.start_onboarding:
        start_onboarding(db, new_user)
    db.commit()
    return new_user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserAdminUpdate, user: Admin, db: DB) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise not_found("Person")
    if target.id == user.id and (body.role not in (None, "admin") or body.is_active is False):
        raise ApiError(409, "self_lockout", "You cannot remove your own administrator access.")
    changes = body.model_dump(exclude_unset=True)
    if "manager_id" in changes:
        if changes["manager_id"] == target.id:
            raise ApiError(422, "manager_cycle", "A person cannot be their own manager.")
        check_manager(db, target, changes["manager_id"])
    for field, value in changes.items():
        if value is None and field != "manager_id":
            continue
        setattr(target, field, value)
    if changes.get("is_active") is False:
        db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
    db.commit()
    return target


@router.post("/users/{user_id}/password", status_code=204)
def reset_password(user_id: int, body: PasswordReset, user: Admin, db: DB) -> None:
    target = db.get(User, user_id)
    if target is None:
        raise not_found("Person")
    if target.id == user.id:
        raise ApiError(409, "use_profile", "Please change your own password under Profile.")
    target.password_hash = hash_password(body.password)
    # Sign the person out everywhere so only the new password works.
    db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
    db.commit()
