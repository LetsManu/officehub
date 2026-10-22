"""Backups for administrators: status, settings, "Back up now", download and restore."""

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..db import SessionLocal
from ..deps import DB, Admin
from ..schemas import UtcDateTime
from ..services import backup
from ..services.audit import audit
from ..services.settings import set_setting

router = APIRouter(prefix="/api/admin/backups", tags=["admin"])


class BackupItem(BaseModel):
    name: str
    size: int
    created_at: UtcDateTime


class BackupOptions(BaseModel):
    enabled: bool = True
    hour: int = Field(2, ge=0, le=23)
    keep: int = Field(14, ge=1, le=365)


class BackupStatus(BaseModel):
    at: datetime | None = None
    ok: bool | None = None
    name: str | None = None
    size: int | None = None
    error: str | None = None


class BackupOverview(BaseModel):
    available: bool
    folder: str
    options: BackupOptions
    last: BackupStatus
    items: list[BackupItem]


def _overview(db: DB) -> BackupOverview:
    return BackupOverview(available=backup.available(), folder=str(backup.folder()), options=BackupOptions(**backup.options(db)),
                          last=BackupStatus(**{k: v for k, v in backup.status(db).items() if k != "day"}),
                          items=[BackupItem(**b) for b in backup.list_backups()])


@router.get("", response_model=BackupOverview)
def overview(user: Admin, db: DB) -> BackupOverview:
    return _overview(db)


@router.put("/settings", response_model=BackupOverview)
def save_options(body: BackupOptions, user: Admin, db: DB) -> BackupOverview:
    set_setting(db, "backup", body.model_dump())
    audit(db, user, "settings_updated", "backup", **body.model_dump())
    db.commit()
    return _overview(db)


@router.post("", response_model=BackupItem, status_code=201)
def back_up_now(user: Admin) -> BackupItem:
    return BackupItem(**backup.run_now("manual"))


@router.get("/{name}/download")
def download(name: str, user: Admin) -> FileResponse:
    return FileResponse(backup.path_of(name), media_type="application/gzip", filename=name)


@router.post("/{name}/restore", response_model=BackupItem)
def restore(name: str, user: Admin, db: DB) -> BackupItem:
    """Everything goes back to the state of this backup; the state before is kept as "…-restore.tar.gz"."""
    who = user.email
    db.close()  # the database file is swapped underneath
    safety = backup.restore(name)
    with SessionLocal() as fresh:
        audit(fresh, None, "backup_restored", name, by=who, saved_before=safety["name"])
        fresh.commit()
    return BackupItem(**safety)
