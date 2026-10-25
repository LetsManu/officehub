"""Second copy of every backup on the company's own NAS, so one dead disk cannot take everything.

Two kinds of targets: a Windows/SMB share (Synology, QNAP, Windows server: `\\\\nas\\backup` or
`smb://nas/backup/officehub`) through `smbprotocol`, or SFTP through `paramiko`. Both are pure Python and talk only to
the address the administrator entered – never to an outside service.

After every backup the new archive is uploaded as `.<name>.part` and renamed when complete, so a broken copy never
looks like a backup. The newest `keep` archives stay on the NAS (0 = as many as in the local folder); only files that
look like OfficeHub archives are ever removed. A failing copy never touches the local backup: it is logged and shown
in Administration → Backups.

The password is kept in the settings like the client secret of the company login and never sent to the browser. For
SFTP the NAS's host key is remembered on the first successful connection (like `ssh` does); if it changes later,
OfficeHub stops copying until the administrator saves the settings again.
"""

import logging
import secrets
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Protocol

from ..db import SessionLocal
from ..errors import ApiError
from .settings import get_setting, set_setting

logger = logging.getLogger("officehub.backup.nas")

KEY = "backup.nas"
STATUS_KEY = "backup.nas.status"
DEFAULTS = {"kind": "off", "path": "", "host": "", "port": 22, "folder": "", "user": "", "password": "", "keep": 0,
            "host_key": ""}
TIMEOUT = 20
RUNNING_FOR_AT_MOST = timedelta(hours=6)  # a "copying …" older than this was cut off (server restarted)
_lock = threading.Lock()

MESSAGES = {
    "nas_auth": "The NAS did not accept the user name or password.",
    "nas_not_found": "This share or folder was not found on the NAS.",
    "nas_unreachable": "The NAS cannot be reached. Check the address and that it is switched on.",
    "nas_denied": "This user may not write to that folder on the NAS.",
    "nas_full": "The NAS is full.",
    "nas_host_key": "The NAS identifies itself differently than before. Save the NAS settings again if that is expected.",
    "nas_failed": "Copying to the NAS did not work.",
}


class NasError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or MESSAGES.get(code, MESSAGES["nas_failed"]))
        self.code = code

    def api(self) -> ApiError:
        return ApiError(422, self.code, str(self))


# ---------------------------------------------------------------------------------------------------------- settings


def options(db) -> dict:
    stored = get_setting(db, KEY, {}) or {}
    return {**DEFAULTS, **{k: stored[k] for k in DEFAULTS if k in stored}}


def public(opts: dict) -> dict:
    """What the browser may see: everything except the password (only whether one is set) and the host key."""
    return {**{k: v for k, v in opts.items() if k not in ("password", "host_key")}, "has_password": bool(opts["password"])}


def configured(opts: dict) -> bool:
    return opts["kind"] in ("smb", "sftp")


def parse_share(path: str) -> tuple[str, int, str, list[str]]:
    """`\\\\nas\\backup\\sub`, `//nas/backup/sub` or `smb://nas[:port]/backup/sub` → (server, port, share, folders)."""
    raw = path.strip()
    if raw.lower().startswith("smb://"):
        raw = raw[6:]
    raw = raw.replace("\\", "/").strip("/")
    parts = [p for p in raw.split("/") if p]
    if len(parts) < 2 or any(p in (".", "..") for p in parts):
        raise ApiError(422, "nas_address", "Please enter the share like \\\\nas\\backup.")
    server, port = parts[0], 445
    if ":" in server:
        server, _, number = server.partition(":")
        if not number.isdigit() or not 0 < int(number) < 65536:
            raise ApiError(422, "nas_address", "Please enter the share like \\\\nas\\backup.")
        port = int(number)
    return server, port, parts[1], parts[2:]


