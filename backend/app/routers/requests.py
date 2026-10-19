from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..deps import DB, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..files import INLINE_TYPES, MIME_TYPES, RECEIPT_TYPES, delete_quietly, resolve, save_upload
from ..models import PENDING_STATUSES, REQUEST_STATUSES, REQUEST_TYPES, Request, RequestComment, User, utcnow
from ..schemas import CommentIn, DecisionIn, RequestCreate, RequestDetail, RequestList, RequestUpdate
from ..services import notifications
from ..services import requests as service

router = APIRouter(prefix="/api/requests", tags=["requests"])


def _load(db: Session, request_id: int, user: User) -> Request:
    req = db.scalar(
        select(Request)
        .where(Request.id == request_id)
        .options(selectinload(Request.comments), selectinload(Request.events))
    )
    if req is None or not service.can_view(user, req):
        # Same answer for "missing" and "not yours", so ids cannot be probed.
        raise not_found("Request")
    return req


def _notify_submitted(db: Session, req: Request, user: User) -> None:
    notifications.notify_many(
        db,
        notifications.request_approvers(db, req),
        user,
        "request_submitted",
        notifications.request_params(req, user),
        f"/requests/{req.id}",
    )


def _split(value: str | None, allowed: tuple[str, ...]) -> list[str]:
    if not value:
        return []
    items = [v.strip() for v in value.split(",") if v.strip()]
    invalid = [v for v in items if v not in allowed]
    if invalid:
        raise ApiError(422, "invalid_filter", f"Unknown filter value: {invalid[0]}.")
    return items


