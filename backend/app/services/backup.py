"""Automatic backups: every night the database and all uploaded files go into one archive in the backup folder.

The folder is `BACKUP_DIR` (the stack mounts its own volume there; point it at a NAS share to keep copies off the
server). Archives are plain `.tar.gz` files: `officehub.db` (a consistent copy made with SQLite's backup function, so
nobody has to stop working), `uploads/` and `manifest.json`. The newest `keep` archives stay, older ones are removed.

Restoring first makes one more archive of the current state, then swaps in the database and the files of the chosen
archive while the portal keeps running. Sign-ins come from the archive too: whoever signed in after it was made has
to sign in again.
"""

import asyncio
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import settings
from ..db import Base, SessionLocal, add_missing_columns, engine
from ..errors import ApiError
from .settings import get_setting, set_setting

logger = logging.getLogger("officehub.backup")

NAME = re.compile(r"^officehub-\d{8}-\d{6}(-[a-z]+)?\.tar\.gz$")
DEFAULTS = {"enabled": True, "hour": 2, "keep": 14}
CHECK_SECONDS = 300
_lock = threading.RLock()


def available() -> bool:
    """Backups cover the built-in SQLite database (another database server has its own backup tools)."""
    return settings.database_url.startswith("sqlite:///")


def folder() -> Path:
    return settings.backup_dir


def options(db) -> dict:
    stored = get_setting(db, "backup", {}) or {}
    return {**DEFAULTS, **{k: stored[k] for k in DEFAULTS if k in stored}}


def status(db) -> dict:
    return get_setting(db, "backup.status", {}) or {}


def _now() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.timezone))
    except (KeyError, ValueError):
        return datetime.now()


def _db_path() -> Path:
    return Path(settings.database_url.removeprefix("sqlite:///"))


def list_backups() -> list[dict]:
    if not folder().is_dir():
        return []
    items = []
    for path in folder().iterdir():
        if NAME.match(path.name) and path.is_file():
            stat = path.stat()
            items.append({"name": path.name, "size": stat.st_size,
                          "created_at": datetime.fromtimestamp(stat.st_mtime).astimezone()})
    return sorted(items, key=lambda x: x["name"], reverse=True)


def path_of(name: str) -> Path:
    path = folder() / name
    if not NAME.match(name) or not path.is_file():
        raise ApiError(404, "not_found", "This backup does not exist.")
    return path


def create(reason: str = "") -> dict:
    """Write one archive now; returns its entry. `reason` marks archives made by hand ("manual", "restore")."""
    if not available():
        raise ApiError(409, "backup_unavailable", "Backups only cover the built-in database.")
    with _lock:
        target = folder()
        target.mkdir(parents=True, exist_ok=True)
        stamp = _now().strftime("%Y%m%d-%H%M%S")
        name = f"officehub-{stamp}{f'-{reason}' if reason else ''}.tar.gz"
        part = target / f".{name}.part"
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=settings.data_dir) as work:
                copy = Path(work) / "officehub.db"
                source, dest = sqlite3.connect(_db_path()), sqlite3.connect(copy)
                try:
                    source.backup(dest)
                finally:
                    dest.close()
                    source.close()
                manifest = json.dumps({"version": settings.app_version, "created_at": _now().isoformat()}).encode()
                with tarfile.open(part, "w:gz") as tar:
                    info = tarfile.TarInfo("manifest.json")
                    info.size = len(manifest)
                    tar.addfile(info, io.BytesIO(manifest))
                    tar.add(copy, "officehub.db")
                    if settings.upload_dir.is_dir():
                        tar.add(settings.upload_dir, "uploads")
            os.replace(part, target / name)
        finally:
            part.unlink(missing_ok=True)
        _prune()
    return next(b for b in list_backups() if b["name"] == name)


def _prune() -> None:
    with SessionLocal() as db:
        keep = max(1, int(options(db)["keep"]))
    for old in list_backups()[keep:]:
        (folder() / old["name"]).unlink(missing_ok=True)


def _record(ok: bool, entry: dict | None = None, error: str | None = None) -> None:
    with SessionLocal() as db:
        set_setting(db, "backup.status", {
            "day": _now().date().isoformat(), "at": _now().isoformat(), "ok": ok,
            "name": entry["name"] if entry else None, "size": entry["size"] if entry else None, "error": error,
        })
        db.commit()


def run_now(reason: str = "manual") -> dict:
    try:
        entry = create(reason)
    except ApiError:
        raise
    except Exception as e:  # noqa: BLE001 - shown to the admin as it is (full disk, folder not writable …)
        logger.exception("Backup failed")
        _record(False, error=str(e) or e.__class__.__name__)
        raise ApiError(500, "backup_failed", f"The backup could not be written: {e}") from None
    _record(True, entry)
    return entry


def run_if_due() -> None:
    """Once a day after the chosen hour (also when the server was off at that time)."""
    if not available():
        return
    with SessionLocal() as db:
        opts, last = options(db), status(db)
    now = _now()
    if not opts["enabled"] or now.hour < int(opts["hour"]) or last.get("day") == now.date().isoformat():
        return
    try:
        run_now("")
    except ApiError:
        pass  # recorded; tried again tomorrow


async def nightly() -> None:
    await asyncio.sleep(CHECK_SECONDS)  # let the portal start first
    while True:
        try:
            await asyncio.to_thread(run_if_due)
        except Exception:  # noqa: BLE001 - the loop must keep running
            logger.exception("Backup check failed")
        await asyncio.sleep(CHECK_SECONDS)


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
            raise ApiError(422, "backup_invalid", "This file is not an OfficeHub backup.")
        if m.name in ("officehub.db", "manifest.json") or parts[0] == "uploads":
            members.append(m)
    return members


def restore(name: str) -> dict:
    """Bring back the database and files of this archive; the current state is saved first."""
    source = path_of(name)
    with _lock:
        with tempfile.TemporaryDirectory(dir=settings.data_dir) as work:
            work_path = Path(work)
            try:
                with tarfile.open(source, "r:gz") as tar:
                    tar.extractall(work_path, members=_safe_members(tar), filter="data")
            except (tarfile.TarError, OSError, EOFError):
                raise ApiError(422, "backup_invalid", "This file is not an OfficeHub backup.") from None
            new_db = work_path / "officehub.db"
            try:
                check = sqlite3.connect(new_db)
                ok = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                check.close()
            except sqlite3.DatabaseError:
                ok = False
            if not new_db.is_file() or not ok:
                raise ApiError(422, "backup_invalid", "This file is not an OfficeHub backup.")

            safety = run_now("restore")

            engine.dispose()
            target = _db_path()
            for suffix in ("-wal", "-shm"):
                Path(f"{target}{suffix}").unlink(missing_ok=True)
            shutil.move(str(new_db), str(target))
            engine.dispose()

            uploads = settings.upload_dir
            old = uploads.with_name(f"{uploads.name}.old")
            shutil.rmtree(old, ignore_errors=True)
            if uploads.exists():
                uploads.rename(old)
            restored = work_path / "uploads"
            if restored.is_dir():
                shutil.move(str(restored), str(uploads))
            else:
                uploads.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(old, ignore_errors=True)

        # An archive from an older version gets the newer tables and columns
        Base.metadata.create_all(engine)
        add_missing_columns()
        _record(True, safety)
    return safety
