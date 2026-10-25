"""Is everything running? One overview for administrators (Administration → System).

Collects what OfficeHub knows about the parts of its stack without any outside service: the optional servers it
can reach inside the Docker network (craft apps, ONLYOFFICE, Jitsi), what it knows about the relay (coturn sits on
its own network, so only its shared secret and port are known), free disk space, the last backup and the size of
the database. It also notices leftovers and missing parts of an older stack file (the Collabora container that is
no longer used since 3.9, the `hostip` service, the craft container) and says what to do about them.
"""

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..config import _resolve, settings
from . import address, backup, craft, meetings, office
from .probe import reachable

COLLABORA_URL = "http://collabora:9980/hosting/discovery"
GB = 1024 ** 3
BACKUP_STALE = timedelta(days=2)


def shared_dir() -> Path:
    return Path(os.getenv("SHARED_DIR", "/shared"))


def _read(name: str) -> str | None:
    try:
        return (shared_dir() / name).read_text().strip() or None
    except OSError:
        return None


def in_stack() -> bool:
    """Running in the Docker stack (the shared folder of the stack file is mounted)."""
    return shared_dir().is_dir()


def collabora_running() -> bool:
    return reachable(COLLABORA_URL)


def public_address() -> dict:
    """The public address meetings tell people outside the office, and where it came from."""
    by_hand = os.getenv("PUBLIC_IP") or os.getenv("JITSI_PUBLIC_IP")
    if by_hand:
        return {"address": by_hand.strip(), "source": "setting"}
    if found := address.learned():
        return {"address": found, "source": "proxy"}
    host = urlparse(settings.portal_url).hostname
    if resolved := _resolve(host):
        return {"address": resolved, "source": "portal"}
    if noted := _read("public_ip"):
        return {"address": noted, "source": "noted"}
    return {"address": None, "source": None}


def relay() -> dict:
    """What is known about the relay (coturn). The backend cannot reach it: it has its own network."""
    own = bool(settings.ice_servers)
    servers = meetings.ice_servers()
    return {
        "own_servers": own,
        "secret": bool(settings.turn_secret) or _read("turn_secret") is not None,
        "port": settings.turn_port,
        "host": None if own else (address.learned() or meetings.portal_host()),
        "ready": bool(servers),
    }


def disk() -> dict:
    try:
        usage = shutil.disk_usage(settings.data_dir)
    except OSError:
        return {"free": None, "total": None, "state": "unknown"}
    free, total = usage.free, usage.total
    share = free / total if total else 0
    state = "bad" if free < GB or share < 0.05 else "warn" if free < 5 * GB or share < 0.10 else "ok"
    return {"free": free, "total": total, "state": state}


def database_size() -> int | None:
    if not settings.database_url.startswith("sqlite:///"):
        return None
    path = Path(settings.database_url.removeprefix("sqlite:///"))
    size = 0
    for part in (path, path.with_name(path.name + "-wal")):
        try:
            size += part.stat().st_size
        except OSError:
            pass
    return size or None


def last_backup(db: Session, now: datetime | None = None) -> dict:
    if not backup.available():
        return {"available": False, "enabled": False, "at": None, "ok": None, "error": None, "state": "unknown"}
    opts, last = backup.options(db), backup.status(db)
    at = last.get("at")
    state = "warn"
    if last.get("ok") is False:
        state = "bad"
    elif at and opts["enabled"]:
        try:
            when = datetime.fromisoformat(at)
            when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            state = "ok" if (now or datetime.now(timezone.utc)) - when < BACKUP_STALE else "warn"
        except ValueError:
            state = "warn"
    return {"available": True, "enabled": bool(opts["enabled"]), "at": at, "ok": last.get("ok"),
            "error": last.get("error"), "state": state}


def notices(parts: dict | None = None) -> list[str]:
    """Leftovers and missing parts of the stack, as codes the page explains (`system.notices.<code>`)."""
    found = []
    if collabora_running():
        found.append("collabora")
    if in_stack():
        if _read("host_ip") is None:
            found.append("hostip")
        if parts is None:
            parts = {"craft": craft.available(), "relay": relay()}
        if not parts["craft"]:
            found.append("craft")
        relay_info = parts["relay"]
        if relay_info["secret"] and not relay_info["own_servers"] and not public_address()["address"]:
            found.append("relay")
    return found


def overview(db: Session) -> dict:
    crafts = craft.available()
    relay_info = relay()
    jitsi_set_up = bool(settings.jitsi_internal_url)
    parts = {"craft": crafts, "relay": relay_info}
    return {
        "version": settings.app_version,
        "in_stack": in_stack(),
        "craft": {"apps": crafts, "running": bool(crafts), "set_up": bool(settings.craft_internal_url)},
        "onlyoffice": {"running": bool(office.available()), "set_up": bool(settings.onlyoffice_url)},
        "jitsi": {"running": meetings.jitsi_running(), "set_up": jitsi_set_up},
        "relay": relay_info,
        "disk": disk(),
        "database_size": database_size(),
        "backup": last_backup(db),
        "network": {
            "public": public_address(),
            "office": _read("host_ip"),
            "behind_proxy": address.learned() is not None,
            "portal_url": settings.portal_url,
        },
        "notices": notices(parts),
    }

