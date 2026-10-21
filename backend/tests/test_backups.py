"""Automatic backups: archive of database and files, keep the newest, restore while the portal runs."""

import io
import tarfile
from datetime import datetime

from app.services import backup
from tests.conftest import make_client


def _space_with_file(client, name="Backup-Test"):
    space = client.post("/api/spaces", json={"name": name, "description": "", "color": "blue", "member_ids": []}).json()
    item = client.post(f"/api/spaces/{space['id']}/files", files={"file": ("Notiz.txt", b"Version eins")}).json()
    return space, item


def test_only_admins_see_backups(anna, julia):
    assert anna.get("/api/admin/backups").status_code == 403
    data = julia.get("/api/admin/backups").json()
    assert data["available"] is True and data["options"] == {"enabled": True, "hour": 2, "keep": 14}
    assert julia.put("/api/admin/backups/settings", json={"enabled": True, "hour": 24, "keep": 3}).status_code == 422
    saved = julia.put("/api/admin/backups/settings", json={"enabled": False, "hour": 3, "keep": 3}).json()
    assert saved["options"] == {"enabled": False, "hour": 3, "keep": 3}
    assert julia.get("/api/admin/backups/../../etc/passwd/download").status_code == 404
    assert julia.get("/api/admin/backups/officehub-20260101-000000.tar.gz/download").status_code == 404


def test_back_up_and_restore(julia):
    space, item = _space_with_file(julia)
    made = julia.post("/api/admin/backups")
    assert made.status_code == 201, made.text
    name = made.json()["name"]
    assert name.endswith("-manual.tar.gz")
    overview = julia.get("/api/admin/backups").json()
    assert overview["last"]["ok"] is True and overview["last"]["name"] == name
    with tarfile.open(backup.path_of(name)) as tar:
        names = tar.getnames()
    assert "officehub.db" in names and "manifest.json" in names and any(n.startswith("uploads/") for n in names)
    assert julia.get(f"/api/admin/backups/{name}/download").status_code == 200

    # things change after the backup …
    julia.post(f"/api/spaces/{space['id']}/files", files={"file": ("Notiz.txt", b"Version zwei")})
    later = julia.post("/api/spaces", json={"name": "Nach dem Backup", "description": "", "color": "blue", "member_ids": []}).json()
    assert julia.get(f"/api/spaces/files/{item['id']}").json()["version"] == 2

    # … and are undone by restoring; the state before is kept as an archive of its own
    restored = julia.post(f"/api/admin/backups/{name}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["name"].endswith("-restore.tar.gz")
    julia = make_client("julia.weber@example.com")  # sign-ins newer than the backup are gone
    assert julia.get(f"/api/spaces/files/{item['id']}").json()["version"] == 1
    assert julia.get(f"/api/spaces/files/{item['id']}/download").content == b"Version eins"
    assert julia.get(f"/api/spaces/{later['id']}").status_code == 404
    assert any(e["action"] == "backup_restored" for e in julia.get("/api/admin/audit").json()["items"])
    assert {b["name"] for b in julia.get("/api/admin/backups").json()["items"]} >= {name, restored.json()["name"]}


def test_keeps_newest_and_rejects_foreign_archives(julia, monkeypatch):
    julia.put("/api/admin/backups/settings", json={"enabled": True, "hour": 2, "keep": 2})
    for b in backup.list_backups():
        (backup.folder() / b["name"]).unlink()
    for second in range(4):
        monkeypatch.setattr(backup, "_now", lambda s=second: datetime(2026, 10, 21, 3, 0, s))
        julia.post("/api/admin/backups")
    assert [b["name"] for b in backup.list_backups()] == ["officehub-20261021-030003-manual.tar.gz", "officehub-20261021-030002-manual.tar.gz"]

    evil = backup.folder() / "officehub-20261021-040000.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    assert julia.post(f"/api/admin/backups/{evil.name}/restore").json()["code"] == "backup_invalid"
    assert not (backup.folder().parent / "escape.txt").exists()


def test_nightly_once_a_day_after_the_hour(julia, monkeypatch):
    julia.put("/api/admin/backups/settings", json={"enabled": True, "hour": 2, "keep": 14})
    made = []
    monkeypatch.setattr(backup, "create", lambda reason="": made.append(reason) or {"name": "x", "size": 1})
    monkeypatch.setattr(backup, "_now", lambda: datetime(2026, 10, 21, 1, 30))
    backup.run_if_due()
    assert made == []  # before 2:00
    monkeypatch.setattr(backup, "_now", lambda: datetime(2026, 10, 21, 2, 5))
    backup.run_if_due()
    backup.run_if_due()
    assert made == [""]  # once that day
    monkeypatch.setattr(backup, "_now", lambda: datetime(2026, 10, 22, 9, 0))
    backup.run_if_due()
    assert made == ["", ""]  # the next day (also when the server was off at 2:00)
    julia.put("/api/admin/backups/settings", json={"enabled": False, "hour": 2, "keep": 14})
    monkeypatch.setattr(backup, "_now", lambda: datetime(2026, 10, 23, 9, 0))
    backup.run_if_due()
    assert made == ["", ""]
