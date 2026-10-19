"""Create notifications. They are added to the open session and saved with the caller's commit."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import APPROVER_ROLES, Notification, Request, User

NOTIFICATION_KINDS = (
    "request_submitted",
    "request_in_review",
    "request_approved",
    "request_rejected",
    "request_comment",
    "visitor_arrived",
    "review_created",
    "booking_cancelled",
    "must_read_new",
    "must_read_reminder",
    "personal_document",
    "welcome",
)


def notify(db: Session, user_id: int, kind: str, params: dict | None = None, link: str = "") -> None:
    db.add(Notification(user_id=user_id, kind=kind, params=json.dumps(params or {}), link=link))


def notify_many(db: Session, user_ids, actor: User | None, kind: str, params: dict | None = None, link: str = "") -> None:
    """Notify each person once, never the person who caused it."""
    for user_id in sorted(set(user_ids)):
        if actor is None or user_id != actor.id:
            notify(db, user_id, kind, params, link)


def request_approvers(db: Session, req: Request) -> list[int]:
    """The requester's own manager, or everyone with the admin role when there is none."""
    manager = req.requester.manager
    if manager is not None and manager.is_active and manager.role in APPROVER_ROLES and manager.id != req.requester_id:
        return [manager.id]
    return list(db.scalars(select(User.id).where(User.role == "admin", User.is_active.is_(True), User.id != req.requester_id)))


def request_params(req: Request, actor: User) -> dict:
    return {"name": actor.full_name, "title": req.title, "type": req.type}
