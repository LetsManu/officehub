"""Spaces as a network drive (WebDAV) for desktop programs like WordCraft and DeckCraft, check-out and app passwords."""

import base64
import io
import zipfile
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.main import app




def _docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def _dav(login, password):
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    return TestClient(app, headers={"Authorization": f"Basic {token}"})


def _space(anna, name="Laufwerk-Test"):
    space = anna.post("/api/spaces", json={"name": name, "description": "", "color": "blue", "member_ids": []})
    assert space.status_code == 201, space.text
    return space.json()


def _app_password(client):
    created = client.post("/api/profile/app-passwords", json={"name": "WordCraft am Laptop"})
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["drive_url"].endswith("/dav/") and len(data["password"]) > 20
    return data


def test_app_passwords_and_sign_in(anna):
    data = _app_password(anna)
    assert [p["name"] for p in anna.get("/api/profile/app-passwords").json()] == ["WordCraft am Laptop"]
    assert "password" not in anna.get("/api/profile/app-passwords").json()[0]

    assert TestClient(app).request("PROPFIND", "/dav/").status_code == 401
    assert _dav(data["login"], "wrong").request("PROPFIND", "/dav/").status_code == 401
    assert _dav(data["login"], "demo1234").request("PROPFIND", "/dav/").status_code == 401  # not the real password
    ok = _dav(data["login"], data["password"]).request("PROPFIND", "/dav/", headers={"Depth": "1"})
    assert ok.status_code == 207 and "<D:multistatus" in ok.text

    anna.delete(f"/api/profile/app-passwords/{data['id']}")
    assert _dav(data["login"], data["password"]).request("PROPFIND", "/dav/").status_code == 401


def test_drive_files_versions_folders(anna, lukas):
    space = _space(anna)
    data = _app_password(anna)
    dav = _dav(data["login"], data["password"])
    root = dav.request("PROPFIND", "/dav/", headers={"Depth": "1"}).text
    assert f"/dav/{quote('Laufwerk-Test')}/" in root

    base = f"/dav/{quote('Laufwerk-Test')}"
    assert dav.request("MKCOL", f"{base}/Berichte").status_code == 201
    assert dav.put(f"{base}/Berichte/Plan.docx", content=_docx()).status_code == 201
    assert dav.put(f"{base}/Berichte/Plan.docx", content=_docx()).status_code == 204  # saved again: version 2
    assert dav.put(f"{base}/Berichte/evil.exe", content=b"MZ").status_code == 415
    assert dav.put(f"{base}/Berichte/fake.docx", content=b"not a zip").status_code == 415
    assert dav.put(f"{base}/Berichte/.DS_Store", content=b"x").status_code == 201  # ignored, not stored

    listing = dav.request("PROPFIND", f"{base}/Berichte/", headers={"Depth": "1"}).text
    assert "Plan.docx" in listing and ".DS_Store" not in listing
    assert dav.get(f"{base}/Berichte/Plan.docx").content == _docx()

    files = anna.get(f"/api/spaces/{space['id']}/files").json()
    folder = files["folders"][0]
    plan = anna.get(f"/api/spaces/{space['id']}/files?folder_id={folder['id']}").json()["files"][0]
    assert plan["name"] == "Plan.docx" and plan["version"] == 2

    # rename by MOVE, "save via temporary file" keeps the history, delete goes to the trash
    assert dav.request("MOVE", f"{base}/Berichte/Plan.docx",
                       headers={"Destination": f"http://testserver{base}/Berichte/Plan%202027.docx"}).status_code == 201
    assert dav.put(f"{base}/Berichte/neu.docx", content=_docx()).status_code == 201
    assert dav.request("MOVE", f"{base}/Berichte/neu.docx", headers={
        "Destination": f"http://testserver{base}/Berichte/Plan%202027.docx", "Overwrite": "T"}).status_code == 204
    detail = anna.get(f"/api/spaces/files/{plan['id']}").json()
    assert detail["name"] == "Plan 2027.docx" and detail["version"] == 3
    assert detail["drive_path"] == f"{base}/Berichte/Plan%202027.docx"
    assert dav.delete(f"{base}/Berichte/Plan%202027.docx").status_code == 204
    assert anna.get(f"/api/spaces/{space['id']}/trash").json()["files"][0]["name"] == "Plan 2027.docx"

    # someone who is not in the space does not see it
    other = _app_password(lukas)
    assert "Laufwerk-Test" not in _dav(other["login"], other["password"]).request("PROPFIND", "/dav/").text


