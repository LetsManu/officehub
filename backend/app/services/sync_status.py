"""Sync status per computer (the Windows app's OfficeHub folder): one app password = one device.

Every /api/sync request signed in with an app password counts as contact (so older app versions show up too). After
each sync round the app reports how it went (`POST /api/sync/report`): whether the round went through, the files
that did not reach the portal with a short reason, and how many changes are still waiting.
"""

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppPassword, SyncDevice, User, utcnow

CONTACT_EVERY = timedelta(minutes=1)  # contact is written at most this often (long polling asks every 25 s)
FRESH = timedelta(hours=24)  # synced within this time and no problems: green
MAX_FAILED = 20
NAME_LENGTH = 80
REASON_LENGTH = 120
PATH_LENGTH = 260


def _app_version(user_agent: str) -> str:
    """'OfficeHubApp/1.2.0 (windows; sync)' → '1.2.0'."""
    marker = "OfficeHubApp/"
    if marker not in user_agent:
        return ""
    return user_agent.split(marker, 1)[1].split(" ", 1)[0][:40]


def device_for(db: Session, password: AppPassword) -> SyncDevice:
    device = db.scalar(select(SyncDevice).where(SyncDevice.app_password_id == password.id))
    if device is None:
        device = SyncDevice(app_password_id=password.id, user_id=password.user_id)
        db.add(device)
    return device


def touch(db: Session, password: AppPassword, user_agent: str = "") -> None:
    """A sync request from this device: remember the contact (not more than once a minute)."""
    device = db.scalar(select(SyncDevice).where(SyncDevice.app_password_id == password.id))
    now = utcnow()
    if device is not None and device.last_contact_at is not None and now - device.last_contact_at < CONTACT_EVERY:
        return
    device = device or device_for(db, password)
    device.last_contact_at = now
    version = _app_version(user_agent)
    if version:
        device.app_version = version
    db.commit()


def _clean(text: str, length: int) -> str:
    return " ".join(str(text).split())[:length]


def record(db: Session, password: AppPassword, *, device_name: str, ok: bool, failed: list[tuple[str, str]],
           failed_count: int | None, pending_uploads: int, error: str, user_agent: str = "") -> SyncDevice:
    """What the app says about its last sync round."""
    device = device_for(db, password)
    now = utcnow()
    device.last_contact_at = device.last_report_at = now
    if ok:
        device.last_sync_at = now
    name = _clean(device_name, NAME_LENGTH)
    if name:
        device.device_name = name
    version = _app_version(user_agent)
    if version:
        device.app_version = version
    kept = [{"path": _clean(p, PATH_LENGTH), "reason": _clean(r, REASON_LENGTH)} for p, r in failed[:MAX_FAILED]]
    device.failed = json.dumps(kept, ensure_ascii=False)
    device.failed_count = max(len(failed), failed_count or 0)
    device.pending_uploads = max(0, pending_uploads)
    device.last_error = _clean(error, 200) if error else (kept[0]["reason"] if kept else "")
    db.commit()
    return device


def status(device: SyncDevice | None, now: datetime | None = None) -> str:
    """green: synced within 24 h without problems; amber: problems or longer ago; grey: never synced."""
    if device is None:
        return "never"
    # An app without reports only says that it is there: its contact stands for the last sync
    seen = device.last_sync_at if device.last_report_at is not None else device.last_contact_at
    if seen is None:
        return "problem" if device.failed_count or device.last_error else "never"
    if device.failed_count or device.last_error or (now or utcnow()) - seen > FRESH:
        return "problem"
    return "ok"


def failed_list(device: SyncDevice) -> list[dict]:
    try:
        items = json.loads(device.failed or "[]")
    except ValueError:
        return []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def for_user(db: Session, user: User) -> dict[int, SyncDevice]:
    """My devices by app password id."""
    rows = db.scalars(select(SyncDevice).where(SyncDevice.user_id == user.id))
    return {d.app_password_id: d for d in rows}


def everyone(db: Session) -> list[tuple[SyncDevice, AppPassword, User]]:
    rows = db.execute(
        select(SyncDevice, AppPassword, User)
        .join(AppPassword, AppPassword.id == SyncDevice.app_password_id)
        .join(User, User.id == SyncDevice.user_id)
        .order_by(User.last_name, User.first_name, SyncDevice.device_name)
    )
    return [(d, p, u) for d, p, u in rows]
