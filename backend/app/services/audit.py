"""Audit log: a short, append-only record of important changes for HR and administrators."""

import json

from sqlalchemy.orm import Session

from ..models import AuditEvent, User

AUDIT_ACTIONS = (
    "user_created", "user_updated", "password_reset", "two_factor_reset",
    "request_approved", "request_rejected",
    "document_uploaded", "document_updated", "document_replaced",
    "announcement_created", "announcement_updated",
    "personal_document_sent", "personal_document_deleted",
    "settings_updated", "branding_updated", "holidays_updated",
    "asset_created", "asset_updated", "asset_assigned", "asset_returned",
    "training_created", "training_updated", "training_confirmed",
    "survey_created", "survey_closed", "idea_status", "offboarding_started",
    "login_failed_locked", "backup_restored", "keys_reset",
)


def audit(db: Session, actor: User | None, action: str, target: str = "", **details) -> None:
    """Adds an entry to the open session; it is saved with the caller's commit."""
    db.add(AuditEvent(actor_id=actor.id if actor else None, action=action, target=target[:150], details=json.dumps(details)))
