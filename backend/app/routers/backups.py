"""Backups for administrators: status, settings, "Back up now", download, restore and the copy on the NAS."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..db import SessionLocal
from ..deps import DB, Admin
from ..schemas import UtcDateTime
from ..services import backup, nas
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


class NasBase(BaseModel):
    kind: Literal["off", "smb", "sftp"] = "off"
    path: str = Field("", max_length=500)  # SMB share, e.g. //nas/backup or smb://nas/backup/officehub
    host: str = Field("", max_length=255)  # SFTP
    port: int = Field(22, ge=1, le=65535)
    folder: str = Field("", max_length=500)
    user: str = Field("", max_length=255)
    keep: int = Field(0, ge=0, le=365)  # 0 = as many as in the backup folder


class NasSettings(NasBase):
    # Empty when saving or testing = keep the stored password
    password: str = Field("", max_length=500)


class NasSettingsOut(NasBase):
    has_password: bool = False


class NasStatus(BaseModel):
    at: datetime | None = None
    ok: bool | None = None
    name: str | None = None
    code: str | None = None
    error: str | None = None
    running: bool = False
    count: int | None = None


class BackupOverview(BaseModel):
    available: bool
    folder: str
    options: BackupOptions
    last: BackupStatus
    items: list[BackupItem]
    nas: NasSettingsOut
    nas_last: NasStatus


def _overview(db: DB) -> BackupOverview:
    return BackupOverview(available=backup.available(), folder=str(backup.folder()), options=BackupOptions(**backup.options(db)),
                          last=BackupStatus(**{k: v for k, v in backup.status(db).items() if k != "day"}),
                          items=[BackupItem(**b) for b in backup.list_backups()],
                          nas=NasSettingsOut(**nas.public(nas.options(db))),
                          nas_last=NasStatus(**{k: v for k, v in nas.status(db).items() if k in NasStatus.model_fields}))


@router.get("", response_model=BackupOverview)
def overview(user: Admin, db: DB) -> BackupOverview:
    return _overview(db)


@router.put("/settings", response_model=BackupOverview)
def save_options(body: BackupOptions, user: Admin, db: DB) -> BackupOverview:
    set_setting(db, "backup", body.model_dump())
    audit(db, user, "settings_updated", "backup", **body.model_dump())
    db.commit()
    return _overview(db)


@router.put("/nas", response_model=BackupOverview)
def save_nas(body: NasSettings, user: Admin, db: DB) -> BackupOverview:
    data = nas.validate(body.model_dump(), nas.options(db))
    set_setting(db, nas.KEY, data)
    audit(db, user, "settings_updated", "backup.nas", kind=data["kind"], path=data["path"], host=data["host"],
          folder=data["folder"], user=data["user"], keep=data["keep"])
    db.commit()
    return _overview(db)


@router.post("/nas/test", status_code=204)
def test_nas(body: NasSettings, user: Admin, db: DB) -> None:
    """Try the values from the form (saved or not): connect, write a small file and delete it again."""
    data = nas.validate(body.model_dump(), nas.options(db))
    db.close()  # the test may take a while; it records the host key in its own session
    nas.test(data)


@router.post("", response_model=BackupItem, status_code=201)
def back_up_now(user: Admin, tasks: BackgroundTasks) -> BackupItem:
    entry = backup.run_now("manual", copy=False)
    # The copy to the NAS runs after the answer, so a big archive does not keep the page waiting
    nas.mark_running(entry["name"])
    tasks.add_task(nas.copy, entry["name"])
    return BackupItem(**entry)


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
