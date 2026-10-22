"""Portal-wide security rules HR can switch on."""

import json

from sqlalchemy.orm import Session

from ..models import User
from ..security import hash_token
from .settings import get_setting


def required_2fa_roles(db: Session) -> list[str]:
    return list(get_setting(db, "security", {}).get("require_2fa_roles", []))


def two_factor_required(db: Session, user: User) -> bool:
    required = required_2fa_roles(db)
    return any(r in required for r in (user.roles or ["employee"]))


def use_recovery_code(user: User, code: str) -> bool:
    """Accepts each recovery code once."""
    hashes = json.loads(user.recovery_codes or "[]")
    digest = hash_token(code.strip().lower())
    if digest not in hashes:
        return False
    hashes.remove(digest)
    user.recovery_codes = json.dumps(hashes)
    return True
