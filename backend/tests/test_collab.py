"""Editing together in WordCraft and DeckCraft: one live session per file, OfficeHub passes the changes between the people."""

import base64
import dataclasses
import sys
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import collab
from tests.test_webdav import _docx, _space


@pytest.fixture
def deck_together(anna, lukas, monkeypatch):
    from app import config
    from app.services import craft

    monkeypatch.setattr(craft, "settings", dataclasses.replace(config.settings, craft_internal_url="http://craft:8080"))
    monkeypatch.setattr(craft, "reachable", lambda url: True)
    monkeypatch.setattr(craft, "together", lambda app_name: app_name == "deckcraft")
    collab.rooms.clear()
    space = _space(anna, "Gemeinsame Folien")
    anna.post(f"/api/spaces/{space['id']}/members", json={"user_id": lukas.get("/api/auth/me").json()["id"], "role": "member"})
    item = anna.post(f"/api/spaces/{space['id']}/files", files={"file": ("Pitch.pptx", _docx())}).json()
    return space, item


def _collab_url(opened: dict) -> str:
    return parse_qs(urlparse(opened["url"]).query)["collab"][0]


def _call(url: str, action: str, body: dict | None = None):
    base, query = url.split("?", 1)
    client = TestClient(app, headers={"X-Requested-With": "OfficeHub"})  # the app itself, with the ticket only
    return client.post(f"{base}/{action}?{query}", json=body or {})


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_everyone_edits_in_one_live_session(anna, lukas, deck_together):
    space, item = deck_together
    first = anna.post(f"/api/craft/open/{item['id']}").json()
    second = lukas.post(f"/api/craft/open/{item['id']}").json()
    assert first["can_write"] and second["can_write"], "nobody is read-only"
    assert first["lock"] == second["lock"], "one shared session"
    a_url, l_url = _collab_url(first), _collab_url(second)

    a = _call(a_url, "hello").json()
    assert a["seed"] is True and a["log"] == [] and a["name"] == "Anna Mayer"
    l = _call(l_url, "hello").json()
    assert l["seed"] is False and l["slot"] != a["slot"]
    assert [p["name"] for p in l["peers"]] == ["Anna Mayer"]

    # Anna seeds, then changes something; Lukas receives both, in order
    assert _call(a_url, "update", {"peer_id": a["peer_id"], "data": b64(b"seed")}).status_code == 204
    assert _call(a_url, "update", {"peer_id": a["peer_id"], "data": b64(b"edit")}).status_code == 204
    messages = _call(l_url, "poll", {"peer_id": l["peer_id"], "after": 0}).json()["messages"]
    updates = [m["data"] for m in messages if m["type"] == "update"]
    assert updates == [b64(b"seed"), b64(b"edit")]
    assert any(m["type"] == "join" for m in _call(a_url, "poll", {"peer_id": a["peer_id"], "after": 0}).json()["messages"])

    # where Lukas is goes to Anna, but is not kept
    _call(l_url, "presence", {"peer_id": l["peer_id"], "state": {"slide": 3}})
    seen = _call(a_url, "poll", {"peer_id": a["peer_id"], "after": 1}).json()["messages"]
    assert seen[-1]["type"] == "presence" and seen[-1]["data"] == {"slide": 3}

    # someone joining later gets everything so far; after compacting, one update instead of many
    late = _call(l_url, "hello").json()
    assert late["log"] == [b64(b"seed"), b64(b"edit")]
    _call(a_url, "compact", {"peer_id": a["peer_id"], "data": b64(b"whole"), "upto": 2})
    assert _call(l_url, "hello").json()["log"] == [b64(b"whole")]

    # the office editor waits while the session runs; saving from the session works
    monkeypatch_office = sys.modules["app.routers.office"]
    original = monkeypatch_office.available
    monkeypatch_office.available = lambda: ["onlyoffice"]
    try:
        office = lukas.post(f"/api/office/open/{item['id']}", json={"engine": "onlyoffice", "origin": "http://testserver"}).json()
        assert office["can_write"] is False
    finally:
        monkeypatch_office.available = original
    save = parse_qs(urlparse(second["url"]).query)["save"][0]
    plain = TestClient(app, headers={"X-Requested-With": "OfficeHub"})
    assert plain.put(save, content=_docx()).status_code == 204

    # closing one page keeps the session for the other; the last one frees the file
    anna.delete(f"/api/craft/lock/{item['id']}?lock={first['lock']}")
    assert anna.get(f"/api/spaces/{space['id']}/files").json()["files"][0]["locked"] is True
    for url, peer in ((a_url, a["peer_id"]), (l_url, l["peer_id"]), (l_url, late["peer_id"])):
        _call(url, "bye", {"peer_id": peer})
    lukas.delete(f"/api/craft/lock/{item['id']}?lock={second['lock']}")
    assert anna.get(f"/api/spaces/{space['id']}/files").json()["files"][0]["locked"] is False


