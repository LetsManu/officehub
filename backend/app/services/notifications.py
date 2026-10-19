"""Create notifications. They are added to the open session and saved with the caller's commit."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import APPROVER_ROLES, Notification, Request, User
from .mailer import EMAIL_KINDS, queue_mail

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
    "training_due",
    "survey_new",
    "idea_status",
    "welcome",
)


def notify(db: Session, user_id: int, kind: str, params: dict | None = None, link: str = "") -> None:
    db.add(Notification(user_id=user_id, kind=kind, params=json.dumps(params or {}), link=link))
    if kind in EMAIL_KINDS:
        person = db.get(User, user_id)
        if person is not None and person.is_active and person.email_notifications:
            queue_mail(db, person.email, person.language, kind, params or {}, link)


def notify_many(db: Session, user_ids, actor: User | None, kind: str, params: dict | None = None, link: str = "") -> None:
    """Notify each person once, never the person who caused it."""
    for user_id in sorted(set(user_ids)):
        if actor is None or user_id != actor.id:
            notify(db, user_id, kind, params, link)


def request_approvers(db: Session, req: Request) -> list[int]:
    """The requester's own manager (and their deputy while they are away), else everyone with the admin role."""
    manager = req.requester.manager
    if manager is not None and manager.is_active and manager.role in APPROVER_ROLES and manager.id != req.requester_id:
        deputy = manager.active_deputy()
        return [manager.id] + ([deputy.id] if deputy and deputy.id != req.requester_id else [])
    return list(db.scalars(select(User.id).where(User.role == "admin", User.is_active.is_(True), User.id != req.requester_id)))


def request_params(req: Request, actor: User) -> dict:
    return {"name": actor.full_name, "title": req.title, "type": req.type}
