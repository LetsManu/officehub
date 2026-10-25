"""Sync status per computer: reports from the Windows app, contact from every sync call, own devices, the IT list."""

import base64
from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import SyncDevice
from app.services import sync_status
from conftest import make_client
from test_webdav import _app_password

APP_AGENT = "OfficeHubApp/1.4.0 (windows; sync)"


def _pc(client, email: str) -> tuple[TestClient, int]:
    created = _app_password(client)
    token = base64.b64encode(f"{email}:{created['password']}".encode()).decode()
    pc = TestClient(app, headers={"Authorization": f"Basic {token}", "X-Requested-With": "OfficeHub",
                                  "User-Agent": APP_AGENT})
    return pc, created["id"]


def _my_device(client, password_id: int):
    rows = client.get("/api/profile/app-passwords").json()
    return next(r for r in rows if r["id"] == password_id)["device"]


def test_a_sync_call_counts_as_contact(anna):
    pc, password_id = _pc(anna, "anna.mayer@example.com")
    assert _my_device(anna, password_id) is None  # never used for syncing yet

    assert pc.get("/api/sync/changes").status_code == 200
    device = _my_device(anna, password_id)
    assert device["last_contact_at"] and device["app_version"] == "1.4.0"
    # An older app that sends no reports: its contact stands for the last sync
    assert device["reports"] is False and device["status"] == "ok"

    # Not written again within a minute; after that it is
    with SessionLocal() as db:
        row = db.query(SyncDevice).one()
        old = row.last_contact_at - timedelta(minutes=5)
        row.last_contact_at = old
        db.commit()
    pc.get("/api/sync/changes")
    with SessionLocal() as db:
        assert db.query(SyncDevice).one().last_contact_at > old


def test_report_is_stored_and_shown_to_the_person(anna):
    pc, password_id = _pc(anna, "anna.mayer@example.com")
    ok = pc.post("/api/sync/report", json={"device_name": "ANNA-LAPTOP", "ok": True, "failed": [], "pending_uploads": 0})
    assert ok.status_code == 204, ok.text
    device = _my_device(anna, password_id)
    assert device["device_name"] == "ANNA-LAPTOP" and device["status"] == "ok" and device["last_sync_at"]
    assert device["reports"] is True

    failed = [{"path": f"Marketing/Datei {i}.docx", "reason": "too_large"} for i in range(30)]
    pc.post("/api/sync/report", json={"device_name": "ANNA-LAPTOP", "ok": True, "failed": failed, "pending_uploads": 2})
    device = _my_device(anna, password_id)
    assert device["status"] == "problem" and device["failed_count"] == 30 and device["pending_uploads"] == 2
    assert len(device["failed"]) == sync_status.MAX_FAILED and device["last_error"] == "too_large"

    # Fixed again: the problems go away
    pc.post("/api/sync/report", json={"device_name": "ANNA-LAPTOP", "ok": True})
    device = _my_device(anna, password_id)
    assert device["status"] == "ok" and device["failed"] == [] and device["last_error"] == ""


def test_a_round_that_did_not_go_through_and_old_syncs_need_attention(anna):
    pc, password_id = _pc(anna, "anna.mayer@example.com")
    pc.post("/api/sync/report", json={"device_name": "PC", "ok": False, "error": "offline"})
    device = _my_device(anna, password_id)
    assert device["last_sync_at"] is None and device["status"] == "problem" and device["last_error"] == "offline"

    pc.post("/api/sync/report", json={"device_name": "PC", "ok": True})
    with SessionLocal() as db:
        row = db.query(SyncDevice).one()
        row.last_sync_at -= timedelta(hours=25)
        db.commit()
        assert sync_status.status(row) == "problem"
    assert sync_status.status(None) == "never"


def test_only_the_app_reports_and_only_own_devices_are_shown(anna, lukas):
    # The portal session is no device
    assert anna.post("/api/sync/report", json={"ok": True}).status_code == 400
    assert TestClient(app, headers={"X-Requested-With": "OfficeHub"}).post("/api/sync/report", json={"ok": True}).status_code == 401

    pc, _ = _pc(anna, "anna.mayer@example.com")
    pc.post("/api/sync/report", json={"device_name": "ANNA-PC", "ok": True})
    lukas_pc, lukas_password = _pc(lukas, "lukas.schmid@example.com")
    lukas_pc.post("/api/sync/report", json={"device_name": "LUKAS-PC", "ok": True})

    mine = [r["device"]["device_name"] for r in anna.get("/api/profile/app-passwords").json() if r["device"]]
    assert mine == ["ANNA-PC"]
    assert _my_device(lukas, lukas_password)["device_name"] == "LUKAS-PC"


def test_the_list_of_all_devices_is_for_the_service_desk(anna, lukas, julia):
    pc, _ = _pc(anna, "anna.mayer@example.com")
    pc.post("/api/sync/report", json={"device_name": "ANNA-PC", "ok": True,
                                      "failed": [{"path": "a.exe", "reason": "not_supported"}]})
    assert anna.get("/api/sync/devices").status_code == 403
    assert lukas.get("/api/sync/devices").status_code == 403

    max_ = make_client("max.gruber@example.com")  # service desk
    rows = max_.get("/api/sync/devices").json()
    assert [(r["full_name"], r["device_name"], r["status"], r["failed_count"]) for r in rows] == [
        ("Anna Mayer", "ANNA-PC", "problem", 1)]
    assert julia.get("/api/sync/devices").status_code == 200  # admin


def test_removing_the_app_password_removes_the_device(anna):
    pc, password_id = _pc(anna, "anna.mayer@example.com")
    pc.post("/api/sync/report", json={"device_name": "ANNA-PC", "ok": True})
    assert anna.delete(f"/api/profile/app-passwords/{password_id}").status_code == 204
    with SessionLocal() as db:
        assert db.query(SyncDevice).count() == 0
    assert pc.post("/api/sync/report", json={"ok": True}).status_code == 401