def validate(data: dict, stored: dict) -> dict:
    """Clean the values from the form; an empty password keeps the stored one."""
    data = {**DEFAULTS, **{k: v.strip() if isinstance(v, str) and k != "password" else v for k, v in data.items()}}
    same_target = (data["kind"], data["host"], int(data["port"]), data["path"]) == (
        stored["kind"], stored["host"], int(stored["port"]), stored["path"])
    if not data["password"]:
        data["password"] = stored["password"]
    data["host_key"] = stored["host_key"] if same_target else ""
    if data["kind"] == "smb":
        parse_share(data["path"])
    elif data["kind"] == "sftp":
        if not data["host"] or any(c in data["host"] for c in " /\\@"):
            raise ApiError(422, "nas_host", "Please enter the address of the NAS.")
        if not data["user"]:
            raise ApiError(422, "nas_user", "Please enter the user name for the NAS.")
    return data


def status(db) -> dict:
    last = get_setting(db, STATUS_KEY, {}) or {}
    if last.get("running"):
        try:
            started = datetime.fromisoformat(last.get("started", ""))
        except ValueError:
            started = None
        if started is None or datetime.now(started.tzinfo) - started > RUNNING_FOR_AT_MOST:
            last = {**last, "running": False}
    return last


def _save_status(**values) -> None:
    with SessionLocal() as db:
        set_setting(db, STATUS_KEY, {**(get_setting(db, STATUS_KEY, {}) or {}), **values})
        db.commit()


# --------------------------------------------------------------------------------------------------------- transports


class Transport(Protocol):
    host_key: str  # SFTP: "type base64" of the NAS's key; empty for SMB

    def listdir(self) -> list[str]: ...
    def upload(self, local: Path, name: str) -> None: ...
    def write(self, name: str, data: bytes) -> None: ...
    def remove(self, name: str) -> None: ...


def _smb_error(e: BaseException) -> NasError:
    from smbprotocol.exceptions import SMBAuthenticationError, SMBConnectionClosed, SMBException
    from smbprotocol.header import NtStatus

    if isinstance(e, NasError):
        return e
    if isinstance(e, SMBAuthenticationError):
        return NasError("nas_auth")
    status = getattr(e, "ntstatus", None) or getattr(e, "status", None)
    if status in (NtStatus.STATUS_LOGON_FAILURE, NtStatus.STATUS_WRONG_PASSWORD, NtStatus.STATUS_PASSWORD_EXPIRED,
                  0xC0000072, 0xC000006E):  # account disabled / restricted
        return NasError("nas_auth")
    if status in (NtStatus.STATUS_BAD_NETWORK_NAME, NtStatus.STATUS_OBJECT_PATH_NOT_FOUND,
                  NtStatus.STATUS_OBJECT_NAME_NOT_FOUND, 0xC00000BE):  # bad network path
        return NasError("nas_not_found")
    if status == NtStatus.STATUS_ACCESS_DENIED:
        return NasError("nas_denied")
    if status == NtStatus.STATUS_DISK_FULL:
        return NasError("nas_full")
    if isinstance(e, SMBConnectionClosed) or isinstance(e, ValueError) and "connect" in str(e).lower():
        return NasError("nas_unreachable")
    if isinstance(e, OSError) and not isinstance(e, SMBException):  # socket errors: no route, refused, timeout
        return NasError("nas_unreachable")
    return NasError("nas_failed", f"{MESSAGES['nas_failed']} ({e or e.__class__.__name__})")