def test_check_out_and_locks(anna, lukas):
    space = _space(anna, "Gemeinsam")
    anna.post(f"/api/spaces/{space['id']}/members", json={"user_id": lukas.get("/api/auth/me").json()["id"], "role": "member"})
    a = _app_password(anna)
    b = _app_password(lukas)
    dav_a, dav_b = _dav(a["login"], a["password"]), _dav(b["login"], b["password"])
    base = "/dav/Gemeinsam"
    assert dav_a.put(f"{base}/Angebot.docx", content=_docx()).status_code == 201
    item = anna.get(f"/api/spaces/{space['id']}/files").json()["files"][0]

    # Lukas checks the file out: Anna can read it but not save, rename or delete it
    out = lukas.post(f"/api/spaces/files/{item['id']}/checkout").json()
    assert out["checked_out_by"] == "Lukas Schmid"
    assert dav_a.put(f"{base}/Angebot.docx", content=_docx()).status_code == 423
    assert dav_a.delete(f"{base}/Angebot.docx").status_code == 423
    assert anna.delete(f"/api/spaces/files/{item['id']}").json()["code"] == "file_checked_out"
    assert dav_b.put(f"{base}/Angebot.docx", content=_docx()).status_code == 204
    # the manager of the space (Anna created it) can check it in for him
    assert anna.post(f"/api/spaces/files/{item['id']}/checkin").json()["checked_out_by"] is None

    # WebDAV lock: while Lukas's program holds it, Anna cannot save
    lock = dav_b.request("LOCK", f"{base}/Angebot.docx", content=b"<D:lockinfo xmlns:D='DAV:'/>")
    assert lock.status_code == 200 and "opaquelocktoken:" in lock.headers["lock-token"]
    assert dav_a.put(f"{base}/Angebot.docx", content=_docx()).status_code == 423
    assert dav_b.put(f"{base}/Angebot.docx", content=_docx()).status_code == 204
    assert dav_b.request("UNLOCK", f"{base}/Angebot.docx", headers={"Lock-Token": lock.headers["lock-token"]}).status_code == 204
    assert dav_a.put(f"{base}/Angebot.docx", content=_docx()).status_code == 204

    # Office programs lock a new name before writing it
    assert dav_a.request("LOCK", f"{base}/Neu.docx", content=b"").status_code == 201
    assert dav_a.put(f"{base}/Neu.docx", content=_docx()).status_code == 204
    assert dav_a.request("PROPPATCH", f"{base}/Neu.docx", content=(
        b'<?xml version="1.0"?><D:propertyupdate xmlns:D="DAV:" xmlns:Z="urn:schemas-microsoft-com:"><D:set><D:prop>'
        b"<Z:Win32LastModifiedTime>x</Z:Win32LastModifiedTime></D:prop></D:set></D:propertyupdate>")).status_code == 207


def test_open_in_wordcraft_and_save_back(anna, lukas, monkeypatch):
    import dataclasses

    from app import config
    from app.services import craft

    monkeypatch.setattr(craft, "settings", dataclasses.replace(config.settings, craft_internal_url="http://craft:8080"))
    monkeypatch.setattr(craft, "reachable", lambda url: True)  # the container runs
    assert anna.get("/api/craft/config").json()["apps"] == ["wordcraft", "deckcraft"]

    space = _space(anna, "Texte")
    upload = anna.post(f"/api/spaces/{space['id']}/files", files={"file": ("Brief.docx", _docx())})
    item = upload.json()
    opened = anna.post(f"/api/craft/open/{item['id']}").json()
    assert opened["app"] == "wordcraft" and opened["can_write"] is True
    assert opened["url"].startswith("/wordcraft/?src=%2Fapi%2Fcraft%2Ffiles%2F")

    from urllib.parse import parse_qs, urlparse
    query = parse_qs(urlparse(opened["url"]).query)
    plain = TestClient(app, headers={"X-Requested-With": "OfficeHub"})  # the app has no session, only the ticket
    assert plain.get(query["src"][0]).content == _docx()
    assert plain.put(query["save"][0], content=b"not a docx").status_code == 422
    assert plain.put(query["save"][0], content=_docx()).status_code == 204
    assert anna.get(f"/api/spaces/files/{item['id']}").json()["version"] == 2
    assert plain.put(query["save"][0].replace("token=", "token=x"), content=_docx()).status_code == 401

    # checked out by someone else: the ticket cannot save
    anna.post(f"/api/spaces/{space['id']}/members", json={"user_id": lukas.get("/api/auth/me").json()["id"], "role": "member"})
    lukas.post(f"/api/spaces/files/{item['id']}/checkout")
    assert plain.put(query["save"][0], content=_docx()).status_code == 423
    assert anna.post(f"/api/craft/open/{item['id']}").json()["can_write"] is False

    # a .deckcraft presentation can be stored and opens in DeckCraft; other types have no program
    deck = anna.post(f"/api/spaces/{space['id']}/files", files={"file": ("Pitch.deckcraft", _docx())}).json()
    assert anna.post(f"/api/craft/open/{deck['id']}").json()["app"] == "deckcraft"
    note = anna.post(f"/api/spaces/{space['id']}/files", files={"file": ("a.txt", b"hallo")}).json()
    assert anna.post(f"/api/craft/open/{note['id']}").json()["code"] == "craft_unavailable"


def test_word_and_powerpoint_open_in_craft_by_default(anna, monkeypatch):
    import dataclasses

    from app import config
    from app.services import craft

    from conftest import make_client

    assert anna.get("/api/office/config").json()["prefer_craft"] is False  # not running
    monkeypatch.setattr(craft, "settings", dataclasses.replace(config.settings, craft_internal_url="http://craft:8080"))
    monkeypatch.setattr(craft, "reachable", lambda url: True)
    data = anna.get("/api/office/config").json()
    assert data["craft"] == ["wordcraft", "deckcraft"] and data["prefer_craft"] is True

    # HR can choose the office editor again (and back)
    hr = make_client("julia.weber@example.com")
    assert anna.put("/api/office/config", json={"prefer_craft": False}).status_code == 403
    assert hr.put("/api/office/config", json={"prefer_craft": False}).json()["prefer_craft"] is False
    assert anna.get("/api/office/config").json()["prefer_craft"] is False
    assert hr.put("/api/office/config", json={"prefer_craft": True}).json()["prefer_craft"] is True
