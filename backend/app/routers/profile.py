import json
from datetime import date
from typing import Annotated

import segno
from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select

from .. import totp
from ..deps import DB, CurrentUser
from ..errors import ApiError, forbidden
from ..files import delete_quietly, save_upload
from ..config import settings
from ..models import AppPassword, SyncDevice, User
from ..schemas import PasswordChange, ProfileUpdate, UserOut, UtcDateTime
from ..services import app_passwords, sync_status
from ..services.audit import audit
from ..security import hash_password, hash_token, verify_password
from ..services.security import two_factor_required
from .branding import current_branding
from .sync import SyncDeviceOut, device_out

router = APIRouter(prefix="/api/profile", tags=["profile"])

_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


@router.get("", response_model=UserOut)
def get_profile(user: CurrentUser) -> User:
    return user


@router.patch("", response_model=UserOut)
def update_profile(body: ProfileUpdate, user: CurrentUser, db: DB) -> User:
    # Only personal fields are accepted; role and email cannot be changed here.
    changes = body.model_dump(exclude_unset=True)
    if "birthday_day" in changes or "birthday_month" in changes:
        day, month = changes.pop("birthday_day", None), changes.pop("birthday_month", None)
        if (day is None) != (month is None) or (day and month and day > _DAYS_IN_MONTH[month - 1]):
            error = ApiError(422, "birthday_invalid", "Please choose a valid day and month.")
            error.field = "birthday_day"  # type: ignore[attr-defined]
            raise error
        user.birthday_day, user.birthday_month = day, month
    for field, value in changes.items():
        if value is None:
            continue
        if field == "pinned_tiles":
            value = ",".join(dict.fromkeys(value))
        setattr(user, field, value)
    db.commit()
    return user


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, user: CurrentUser, db: DB) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise ApiError(422, "wrong_password", "Your current password is not correct.")
    user.password_hash = hash_password(body.new_password)
    db.commit()


# ---------- Photo ----------

PHOTO_TYPES = {"png", "jpg", "jpeg"}
MAX_PHOTO_BYTES = 1024 * 1024


@router.post("/photo", response_model=UserOut)
async def upload_photo(user: CurrentUser, db: DB, file: UploadFile = File(...)) -> User:
    """The browser crops and scales the photo to a small square before uploading."""
    stored = await save_upload(file, PHOTO_TYPES, "photos")
    if stored.size > MAX_PHOTO_BYTES:
        delete_quietly(stored.relative_path)
        raise ApiError(422, "file_too_large", "The photo can be at most 1 MB.")
    old, user.photo_path = user.photo_path, stored.relative_path
    db.commit()
    delete_quietly(old)
    return user


@router.delete("/photo", response_model=UserOut)
def delete_photo(user: CurrentUser, db: DB) -> User:
    old, user.photo_path = user.photo_path, None
    db.commit()
    delete_quietly(old)
    return user


# ---------- Deputy ----------


class DeputyIn(BaseModel):
    deputy_id: int | None = None
    until: date | None = None


@router.put("/deputy", response_model=UserOut)
def set_deputy(body: DeputyIn, user: CurrentUser, db: DB) -> User:
    """Managers choose who decides for their team while they are away (until a date)."""
    if not user.is_approver:
        raise forbidden()
    if body.deputy_id is None:
        user.deputy_id, user.deputy_until = None, None
    else:
        deputy = db.get(User, body.deputy_id)
        if deputy is None or not deputy.is_active or deputy.id == user.id:
            raise _field_error("deputy_id", "deputy_invalid", "Please choose an active colleague.")
        if body.until is None or body.until < date.today():
            raise _field_error("until", "until_past", "Please choose today or a later date.")
        user.deputy_id, user.deputy_until = deputy.id, body.until
    db.commit()
    return user


# ---------- Two-factor sign-in ----------


class TwoFactorSetup(BaseModel):
    secret: str
    otpauth_url: str
    qr_image: str  # data: URI of an SVG QR code


class CodeIn(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]


class PasswordIn(BaseModel):
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class RecoveryCodes(BaseModel):
    recovery_codes: list[str]


