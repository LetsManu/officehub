"""App passwords: one password per program (network drive, WordCraft, DeckCraft …).

Programs cannot do the portal's sign-in with a second factor, so each one gets its own long random password. Only
its SHA-256 hash is stored (the secret is long and random, so a slow hash is not needed); it is shown once and can be
removed at any time without touching the real password.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AppPassword, User, utcnow

MAX_PER_USER = 20


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def create(db: Session, user: User, name: str) -> tuple[AppPassword, str]:
    # Groups of five are easy to type from the screen: abcde-fghij-…
    raw = secrets.token_hex(15)
    secret = "-".join(raw[i:i + 5] for i in range(0, len(raw), 5))
    row = AppPassword(user_id=user.id, name=name, secret_hash=_hash(secret))
    db.add(row)
    return row, secret


def count(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).select_from(AppPassword).where(AppPassword.user_id == user.id)) or 0


def verify(db: Session, login: str, secret: str) -> User | None:
    """The active user for this e-mail address and app password, or None."""
    found = check(db, login, secret)
    return found[0] if found else None


def check(db: Session, login: str, secret: str) -> tuple[User, AppPassword] | None:
    """The active user and the app password they signed in with, or None."""
    user = db.scalar(select(User).where(func.lower(User.email) == login.strip().lower()))
    if user is None or not user.is_active:
        _hash(secret)  # same work whether the address exists or not
        return None
    wanted = _hash(secret.strip())
    for row in db.scalars(select(AppPassword).where(AppPassword.user_id == user.id)):
        if hmac.compare_digest(row.secret_hash, wanted):
            now = utcnow()
            if row.last_used_at is None or now - row.last_used_at > timedelta(minutes=5):
                row.last_used_at = now
                db.commit()
            return user, row
    return None
