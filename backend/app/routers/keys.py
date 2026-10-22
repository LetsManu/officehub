"""Identity keys for end-to-end encrypted meetings (services/keys.py): each browser's public key, confirming a
new device from one already confirmed, signed "I have checked this person" notes and the administrator's rule."""

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, select

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, not_found
from ..models import DeviceKey, KeyVerification, User
from ..services import keys
from ..services.audit import audit

router = APIRouter(prefix="/api/keys", tags=["keys"])

B64 = Annotated[str, StringConstraints(min_length=16, max_length=400, pattern=r"^[A-Za-z0-9+/=]+$")]
Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DeviceIn(BaseModel):
    public_key: B64
    name: str = Field(default="", max_length=80)
    signature: B64  # by the new key itself: it holds the private part


class ApproveIn(BaseModel):
    signed_by: int
    signature: B64


class VerificationIn(BaseModel):
    subject_id: int
    root: Hex
    signed_by: int
    signature: B64


class PolicyIn(BaseModel):
    policy: Literal["warn", "strict"]


def _verification_out(v: KeyVerification) -> dict:
    return {"subject_id": v.subject_id, "root": v.root, "signed_by": v.signed_by, "signature": v.signature}


def _own_device(db: DB, user: User, device_id: int) -> DeviceKey:
    device = db.get(DeviceKey, device_id)
    if device is None or device.user_id != user.id:
        raise not_found("Device")
    return device


@router.get("/me")
def mine(user: CurrentUser, db: DB) -> dict:
    verifications = db.scalars(select(KeyVerification).where(KeyVerification.author_id == user.id))
    return {"devices": keys.chain(db, user.id), "verifications": [_verification_out(v) for v in verifications],
            "policy": keys.policy(db)}


@router.post("/devices", status_code=201)
def add_device(body: DeviceIn, user: CurrentUser, db: DB) -> dict:
    """A browser registers its key. The first one is the person's root; later ones wait for confirmation."""
    existing = keys.devices_of(db, user.id)
    if any(d.public_key == body.public_key for d in existing):
        raise ApiError(409, "device_exists", "This device is already registered.")
    if len(existing) >= keys.MAX_DEVICES:
        raise ApiError(422, "too_many_devices", "Please remove a device you no longer use first.")
    device = DeviceKey(user_id=user.id, public_key=body.public_key, name=body.name.strip(), root=not existing,
                       signature=body.signature if not existing else "")
    db.add(device)
    db.commit()
    return keys.device_out(device)


@router.post("/devices/{device_id}/approve")
def approve_device(device_id: int, body: ApproveIn, user: CurrentUser, db: DB) -> dict:
    """One of the person's confirmed devices signs the new one (after they compared the code on both screens)."""
    device = _own_device(db, user, device_id)
    signer = _own_device(db, user, body.signed_by)
    if device.root or device.signed_by is not None:
        raise ApiError(409, "device_confirmed", "This device is already confirmed.")
    if signer.id == device.id or (not signer.root and signer.signed_by is None):
        raise ApiError(422, "signer_unconfirmed", "Please confirm it from a device that is already confirmed.")
    device.signed_by = signer.id
    device.signature = body.signature
    db.commit()
    return keys.device_out(device)


@router.delete("/devices/{device_id}", status_code=204)
def remove_device(device_id: int, user: CurrentUser, db: DB) -> None:
    device = _own_device(db, user, device_id)
    if device.root:
        raise ApiError(422, "root_device", "The first device can only be replaced by starting anew.")
    # Devices this one confirmed lose their confirmation and have to be confirmed again
    for other in keys.devices_of(db, user.id):
        if other.signed_by == device.id:
            other.signed_by = None
            other.signature = ""
    db.delete(device)
    db.commit()


@router.post("/reset", status_code=201)
def start_anew(body: DeviceIn, user: CurrentUser, db: DB) -> dict:
    """No confirmed device left: this browser becomes the new root. Everyone who knew the old key is told that it
    changed, and the person's own checks of others are gone (they were signed with the old devices)."""
    db.execute(delete(DeviceKey).where(DeviceKey.user_id == user.id))
    db.execute(delete(KeyVerification).where(KeyVerification.author_id == user.id))
    device = DeviceKey(user_id=user.id, public_key=body.public_key, name=body.name.strip(), root=True,
                       signature=body.signature)
    db.add(device)
    audit(db, user, "keys_reset", user.full_name)
    db.commit()
    return keys.device_out(device)


@router.get("/users/{user_id}")
def person(user_id: int, user: CurrentUser, db: DB) -> dict:
    subject = db.get(User, user_id)
    if subject is None or not subject.is_active:
        raise not_found("Person")
    return {"user_id": subject.id, "name": subject.full_name, "devices": keys.chain(db, subject.id)}


@router.put("/verifications")
def verify(body: VerificationIn, user: CurrentUser, db: DB) -> dict:
    if body.subject_id == user.id or db.get(User, body.subject_id) is None:
        raise not_found("Person")
    _own_device(db, user, body.signed_by)
    row = db.scalar(select(KeyVerification).where(KeyVerification.author_id == user.id,
                                                  KeyVerification.subject_id == body.subject_id))
    if row is None:
        row = KeyVerification(author_id=user.id, subject_id=body.subject_id, root=body.root, signed_by=body.signed_by,
                              signature=body.signature)
        db.add(row)
    else:
        row.root, row.signed_by, row.signature = body.root, body.signed_by, body.signature
    db.commit()
    return _verification_out(row)


@router.delete("/verifications/{subject_id}", status_code=204)
def unverify(subject_id: int, user: CurrentUser, db: DB) -> None:
    db.execute(delete(KeyVerification).where(KeyVerification.author_id == user.id,
                                             KeyVerification.subject_id == subject_id))
    db.commit()


@router.get("/policy")
def get_policy(user: CurrentUser, db: DB) -> dict:
    return {"policy": keys.policy(db)}


@router.put("/policy")
def put_policy(body: PolicyIn, user: Admin, db: DB) -> dict:
    keys.set_policy(db, body.policy)
    audit(db, user, "settings_updated", "e2ee_identity", policy=body.policy)
    db.commit()
    return {"policy": body.policy}