def test_people_who_may_only_look_watch_but_cannot_change(anna, lukas, deck_together, monkeypatch):
    _space_, item = deck_together
    from app.routers import craft as craft_router

    real_role = craft_router.role_in
    monkeypatch.setattr(craft_router, "role_in", lambda db, user, space: None if user.email.startswith("lukas") else real_role(db, user, space))
    anna_open = anna.post(f"/api/craft/open/{item['id']}").json()
    viewer_open = lukas.post(f"/api/craft/open/{item['id']}").json()
    assert viewer_open["can_write"] is False and "collab=" in viewer_open["url"] and "save=" not in viewer_open["url"]
    a = _call(_collab_url(anna_open), "hello").json()
    v = _call(_collab_url(viewer_open), "hello").json()
    assert v["seed"] is False
    _call(_collab_url(anna_open), "update", {"peer_id": a["peer_id"], "data": b64(b"seed")})
    watched = _call(_collab_url(viewer_open), "poll", {"peer_id": v["peer_id"], "after": 0}).json()["messages"]
    assert [m["data"] for m in watched if m["type"] == "update"] == [b64(b"seed")]
    assert _call(_collab_url(viewer_open), "update", {"peer_id": v["peer_id"], "data": b64(b"x")}).status_code == 403


def test_bad_messages_are_refused(anna, deck_together):
    _space_, item = deck_together
    opened = anna.post(f"/api/craft/open/{item['id']}").json()
    url = _collab_url(opened)
    a = _call(url, "hello").json()
    assert _call(url, "update", {"peer_id": a["peer_id"], "data": "not base64!"}).json()["code"] == "invalid_message"
    assert _call(url, "update", {"peer_id": "someone-else", "data": b64(b"x")}).json()["code"] == "collab_gone"
    assert _call(url.replace("token=", "token=x"), "hello").status_code == 401


def test_builds_that_cannot_edit_together_keep_one_person_at_a_time(anna, lukas, deck_together):
    # (the fixture lets only DeckCraft edit together, like an older WordCraft image)
    space, _item = deck_together
    doc = anna.post(f"/api/spaces/{space['id']}/files", files={"file": ("Brief.docx", _docx())}).json()
    first = anna.post(f"/api/craft/open/{doc['id']}").json()
    second = lukas.post(f"/api/craft/open/{doc['id']}").json()
    assert first["can_write"] and not second["can_write"] and second["editing_by"] == "Anna Mayer"
    assert "collab=" not in first["url"]


def test_automatic_saves_while_editing_together_keep_one_version(anna, deck_together):
    space, item = deck_together
    opened = anna.post(f"/api/craft/open/{item['id']}").json()
    save = parse_qs(urlparse(opened["url"]).query)["save"][0]
    plain = TestClient(app, headers={"X-Requested-With": "OfficeHub"})
    for _ in range(3):
        assert plain.put(save + "&auto=1", content=_docx()).status_code == 204
    detail = anna.get(f"/api/spaces/files/{item['id']}").json()
    assert detail["version"] == 2, "three automatic saves, one new version"
    assert detail["versions"][0]["source"] == "together"
    assert plain.put(save, content=_docx()).status_code == 204  # Save by hand: a version of its own
    assert anna.get(f"/api/spaces/files/{item['id']}").json()["version"] == 3