class SmbTransport:
    host_key = ""

    def __init__(self, opts: dict):
        import smbclient

        self._smb = smbclient
        server, port, share, folders = parse_share(opts["path"])
        self._cache: dict = {}
        self._kw = {"port": port, "connection_cache": self._cache}
        self._server = server
        try:
            smbclient.register_session(server, username=opts["user"] or None, password=opts["password"] or None,
                                       connection_timeout=TIMEOUT, **self._kw)
            self._dir = "\\".join([f"\\\\{server}", share, *folders])
            if folders:
                smbclient.makedirs(self._dir, exist_ok=True, **self._kw)
            else:
                smbclient.listdir(self._dir, **self._kw)  # the share exists and we may look into it
        except Exception as e:  # noqa: BLE001 - turned into a plain-language reason
            self.close()
            raise _smb_error(e) from None

    def _path(self, name: str) -> str:
        return f"{self._dir}\\{name}"

    def _do(self, fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001
            raise _smb_error(e) from None

    def listdir(self) -> list[str]:
        return self._do(lambda: self._smb.listdir(self._dir, **self._kw))

    def upload(self, local: Path, name: str) -> None:
        part = self._path(f".{name}.part")

        def copy():
            with open(local, "rb") as src, self._smb.open_file(part, mode="wb", **self._kw) as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
            self._smb.replace(part, self._path(name), **self._kw)

        try:
            self._do(copy)
        except NasError:
            try:
                self._smb.remove(part, **self._kw)
            except Exception:  # noqa: BLE001 - best effort
                pass
            raise

    def write(self, name: str, data: bytes) -> None:
        def put():
            with self._smb.open_file(self._path(name), mode="wb", **self._kw) as f:
                f.write(data)
        self._do(put)

    def remove(self, name: str) -> None:
        self._do(lambda: self._smb.remove(self._path(name), **self._kw))

    def close(self) -> None:
        try:
            self._smb.reset_connection_cache(fail_on_error=False, connection_cache=self._cache)
        except Exception:  # noqa: BLE001
            pass


def _sftp_error(e: BaseException) -> NasError:
    import errno

    import paramiko

    if isinstance(e, NasError):
        return e
    if isinstance(e, paramiko.AuthenticationException):
        return NasError("nas_auth")
    if isinstance(e, (socket.gaierror, TimeoutError, ConnectionError, paramiko.ssh_exception.NoValidConnectionsError)):
        return NasError("nas_unreachable")
    if isinstance(e, OSError) and e.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ETIMEDOUT):
        return NasError("nas_unreachable")
    if isinstance(e, OSError) and e.errno == errno.ENOENT:
        return NasError("nas_not_found")
    if isinstance(e, PermissionError) or isinstance(e, OSError) and e.errno in (errno.EACCES, errno.EPERM):
        return NasError("nas_denied")
    if isinstance(e, OSError) and e.errno == errno.ENOSPC:
        return NasError("nas_full")
    return NasError("nas_failed", f"{MESSAGES['nas_failed']} ({e or e.__class__.__name__})")


