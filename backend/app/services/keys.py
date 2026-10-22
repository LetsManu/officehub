"""Who is really who in end-to-end encrypted meetings: each browser's identity key (models.DeviceKey).

OfficeHub only stores and hands out the public keys, the signatures between a person's devices and the signed
"I have checked this person" notes (KeyVerification). It never signs anything itself: the browsers check every
signature (frontend src/lib/e2ee/identity.ts), so a changed or added key at the server shows up as such.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DeviceKey
from .settings import get_setting, set_setting

MAX_DEVICES = 20
POLICIES = ("warn", "strict")


def device_out(device: DeviceKey) -> dict:
    return {
        "id": device.id,
        "public_key": device.public_key,
        "name": device.name,
        "root": device.root,
        "signed_by": device.signed_by,
        "signature": device.signature,
        "pending": not device.root and device.signed_by is None,
        "created_at": device.created_at.isoformat() + "Z",
    }


def devices_of(db: Session, user_id: int) -> list[DeviceKey]:
    return list(db.scalars(select(DeviceKey).where(DeviceKey.user_id == user_id).order_by(DeviceKey.id)))


def chain(db: Session, user_id: int) -> list[dict]:
    """A person's devices as the browsers check them: the root, the confirmed ones and those still waiting."""
    return [device_out(d) for d in devices_of(db, user_id)]


def pending_count(db: Session, user_id: int) -> int:
    return sum(1 for d in devices_of(db, user_id) if not d.root and d.signed_by is None)


def policy(db: Session) -> str:
    """'warn': people who are not confirmed are marked; 'strict': guests and devices nobody confirmed are not let
    into an encrypted meeting, and a changed key stops the meeting for whoever notices it."""
    value = get_setting(db, "e2ee_identity", {}).get("policy", "warn")
    return value if value in POLICIES else "warn"


def set_policy(db: Session, value: str) -> None:
    set_setting(db, "e2ee_identity", {"policy": value})
