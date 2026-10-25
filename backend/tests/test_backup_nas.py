"""Second copy of every backup on the company's NAS (SMB share or SFTP); no real network – the transport is faked."""

from contextlib import contextmanager
from datetime import datetime

import pytest

from app.db import SessionLocal
from app.services import backup, nas

SMB = {"kind": "smb", "path": "\\\\nas\\backup\\officehub", "user": "backup", "password": "Geheim-123", "keep": 0}


class FakeNas:
    """Stands in for the SMB/SFTP connection: files live in a dict."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.fail: Exception | None = None
        self.connects: list[dict] = []
        self.written: list[str] = []
        self.host_key = ""

    @contextmanager
    def open(self, opts):
        self.connects.append(opts)
        if self.fail:
            raise self.fail
        yield self

    def listdir(self):
        return list(self.files)

    def upload(self, local, name):
        self.files[name] = local.read_bytes()

    def write(self, name, data):
        self.written.append(name)
        self.files[name] = data

    def remove(self, name):
        del self.files[name]


@pytest.fixture
def fake(monkeypatch):
    f = FakeNas()
    monkeypatch.setattr(nas, "open_transport", f.open)
    for b in backup.list_backups():
        (backup.folder() / b["name"]).unlink()
    return f


def _overview(client):
    return client.get("/api/admin/backups").json()


def test_only_admins(anna, fake):
    assert anna.put("/api/admin/backups/nas", json=SMB).status_code == 403
    assert anna.post("/api/admin/backups/nas/test", json=SMB).status_code == 403
    assert anna.get("/api/admin/backups").status_code == 403
    assert fake.connects == []


def test_settings_saved_password_hidden(julia, fake):
    assert _overview(julia)["nas"]["kind"] == "off"
    saved = julia.put("/api/admin/backups/nas", json=SMB)
    assert saved.status_code == 200, saved.text
    assert "Geheim-123" not in saved.text and "password" not in saved.json()["nas"]
    assert saved.json()["nas"].items() >= {"kind": "smb", "path": "\\\\nas\\backup\\officehub", "user": "backup", "has_password": True}.items()
    assert "Geheim-123" not in julia.get("/api/admin/backups").text
    # Saving without a password keeps the stored one
    julia.put("/api/admin/backups/nas", json={**SMB, "password": "", "keep": 5})
    with SessionLocal() as db:
        assert nas.options(db)["password"] == "Geheim-123" and nas.options(db)["keep"] == 5
    assert any(e["action"] == "settings_updated" for e in julia.get("/api/admin/audit").json()["items"])
    assert "Geheim-123" not in julia.get("/api/admin/audit").text

    bad = julia.put("/api/admin/backups/nas", json={**SMB, "path": "nas"})
    assert bad.status_code == 422 and bad.json()["code"] == "nas_address"
    assert julia.put("/api/admin/backups/nas", json={"kind": "sftp", "host": "", "user": "x"}).json()["code"] == "nas_host"
    assert julia.put("/api/admin/backups/nas", json={"kind": "sftp", "host": "nas", "user": ""}).json()["code"] == "nas_user"
    assert julia.put("/api/admin/backups/nas", json={**SMB, "kind": "ftp"}).status_code == 422


@pytest.mark.parametrize("path, expected", [
    ("\\\\nas\\backup", ("nas", 445, "backup", [])),
    ("smb://nas.firma.local/backup/officehub", ("nas.firma.local", 445, "backup", ["officehub"])),
    ("//192.168.1.5:4455/daten/a/b/", ("192.168.1.5", 4455, "daten", ["a", "b"])),
])
def test_share_addresses(path, expected):
    assert nas.parse_share(path) == expected


def test_test_button(julia, fake):
    ok = julia.post("/api/admin/backups/nas/test", json=SMB)
    assert ok.status_code == 204, ok.text
    assert len(fake.written) == 1 and fake.files == {}  # written and removed again
    assert fake.connects[0]["password"] == "Geheim-123"

    # The stored password is used when the form leaves it empty
    julia.put("/api/admin/backups/nas", json=SMB)
    julia.post("/api/admin/backups/nas/test", json={**SMB, "password": ""})
    assert fake.connects[-1]["password"] == "Geheim-123"

    fake.fail = nas.NasError("nas_auth")
    wrong = julia.post("/api/admin/backups/nas/test", json=SMB)
    assert wrong.status_code == 422 and wrong.json()["code"] == "nas_auth" and wrong.json()["detail"]
    fake.fail = RuntimeError("boom")
    assert julia.post("/api/admin/backups/nas/test", json=SMB).json()["code"] == "nas_failed"
    assert julia.post("/api/admin/backups/nas/test", json={"kind": "off"}).json()["code"] == "nas_off"


def test_copy_after_back_up_now(julia, fake):
    julia.post("/api/admin/backups")
    assert fake.connects == []  # nothing set up: no copy
    julia.put("/api/admin/backups/nas", json=SMB)
    made = julia.post("/api/admin/backups")
    assert made.status_code == 201
    name = made.json()["name"]
    assert fake.files[name] == backup.path_of(name).read_bytes()
    last = _overview(julia)["nas_last"]
    assert last["ok"] is True and last["name"] == name and last["running"] is False and last["at"]


def test_nightly_backup_copies_too(julia, fake, monkeypatch):
    julia.put("/api/admin/backups/nas", json=SMB)
    monkeypatch.setattr(backup, "_now", lambda: datetime(2026, 10, 21, 3, 0))
    backup.run_if_due()
    assert list(fake.files) == ["officehub-20261021-030000.tar.gz"]


def test_retention_trims_old_copies(julia, fake, monkeypatch):
    julia.put("/api/admin/backups/settings", json={"enabled": True, "hour": 2, "keep": 3})
    julia.put("/api/admin/backups/nas", json={**SMB, "keep": 2})
    fake.files["notes.txt"] = b"not ours"
    for second in range(4):
        monkeypatch.setattr(backup, "_now", lambda s=second: datetime(2026, 10, 21, 3, 0, s))
        julia.post("/api/admin/backups")
    assert sorted(fake.files) == ["notes.txt", "officehub-20261021-030002-manual.tar.gz", "officehub-20261021-030003-manual.tar.gz"]
    assert _overview(julia)["nas_last"]["count"] == 2

    # keep 0 = as many as in the backup folder
    julia.put("/api/admin/backups/nas", json={**SMB, "keep": 0})
    monkeypatch.setattr(backup, "_now", lambda: datetime(2026, 10, 21, 3, 0, 9))
    julia.post("/api/admin/backups")
    assert len([n for n in fake.files if n.endswith(".tar.gz")]) == 3


def test_failure_recorded_local_backup_stays(julia, fake):
    julia.put("/api/admin/backups/nas", json=SMB)
    fake.fail = nas.NasError("nas_unreachable")
    made = julia.post("/api/admin/backups")
    assert made.status_code == 201
    data = _overview(julia)
    assert data["last"]["ok"] is True and data["items"][0]["name"] == made.json()["name"]
    assert data["nas_last"].items() >= {"ok": False, "code": "nas_unreachable", "running": False}.items()
    assert data["nas_last"]["error"]

    fake.fail = RuntimeError("disk on fire")
    julia.post("/api/admin/backups")
    last = _overview(julia)["nas_last"]
    assert last["code"] == "nas_failed" and "disk on fire" in last["error"]

    fake.fail = None
    julia.post("/api/admin/backups")
    assert _overview(julia)["nas_last"]["ok"] is True


def test_sftp_host_key_remembered(julia, fake):
    sftp = {"kind": "sftp", "host": "nas.local", "port": 22, "folder": "/volume1/backup", "user": "backup", "password": "pw"}
    julia.put("/api/admin/backups/nas", json=sftp)
    fake.host_key = "ssh-ed25519 AAAAkey"
    assert julia.post("/api/admin/backups/nas/test", json={**sftp, "password": ""}).status_code == 204
    with SessionLocal() as db:
        assert nas.options(db)["host_key"] == "ssh-ed25519 AAAAkey"
    assert "AAAAkey" not in julia.get("/api/admin/backups").text
    julia.post("/api/admin/backups/nas/test", json=sftp)
    assert fake.connects[-1]["host_key"] == "ssh-ed25519 AAAAkey"  # checked on the next connection
    # Another NAS: the old key no longer applies
    julia.put("/api/admin/backups/nas", json={**sftp, "host": "nas2.local"})
    with SessionLocal() as db:
        assert nas.options(db)["host_key"] == ""


def test_plain_language_reasons():
    import paramiko
    from smbprotocol.exceptions import SMBOSError
    from smbprotocol.header import NtStatus

    assert nas._smb_error(SMBOSError(NtStatus.STATUS_LOGON_FAILURE, "x")).code == "nas_auth"
    assert nas._smb_error(SMBOSError(NtStatus.STATUS_BAD_NETWORK_NAME, "x")).code == "nas_not_found"
    assert nas._smb_error(SMBOSError(NtStatus.STATUS_ACCESS_DENIED, "x")).code == "nas_denied"
    assert nas._smb_error(SMBOSError(NtStatus.STATUS_DISK_FULL, "x")).code == "nas_full"
    assert nas._smb_error(ValueError("Failed to connect to 'nas:445': refused")).code == "nas_unreachable"
    assert nas._sftp_error(paramiko.AuthenticationException()).code == "nas_auth"
    assert nas._sftp_error(FileNotFoundError(2, "No such file")).code == "nas_not_found"
    assert nas._sftp_error(PermissionError(13, "Permission denied")).code == "nas_denied"
    assert nas._sftp_error(ConnectionRefusedError()).code == "nas_unreachable"


@pytest.mark.parametrize("opts", [
    {**nas.DEFAULTS, "kind": "smb", "path": "//127.0.0.1:1/backup"},
    {**nas.DEFAULTS, "kind": "sftp", "host": "127.0.0.1", "port": 1, "user": "x"},
])
def test_closed_port_is_unreachable(opts):
    """The real transports on this machine's closed port (no outside network)."""
    with pytest.raises(nas.NasError) as e, nas.open_transport(opts):
        pass
    assert e.value.code == "nas_unreachable"