@router.get("", response_model=RequestList)
def list_requests(
    user: CurrentUser,
    db: DB,
    scope: Literal["mine", "all"] = "mine",
    type: str | None = None,
    status: str | None = None,
    requester_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RequestList:
    query = select(Request)
    if scope == "all":
        if not user.is_approver:
            raise forbidden()
        query = query.where((Request.status != "draft") | (Request.requester_id == user.id))
        if requester_id:
            query = query.where(Request.requester_id == requester_id)
    else:
        query = query.where(Request.requester_id == user.id)

    if types := _split(type, REQUEST_TYPES):
        query = query.where(Request.type.in_(types))
    if statuses := _split(status, REQUEST_STATUSES):
        query = query.where(Request.status.in_(statuses))
    if date_from:
        query = query.where(Request.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.where(Request.created_at < datetime.combine(date_to + timedelta(days=1), time.min))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(selectinload(Request.comments))
        .order_by(Request.updated_at.desc(), Request.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return RequestList(items=[service.to_out(r) for r in rows], total=total)


@router.post("", response_model=RequestDetail, status_code=201)
def create_request(body: RequestCreate, user: CurrentUser, db: DB) -> RequestDetail:
    values = service.validate_fields(body.type, body.model_dump())
    now = utcnow()
    req = Request(
        type=body.type,
        requester_id=user.id,
        status="submitted" if body.submit else "draft",
        submitted_at=now if body.submit else None,
        **values,
    )
    db.add(req)
    service.add_event(db, req, user, "created")
    if body.submit:
        service.add_event(db, req, user, "submitted")
        db.flush()
        _notify_submitted(db, req, user)
    db.commit()
    return service.to_detail(_load(db, req.id, user), user)


@router.get("/{request_id}", response_model=RequestDetail)
def get_request(request_id: int, user: CurrentUser, db: DB) -> RequestDetail:
    return service.to_detail(_load(db, request_id, user), user)


@router.patch("/{request_id}", response_model=RequestDetail)
def update_request(request_id: int, body: RequestUpdate, user: CurrentUser, db: DB) -> RequestDetail:
    req = _load(db, request_id, user)
    perms = service.permissions(user, req)
    changes = body.model_dump(exclude_unset=True, exclude={"status"})

    if changes:
        if not perms.can_edit:
            raise ApiError(409, "not_editable", "Only drafts can be changed. Please add a comment instead.")
        merged = service.current_values(req) | changes
        for field, value in service.validate_fields(req.type, merged).items():
            setattr(req, field, value)
        service.add_event(db, req, user, "edited")

    if body.status == "submitted":
        if not perms.can_submit:
            raise ApiError(409, "invalid_status", "This request has already been sent.")
        # Re-check the stored values, e.g. a draft whose dates are now in the past.
        service.validate_fields(req.type, service.current_values(req))
        req.status = "submitted"
        req.submitted_at = utcnow()
        service.add_event(db, req, user, "submitted")
        _notify_submitted(db, req, user)
    elif body.status == "cancelled":
        if not perms.can_cancel:
            raise ApiError(409, "invalid_status", "This request can no longer be cancelled.")
        req.status = "cancelled"
        service.add_event(db, req, user, "cancelled")
    elif body.status == "in_review":
        if not perms.can_start_review:
            raise forbidden("This request cannot be moved to review.")
        req.status = "in_review"
        service.add_event(db, req, user, "in_review")
        notifications.notify_many(
            db, [req.requester_id], user, "request_in_review", notifications.request_params(req, user), f"/requests/{req.id}"
        )

    req.updated_at = utcnow()
    db.commit()
    db.expire_all()
    return service.to_detail(_load(db, request_id, user), user)


@router.post("/{request_id}/comments", response_model=RequestDetail, status_code=201)
def add_comment(request_id: int, body: CommentIn, user: CurrentUser, db: DB) -> RequestDetail:
    req = _load(db, request_id, user)
    if not service.permissions(user, req).can_comment:
        raise forbidden("Comments are closed for this request.")
    db.add(RequestComment(request_id=req.id, author_id=user.id, body=body.body))
    # Everyone who took part so far hears about the new comment.
    participants = {req.requester_id} | {c.author_id for c in req.comments}
    if req.decided_by_id:
        participants.add(req.decided_by_id)
    if user.id == req.requester_id and len(participants) == 1:
        participants |= set(notifications.request_approvers(db, req))
    notifications.notify_many(
        db, participants, user, "request_comment", notifications.request_params(req, user), f"/requests/{req.id}"
    )
    req.updated_at = utcnow()
    db.commit()
    db.expire_all()
    return service.to_detail(_load(db, request_id, user), user)


def _decide(request_id: int, body: DecisionIn, user: User, db: Session, outcome: str) -> RequestDetail:
    req = _load(db, request_id, user)
    if req.requester_id == user.id and user.is_approver:
        raise forbidden("You cannot decide on your own request.")
    if not service.permissions(user, req).can_decide:
        if req.status not in PENDING_STATUSES and user.is_approver:
            raise ApiError(409, "already_decided", "A decision has already been made for this request.")
        raise forbidden()
    if req.type == "appointment" and outcome == "approved":
        proposed = service.current_values(req)["proposed_times"] or []
        if body.chosen_time not in proposed:
            error = ApiError(422, "time_choose", "Please choose one of the suggested times.")
            error.field = "chosen_time"  # type: ignore[attr-defined]
            raise error
        req.confirmed_time = body.chosen_time
    req.status = outcome
    req.decision_comment = body.comment or None
    req.decided_by_id = user.id
    req.decided_at = utcnow()
    req.updated_at = req.decided_at
    service.add_event(db, req, user, outcome)
    notifications.notify_many(
        db, [req.requester_id], user, f"request_{outcome}", notifications.request_params(req, user), f"/requests/{req.id}"
    )
    db.commit()
    db.expire_all()
    return service.to_detail(_load(db, request_id, user), user)


@router.post("/{request_id}/approve", response_model=RequestDetail)
def approve(request_id: int, user: CurrentUser, db: DB, body: DecisionIn | None = None) -> RequestDetail:
    return _decide(request_id, body or DecisionIn(), user, db, "approved")


@router.post("/{request_id}/reject", response_model=RequestDetail)
def reject(request_id: int, user: CurrentUser, db: DB, body: DecisionIn | None = None) -> RequestDetail:
    return _decide(request_id, body or DecisionIn(), user, db, "rejected")


@router.post("/{request_id}/attachment", response_model=RequestDetail)
async def upload_attachment(request_id: int, user: CurrentUser, db: DB, file: UploadFile = File(...)) -> RequestDetail:
    req = _load(db, request_id, user)
    if not service.permissions(user, req).can_attach:
        raise forbidden("A receipt can only be added to your own pending expense requests.")
    stored = await save_upload(file, RECEIPT_TYPES, "receipts")
    delete_quietly(req.attachment_path)
    req.attachment_name = stored.original_name
    req.attachment_path = stored.relative_path
    req.attachment_mime = MIME_TYPES[stored.file_type]
    req.updated_at = utcnow()
    service.add_event(db, req, user, "attachment")
    db.commit()
    db.expire_all()
    return service.to_detail(_load(db, request_id, user), user)


@router.get("/{request_id}/attachment")
def download_attachment(request_id: int, user: CurrentUser, db: DB) -> FileResponse:
    req = _load(db, request_id, user)
    if not req.attachment_path:
        raise not_found("Receipt")
    path = resolve(req.attachment_path)
    file_type = path.suffix.lstrip(".")
    return FileResponse(
        path,
        media_type=MIME_TYPES.get(file_type, "application/octet-stream"),
        filename=req.attachment_name,
        content_disposition_type="inline" if file_type in INLINE_TYPES else "attachment",
    )
