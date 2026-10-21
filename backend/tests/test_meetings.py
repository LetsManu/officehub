import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.models import Meeting
from app.services import meetings as meeting_service
from app.services.office import jwt_decode

SECRET = "jitsi-test-secret"


@pytest.fixture
def jitsi(monkeypatch):
    patched = dataclasses.replace(config.settings, jitsi_app_secret=SECRET)
    monkeypatch.setattr(meeting_service, "settings", patched)


def _ids(client):
    return {p["full_name"]: p["id"] for p in client.get("/api/directory").json()}


def _plan(client, invitees, **extra):
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    body = {"title": "Planung Q1", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat(),
            "invitee_ids": invitees, **extra}
    response = client.post("/api/meetings", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_meetings_off_without_jitsi(anna):
    assert anna.get("/api/meetings/config").json() == {"enabled": False}
    meeting = _plan(anna, [])
    assert anna.post(f"/api/meetings/{meeting['id']}/join").json()["code"] == "meetings_unavailable"


def test_plan_invite_respond_and_join(anna, lukas, sara, jitsi):
    ids = _ids(anna)
    meeting = _plan(anna, [ids["Lukas Schmid"]])
    assert [i["person"]["full_name"] for i in meeting["invitees"]] == ["Lukas Schmid"]
    assert "meeting_invite" in [n["kind"] for n in lukas.get("/api/notifications").json()["items"]]
    assert "Planung Q1" in [m["title"] for m in lukas.get("/api/meetings").json()]
    assert sara.get(f"/api/meetings/{meeting['id']}").status_code == 404  # not invited

    assert lukas.post(f"/api/meetings/{meeting['id']}/respond", json={"response": "accepted"}).json()["my_response"] == "accepted"
    ics = lukas.get(f"/api/meetings/{meeting['id']}/ics")
    assert ics.status_code == 200 and "BEGIN:VEVENT" in ics.text and "SUMMARY:Planung Q1" in ics.text

    joined = lukas.post(f"/api/meetings/{meeting['id']}/join").json()
    conn = joined["connection"]
    claims = jwt_decode(conn["token"], SECRET)
    assert claims["room"] == conn["room"] and claims["context"]["user"]["name"] == "Lukas Schmid"
    assert claims["aud"] == "officehub" and claims["sub"] == "meet.jitsi"
    assert conn["websocket"] == "/jitsi/xmpp-websocket"
    live = anna.post(f"/api/meetings/{meeting['id']}/presence").json()["live"]
    assert {p["name"] for p in live} == {"Lukas Schmid", "Anna Mayer"}

    # bad times, organizer-only changes, cancelling notifies
    start = datetime.now(timezone.utc)
    bad = anna.post("/api/meetings", json={"title": "x", "starts_at": start.isoformat(), "ends_at": start.isoformat()})
    assert bad.status_code == 422 and bad.json()["field"] == "ends_at"
    assert lukas.delete(f"/api/meetings/{meeting['id']}").status_code == 403
    assert anna.delete(f"/api/meetings/{meeting['id']}").status_code == 204
    assert "meeting_cancelled" in [n["kind"] for n in lukas.get("/api/notifications").json()["items"]]
    assert lukas.post(f"/api/meetings/{meeting['id']}/join").json()["code"] == "meeting_cancelled"


def test_notes_conflict_and_wiki(anna, lukas, jitsi):
    space = anna.post("/api/spaces", json={"name": "Team"}).json()
    anna.post(f"/api/spaces/{space['id']}/members", json={"user_id": _ids(anna)["Lukas Schmid"]})
    meeting = _plan(anna, [], space_id=space["id"])
    # space members may join a space meeting without an invitation
    assert lukas.get(f"/api/meetings/{meeting['id']}").status_code == 200
    saved = lukas.put(f"/api/meetings/{meeting['id']}/notes", json={"notes": "- Budget ok", "base_version": 0}).json()
    assert saved["notes_version"] == 1
    assert anna.put(f"/api/meetings/{meeting['id']}/notes", json={"notes": "x", "base_version": 0}).json()["code"] == "notes_conflict"
    page = anna.post(f"/api/meetings/{meeting['id']}/notes-to-wiki").json()
    assert anna.get(f"/api/wiki/{page['page_id']}").json()["body"] == "- Budget ok"


def test_guests_wait_until_admitted(anna, jitsi):
    meeting = _plan(anna, [], allow_guests=True)
    token = meeting["guest_link"].rsplit("/", 1)[-1]
    guest = TestClient(app, headers={"X-Requested-With": "OfficeHub"})  # no account
    assert guest.get(f"/api/guest/{token}").json()["title"] == "Planung Q1"
    assert guest.get("/api/guest/wrong-token").status_code == 404
    request = guest.post(f"/api/guest/{token}/request", json={"name": "Erika Muster"}).json()
    assert request["status"] == "waiting" and guest.get(f"/api/guest/status/{request['secret']}").json()["join"] is None
    waiting = anna.post(f"/api/meetings/{meeting['id']}/presence").json()["waiting"]
    assert [w["name"] for w in waiting] == ["Erika Muster"]
    anna.post(f"/api/meetings/{meeting['id']}/guests/{waiting[0]['id']}/admit")
    status = guest.get(f"/api/guest/status/{request['secret']}").json()
    assert status["status"] == "admitted"
    claims = jwt_decode(status["join"]["connection"]["token"], SECRET)
    assert claims["moderator"] is False and claims["context"]["user"]["name"].startswith("Erika Muster")
    # guests cannot use the API otherwise
    assert guest.get(f"/api/meetings/{meeting['id']}").status_code == 401


def test_call_rings_and_can_be_declined_or_missed(anna, lukas, julia, jitsi):
    dm = anna.post("/api/chat/direct", json={"user_id": _ids(anna)["Lukas Schmid"]}).json()
    call = anna.post("/api/calls", json={"channel_id": dm["id"]}).json()
    assert call["connection"]["room"].startswith("c-")
    ringing = lukas.get("/api/calls/incoming").json()
    assert [r["caller"]["full_name"] for r in ringing] == ["Anna Mayer"]
    assert anna.get(f"/api/calls/{call['meeting_id']}").json()["status"] == "ringing"
    assert julia.post("/api/calls", json={"channel_id": dm["id"]}).status_code == 404  # not in the conversation
    lukas.post(f"/api/calls/{call['meeting_id']}/decline")
    assert anna.get(f"/api/calls/{call['meeting_id']}").json()["status"] == "declined"
    assert lukas.get("/api/calls/incoming").json() == []
    messages = lukas.get(f"/api/chat/{dm['id']}/messages").json()["messages"]
    assert messages[-1]["meeting"]["id"] == call["meeting_id"]

    # a second call nobody answers becomes a missed call
    second = anna.post("/api/calls", json={"channel_id": dm["id"]}).json()
    from app.db import SessionLocal

    with SessionLocal() as db:
        db.get(Meeting, second["meeting_id"]).created_at -= timedelta(minutes=2)
        db.commit()
    assert lukas.get("/api/calls/incoming").json() == []
    assert "call_missed" in [n["kind"] for n in lukas.get("/api/notifications").json()["items"]]
    # answering by joining
    third = anna.post("/api/calls", json={"channel_id": dm["id"]}).json()
    lukas.post(f"/api/meetings/{third['meeting_id']}/join")
    assert anna.get(f"/api/calls/{third['meeting_id']}").json()["status"] == "active"
    anna.delete(f"/api/meetings/{third['meeting_id']}/presence")
    lukas.delete(f"/api/meetings/{third['meeting_id']}/presence")
    assert anna.get(f"/api/calls/{third['meeting_id']}").json()["status"] == "ended"


def test_space_room(anna, sara, jitsi):
    space = anna.post("/api/spaces", json={"name": "Team"}).json()
    room = anna.get(f"/api/spaces/{space['id']}/meeting").json()
    assert room["kind"] == "space" and anna.get(f"/api/spaces/{space['id']}/meeting").json()["id"] == room["id"]
    assert anna.post(f"/api/meetings/{room['id']}/join").status_code == 200
    assert sara.post(f"/api/meetings/{room['id']}/join").status_code == 404
