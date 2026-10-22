"""Shared FastAPI dependencies: database session and current user."""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .errors import ApiError, forbidden
from .models import AuthSession, User, utcnow
from .security import hash_token

SESSION_COOKIE = "officehub_session"

DB = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DB) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError(401, "not_authenticated", "Please sign in.")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None or session.expires_at < utcnow() or not session.user.is_active:
        raise ApiError(401, "session_expired", "Your session has ended. Please sign in again.")
    if session.app:
        # The apps stay signed in while they are used; the cookie keeps its own (long) lifetime
        renewed = utcnow() + timedelta(days=settings.app_session_days)
        if renewed - session.expires_at > timedelta(days=1):
            session.expires_at = renewed
            db.commit()
    return session.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_approver(user: CurrentUser) -> User:
    if not user.is_approver:
        raise forbidden()
    return user


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise forbidden()
    return user


def require_overseer(user: CurrentUser) -> User:
    """Decides for everyone (manager, HR, admin): company-wide reports and statistics."""
    if not user.approves_everyone:
        raise forbidden()
    return user


def require_staff(user: CurrentUser) -> User:
    """Anyone with more than the employee role: they see the list of people with roles and status."""
    if not (user.is_approver or user.is_support):
        raise forbidden()
    return user


def require_hr(user: CurrentUser) -> User:
    if not user.is_hr:
        raise forbidden()
    return user


def require_support(user: CurrentUser) -> User:
    if not user.is_support:
        raise forbidden()
    return user


Approver = Annotated[User, Depends(require_approver)]
Admin = Annotated[User, Depends(require_admin)]
HR = Annotated[User, Depends(require_hr)]
Support = Annotated[User, Depends(require_support)]
Overseer = Annotated[User, Depends(require_overseer)]
Staff = Annotated[User, Depends(require_staff)]
