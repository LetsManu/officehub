"""Administration → System: status of the stack, meeting check and notices about an outdated stack file."""

from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.services import craft, system
from app.services.settings import set_setting


def test_only_admins_see_the_system_page(anna, lukas, julia):
    assert anna.get("/api/admin/system").status_code == 403
    assert lukas.get("/api/admin/system").status_code == 403
    assert anna.get("/api/admin/system/notices").status_code == 403
    data = julia.get("/api/admin/system").json()
    assert data["version"]
    assert set(data) >= {"craft", "onlyoffice", "jitsi", "relay", "disk", "database_size", "backup", "network",
                         "notices", "ice_servers"}
    assert data["disk"]["free"] > 0 and data["disk"]["state"] in {"ok", "warn", "bad"}
    assert data["database_size"] > 0
    assert data["backup"]["available"] is True and data["backup"]["at"] is None
    # Outside the stack (no shared folder, Collabora not there) nothing needs attention
    assert data["notices"] == []
    assert julia.get("/api/admin/system/notices").json() == {"notices": []}


def test_old_collabora_container_is_noticed(julia, monkeypatch):
    monkeypatch.setattr(system, "reachable", lambda url: url == system.COLLABORA_URL)
    assert julia.get("/api/admin/system/notices").json()["notices"] == ["collabora"]
    assert "collabora" in julia.get("/api/admin/system").json()["notices"]


def test_missing_parts_of_the_stack_are_noticed(julia, monkeypatch, tmp_path):
    monkeypatch.setenv("SHARED_DIR", str(tmp_path))
    monkeypatch.setattr(system, "reachable", lambda url: False)
    monkeypatch.setattr(craft, "available", lambda: [])
    (tmp_path / "turn_secret").write_text("secret")
    monkeypatch.setattr(system, "public_address", lambda: {"address": None, "source": None})
    notices = julia.get("/api/admin/system/notices").json()["notices"]
    assert notices == ["hostip", "craft", "relay"]

    # The current stack file: hostip ran, craft runs, the address is known
    (tmp_path / "host_ip").write_text("192.168.1.20")
    monkeypatch.setattr(craft, "available", lambda: ["wordcraft", "deckcraft", "gridcraft"])
    monkeypatch.setattr(system, "public_address", lambda: {"address": "203.0.113.7", "source": "setting"})
    assert julia.get("/api/admin/system/notices").json()["notices"] == []
    data = julia.get("/api/admin/system").json()
    assert data["network"]["office"] == "192.168.1.20" and data["relay"]["secret"] is True
    assert data["craft"]["running"] is True


def test_public_address_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("SHARED_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_IP", "203.0.113.9")
    assert system.public_address() == {"address": "203.0.113.9", "source": "setting"}
    monkeypatch.delenv("PUBLIC_IP")
    monkeypatch.delenv("JITSI_PUBLIC_IP", raising=False)
    monkeypatch.setattr(system.address, "learned", lambda: "198.51.100.4")
    assert system.public_address() == {"address": "198.51.100.4", "source": "proxy"}
    monkeypatch.setattr(system.address, "learned", lambda: None)
    monkeypatch.setattr(system, "_resolve", lambda host: None)
    (tmp_path / "public_ip").write_text("198.51.100.5")
    assert system.public_address() == {"address": "198.51.100.5", "source": "noted"}


def test_backup_state(julia):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        assert system.last_backup(db)["state"] == "warn"  # none yet
        set_setting(db, "backup.status", {"at": now.isoformat(), "ok": True})
        assert system.last_backup(db)["state"] == "ok"
        set_setting(db, "backup.status", {"at": (now - timedelta(days=3)).isoformat(), "ok": True})
        assert system.last_backup(db)["state"] == "warn"
        set_setting(db, "backup.status", {"at": now.isoformat(), "ok": False, "error": "disk full"})
        assert system.last_backup(db)["state"] == "bad"
