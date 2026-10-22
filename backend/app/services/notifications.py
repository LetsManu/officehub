"""Create notifications. They are added to the open session and saved with the caller's commit."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IT_REQUEST_TYPES, Notification, Request, User, with_role
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


def notify(db: Session, user_id: int, kind: str, params: dict | None = None, link: str = "",
           attachment: tuple[str, bytes, str] | None = None) -> None:
    db.add(Notification(user_id=user_id, kind=kind, params=json.dumps(params or {}), link=link))
    if kind in EMAIL_KINDS:
        person = db.get(User, user_id)
        if person is not None and person.is_active and person.email_notifications:
            queue_mail(db, person.email, person.language, kind, params or {}, link, attachment)


def notify_many(db: Session, user_ids, actor: User | None, kind: str, params: dict | None = None, link: str = "") -> None:
    """Notify each person once, never the person who caused it."""
    for user_id in sorted(set(user_ids)):
        if actor is None or user_id != actor.id:
            notify(db, user_id, kind, params, link)


def request_approvers(db: Session, req: Request) -> list[int]:
    """The requester's own manager or team lead (and their deputy while they are away), else HR; IT requests also
    reach the service desk."""
    manager = req.requester.manager
    if manager is not None and manager.is_active and manager.is_approver and manager.id != req.requester_id:
        deputy = manager.active_deputy()
        people = [manager.id] + ([deputy.id] if deputy and deputy.id != req.requester_id else [])
    else:
        people = list(db.scalars(select(User.id).where(with_role("hr"), User.is_active.is_(True), User.id != req.requester_id)))
    if req.type in IT_REQUEST_TYPES:
        desk = db.scalars(select(User).where(with_role("servicedesk"), User.is_active.is_(True), User.id != req.requester_id))
        people += [u.id for u in desk if "servicedesk" in u.roles and u.id not in people]
    return people


def request_params(req: Request, actor: User) -> dict:
    return {"name": actor.full_name, "title": req.title, "type": req.type}
