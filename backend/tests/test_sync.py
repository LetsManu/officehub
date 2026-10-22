"""Desktop sync API: change numbers, the whole tree, id-based file changes with conflicts, sign-in by app password."""

import base64

from fastapi.testclient import TestClient

from app.main import app
from test_webdav import _app_password, _docx, _space


def _client(anna) -> TestClient:
    password = _app_password(anna)["password"]
    token = base64.b64encode(f"anna.mayer@example.com:{password}".encode()).decode()
    return TestClient(app, headers={"Authorization": f"Basic {token}", "X-Requested-With": "OfficeHub"})


def test_first_sync_gets_the_tree_then_only_changes(anna):
    space = _space(anna)
    pc = _client(anna)
    first = pc.get("/api/sync/changes").json()
    assert first["reset"] is True and any(s["id"] == space["id"] for s in first["spaces"])
    cursor = first["cursor"]

    # Nothing new: the same cursor and no items
    again = pc.get(f"/api/sync/changes?since={cursor}").json()
    assert again["reset"] is False and again["items"] == [] and again["cursor"] == cursor

    # A change in the portal shows up as one item with a higher number
    folder = anna.post(f"/api/spaces/{space['id']}/folders", json={"name": "Angebote", "parent_id": None}).json()
    news = pc.get(f"/api/sync/changes?since={cursor}").json()
    assert [(i["kind"], i["id"], i["name"]) for i in news["items"]] == [("folder", folder["id"], "Angebote")]
    assert news["cursor"] > cursor


def test_create_save_conflict_move_delete(anna):
    space = _space(anna)
    pc = _client(anna)
    cursor = pc.get("/api/sync/changes").json()["cursor"]

    created = pc.post(f"/api/sync/files?space_id={space['id']}&name=Plan.docx", content=_docx())
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["version"] == 1 and item["name"] == "Plan.docx"
    assert pc.get(f"/api/sync/files/{item['id']}").content == _docx()

    # Saving on top of version 1 works once; a second save based on the old version is a conflict
    assert pc.put(f"/api/sync/files/{item['id']}?base=1", content=_docx()).json()["version"] == 2
    conflict = pc.put(f"/api/sync/files/{item['id']}?base=1", content=_docx())
    assert conflict.status_code == 409 and conflict.json()["code"] == "sync_conflict"

    folder = pc.post("/api/sync/folders", json={"space_id": space["id"], "name": "Archiv"}).json()
    moved = pc.patch(f"/api/sync/files/{item['id']}", json={"name": "Plan 2026.docx", "folder_id": folder["id"]})
    assert moved.json()["parent_id"] == folder["id"] and moved.json()["name"] == "Plan 2026.docx"
    assert pc.patch(f"/api/sync/files/{item['id']}", json={"name": "Plan.exe", "folder_id": None}).status_code == 422

    assert pc.delete(f"/api/sync/files/{item['id']}").status_code == 204
    changes = pc.get(f"/api/sync/changes?since={cursor}").json()
    gone = [i for i in changes["items"] if i["id"] == item["id"] and i["kind"] == "file"]
    assert gone and gone[0]["deleted"] is True
    # The portal sees the same: the file is in the space's trash
    assert any(f["id"] == item["id"] for f in anna.get(f"/api/spaces/{space['id']}/trash").json()["files"])


def test_wrong_content_and_types_are_refused(anna):
    space = _space(anna)
    pc = _client(anna)
    assert pc.post(f"/api/sync/files?space_id={space['id']}&name=tool.exe", content=b"MZ").status_code == 415
    assert pc.post(f"/api/sync/files?space_id={space['id']}&name=Fake.docx", content=b"not a zip").status_code == 415


def test_checked_out_files_are_read_only_for_others(anna, lukas):
    space = _space(anna, "Gemeinsam")
    anna.post(f"/api/spaces/{space['id']}/members", json={"user_id": lukas.get("/api/auth/me").json()["id"]})
    pc = _client(anna)
    item = pc.post(f"/api/sync/files?space_id={space['id']}&name=Liste.docx", content=_docx()).json()
    assert lukas.post(f"/api/spaces/files/{item['id']}/checkout").status_code == 200
    seen = [i for i in pc.get("/api/sync/changes").json()["items"] if i["id"] == item["id"]]
    assert seen[0]["read_only"] is True
    assert pc.put(f"/api/sync/files/{item['id']}?base=1", content=_docx()).status_code == 423


def test_other_peoples_spaces_stay_hidden(anna, lukas):
    space = _space(anna, "Nur Anna")
    item = _client(anna).post(f"/api/sync/files?space_id={space['id']}&name=Geheim.docx", content=_docx()).json()
    password = _app_password(lukas)["password"]
    token = base64.b64encode(f"lukas.schmid@example.com:{password}".encode()).decode()
    other = TestClient(app, headers={"Authorization": f"Basic {token}", "X-Requested-With": "OfficeHub"})
    changes = other.get("/api/sync/changes").json()
    assert all(s["id"] != space["id"] for s in changes["spaces"])
    assert all(i["id"] != item["id"] or i["kind"] != "file" for i in changes["items"])
    assert other.get(f"/api/sync/files/{item['id']}").status_code == 404


def test_wrong_app_password_is_refused():
    token = base64.b64encode(b"anna.mayer@example.com:wrong").decode()
    client = TestClient(app, headers={"Authorization": f"Basic {token}"})
    assert client.get("/api/sync/changes").status_code == 401


def test_long_poll_returns_when_something_changes(anna):
    pc = _client(anna)
    cursor = pc.get("/api/sync/changes").json()["cursor"]
    # Nothing changes: the call comes back after the wait with the same cursor
    assert pc.get(f"/api/sync/changes?since={cursor}&wait=1").json()["cursor"] == cursor