class SftpTransport:
    def __init__(self, opts: dict):
        import paramiko

        self._sock = self._transport = self._sftp = None
        try:
            self._sock = socket.create_connection((opts["host"], int(opts["port"] or 22)), timeout=TIMEOUT)
            self._transport = paramiko.Transport(self._sock)
            self._transport.banner_timeout = self._transport.auth_timeout = TIMEOUT
            self._transport.start_client(timeout=TIMEOUT)
            key = self._transport.get_remote_server_key()
            self.host_key = f"{key.get_name()} {key.get_base64()}"
            if opts["host_key"] and opts["host_key"] != self.host_key:
                raise NasError("nas_host_key")
            self._transport.auth_password(opts["user"], opts["password"])
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
            self._sftp.get_channel().settimeout(TIMEOUT * 3)
            self._dir = opts["folder"].rstrip("/") or "."
            self._makedirs(self._dir)
        except Exception as e:  # noqa: BLE001 - turned into a plain-language reason
            self.close()
            raise _sftp_error(e) from None

    def _makedirs(self, folder: str) -> None:
        if folder in (".", "/", ""):
            return
        try:
            self._sftp.stat(folder)
        except FileNotFoundError:
            parent = folder.rsplit("/", 1)[0] if "/" in folder.strip("/") else ""
            if parent and parent != folder:
                self._makedirs(parent)
            self._sftp.mkdir(folder)

    def _path(self, name: str) -> str:
        return f"{self._dir}/{name}"

    def _do(self, fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001
            raise _sftp_error(e) from None

    def listdir(self) -> list[str]:
        return self._do(self._sftp.listdir, self._dir)

    def upload(self, local: Path, name: str) -> None:
        part = self._path(f".{name}.part")

        def put():
            self._sftp.put(str(local), part, confirm=True)
            self._sftp.posix_rename(part, self._path(name))

        try:
            self._do(put)
        except NasError:
            try:
                self._sftp.remove(part)
            except Exception:  # noqa: BLE001 - best effort
                pass
            raise

    def write(self, name: str, data: bytes) -> None:
        def put():
            with self._sftp.open(self._path(name), "wb") as f:
                f.write(data)
        self._do(put)

    def remove(self, name: str) -> None:
        self._do(self._sftp.remove, self._path(name))

    def close(self) -> None:
        for part in (self._sftp, self._transport, self._sock):
            try:
                if part is not None:
                    part.close()
            except Exception:  # noqa: BLE001
                pass


@contextmanager
def open_transport(opts: dict) -> Iterator[Transport]:
    """Connect to the NAS (tests replace this with a fake). Raises `NasError` with a plain-language reason."""
    transport = SmbTransport(opts) if opts["kind"] == "smb" else SftpTransport(opts)
    try:
        yield transport
    finally:
        transport.close()


# ----------------------------------------------------------------------------------------------------------- actions


def _remember_host_key(opts: dict, seen: str) -> None:
    """Trust on first use: keep the key the NAS showed the first time for these saved settings."""
    if opts["kind"] != "sftp" or not seen or opts["host_key"]:
        return
    with SessionLocal() as db:
        stored = options(db)
        if (stored["kind"], stored["host"], int(stored["port"])) == ("sftp", opts["host"], int(opts["port"])) and not stored["host_key"]:
            set_setting(db, KEY, {**stored, "host_key": seen})
            db.commit()


def test(opts: dict) -> None:
    """Connect, write a small file and delete it again; raises `ApiError` with a plain-language code."""
    if not configured(opts):
        raise ApiError(422, "nas_off", "Choose the kind of NAS first.")
    name = f".officehub-test-{secrets.token_hex(4)}.txt"
    try:
        with open_transport(opts) as nas:
            nas.write(name, b"OfficeHub backup test - this file can be deleted.\n")
            nas.remove(name)
            _remember_host_key(opts, nas.host_key)
    except NasError as e:
        raise e.api() from None
    except Exception as e:  # noqa: BLE001 - shown as it is
        logger.exception("NAS test failed")
        raise NasError("nas_failed", f"{MESSAGES['nas_failed']} ({e or e.__class__.__name__})").api() from None


def mark_running(name: str) -> None:
    with SessionLocal() as db:
        if not configured(options(db)):
            return
    _save_status(running=True, started=datetime.now().astimezone().isoformat(), pending=name)


def copy(name: str) -> None:
    """Copy this archive from the backup folder to the NAS and trim old copies there. Never raises."""
    from . import backup  # backup imports this module lazily too

    with SessionLocal() as db:
        opts, local_keep = options(db), int(backup.options(db)["keep"])
    if not configured(opts):
        return
    keep = max(1, int(opts["keep"]) or local_keep)
    with _lock:
        _save_status(running=True, started=datetime.now().astimezone().isoformat(), pending=name)
        try:
            local = backup.path_of(name)
            with open_transport(opts) as nas:
                _remember_host_key(opts, nas.host_key)
                nas.upload(local, name)
                copies = sorted((n for n in nas.listdir() if backup.NAME.match(n)), reverse=True)
                for old in copies[keep:]:
                    nas.remove(old)
            _save_status(running=False, at=datetime.now().astimezone().isoformat(), ok=True, name=name, code=None,
                         error=None, count=min(len(copies), keep))
        except Exception as e:  # noqa: BLE001 - the local backup is done; this only gets shown and logged
            if isinstance(e, NasError):
                err = e
            else:
                err = NasError("nas_failed", f"{MESSAGES['nas_failed']} ({getattr(e, 'detail', None) or e or e.__class__.__name__})")
            logger.warning("Copy of %s to the NAS failed: %s", name, err)
            _save_status(running=False, at=datetime.now().astimezone().isoformat(), ok=False, name=name, code=err.code,
                         error=str(err))