def _field_error(field: str, code: str, message: str) -> ApiError:
    error = ApiError(422, code, message)
    error.field = field  # type: ignore[attr-defined]
    return error


@router.post("/2fa/setup", response_model=TwoFactorSetup)
def two_factor_setup(user: CurrentUser, db: DB) -> TwoFactorSetup:
    """Creates a new secret. It only becomes active after a correct code was entered."""
    if user.totp_enabled:
        raise ApiError(409, "two_factor_active", "Two-factor sign-in is already switched on.")
    user.totp_secret = totp.new_secret()
    db.commit()
    issuer = current_branding(db).company_name or "OfficeHub"
    uri = totp.provisioning_uri(user.totp_secret, user.email, issuer)
    image = segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#111827", light="#ffffff")
    return TwoFactorSetup(secret=user.totp_secret, otpauth_url=uri, qr_image=image)


@router.post("/2fa/enable", response_model=RecoveryCodes)
def two_factor_enable(body: CodeIn, user: CurrentUser, db: DB) -> RecoveryCodes:
    if user.totp_enabled:
        raise ApiError(409, "two_factor_active", "Two-factor sign-in is already switched on.")
    if not user.totp_secret or not totp.verify(user.totp_secret, body.code):
        raise _field_error("code", "code_invalid", "The code is not correct. Please try the current code.")
    codes = totp.new_recovery_codes()
    user.recovery_codes = json.dumps([hash_token(c) for c in codes])
    user.totp_enabled = True
    db.commit()
    return RecoveryCodes(recovery_codes=codes)


@router.post("/2fa/disable", response_model=UserOut)
def two_factor_disable(body: PasswordIn, user: CurrentUser, db: DB) -> User:
    if not verify_password(body.password, user.password_hash):
        raise _field_error("password", "wrong_password", "Your current password is not correct.")
    if two_factor_required(db, user):
        raise ApiError(409, "two_factor_required", "Two-factor sign-in is required for your role.")
    user.totp_enabled, user.totp_secret, user.recovery_codes = False, None, "[]"
    db.commit()
    return user


# ---------- app passwords: network drive and desktop programs ----------


class AppPasswordOut(BaseModel):
    id: int
    name: str
    created_at: UtcDateTime
    last_used_at: UtcDateTime | None
    device: SyncDeviceOut | None = None  # the computer that syncs its OfficeHub folder with this password


class AppPasswordCreated(AppPasswordOut):
    password: str  # shown once
    login: str
    drive_url: str


class AppPasswordIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


def _app_password_out(row: AppPassword, device: SyncDevice | None = None) -> AppPasswordOut:
    return AppPasswordOut(id=row.id, name=row.name, created_at=row.created_at, last_used_at=row.last_used_at,
                          device=device_out(device) if device is not None else None)


@router.get("/app-passwords", response_model=list[AppPasswordOut])
def list_app_passwords(user: CurrentUser, db: DB) -> list[AppPasswordOut]:
    rows = db.scalars(select(AppPassword).where(AppPassword.user_id == user.id).order_by(AppPassword.created_at.desc()))
    devices = sync_status.for_user(db, user)
    return [_app_password_out(r, devices.get(r.id)) for r in rows]


@router.post("/app-passwords", response_model=AppPasswordCreated, status_code=201)
def create_app_password(body: AppPasswordIn, user: CurrentUser, db: DB) -> AppPasswordCreated:
    if app_passwords.count(db, user) >= app_passwords.MAX_PER_USER:
        raise ApiError(409, "too_many_app_passwords", "Please remove an app password you no longer use first.")
    row, secret = app_passwords.create(db, user, body.name)
    audit(db, user, "app_password_created", "user", name=body.name)
    db.commit()
    return AppPasswordCreated(**_app_password_out(row).model_dump(), password=secret, login=user.email,
                              drive_url=f"{settings.portal_url}/dav/")


@router.delete("/app-passwords/{password_id}", status_code=204)
def delete_app_password(password_id: int, user: CurrentUser, db: DB) -> None:
    row = db.get(AppPassword, password_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "Not found.")
    db.delete(row)
    audit(db, user, "app_password_deleted", "user", name=row.name)
    db.commit()
