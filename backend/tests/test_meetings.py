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
    patched = dataclasses.replace(config.settings, jitsi_app_secret=SECRET, jitsi_internal_url="http://jitsi-web")
    monkeypatch.setattr(meeting_service, "settings", patched)
    monkeypatch.setattr(meeting_service, "reachable", lambda url: True)  # the Jitsi server is running


def _ids(client):
    return {p["full_name"]: p["id"] for p in client.get("/api/directory").json()}


def _plan(client, invitees, **extra):
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    body = {"title": "Planung Q1", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat(),
            "invitee_ids": invitees, **extra}
    response = client.post("/api/meetings", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_builtin_meetings_without_any_server(anna, lukas, sara):
    """Without a Jitsi server meetings still work: OfficeHub introduces the browsers to each other."""
    assert anna.get("/api/meetings/config").json() == {"enabled": True, "mode": "builtin"}
    assert anna.get("/api/config").json()["meetings_enabled"] is True
    meeting = _plan(anna, [_ids(anna)["Lukas Schmid"]])
    a = anna.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    b = lukas.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    assert a["mode"] == "builtin" and a["room"] == b["room"] and a["ice_servers"] == []

    rtc_client = TestClient(app, headers={"X-Requested-With": "OfficeHub"})  # works without a session (guests, apps)
    first = rtc_client.post("/api/rtc/hello", headers={"X-Meeting-Token": a["token"]}).json()
    assert first["peers"] == []
    second = rtc_client.post("/api/rtc/hello", headers={"X-Meeting-Token": b["token"]}).json()
    assert [p["name"] for p in second["peers"]] == ["Anna Mayer"]

    # Lukas sends an offer to Anna; Anna sees that he joined and receives it
    offer = {"sdp": {"type": "offer", "sdp": "v=0"}}
    sent = rtc_client.post("/api/rtc/send", headers={"X-Meeting-Token": b["token"]},
                           json={"peer_id": second["peer_id"], "to": first["peer_id"], "type": "signal", "data": offer})
    assert sent.status_code == 204
    rtc_client.post("/api/rtc/send", headers={"X-Meeting-Token": b["token"]},
                    json={"peer_id": second["peer_id"], "type": "state", "data": {"audioMuted": True}})
    got = rtc_client.post("/api/rtc/poll", headers={"X-Meeting-Token": a["token"]}, json={"peer_id": first["peer_id"]}).json()
    assert [m["type"] for m in got["messages"]] == ["join", "signal", "state"]
    assert got["messages"][1]["data"] == offer and got["messages"][1]["from"] == second["peer_id"]

    # someone else's ticket cannot read Anna's messages; a forged ticket is refused
    assert rtc_client.post("/api/rtc/poll", headers={"X-Meeting-Token": b["token"]},
                           json={"peer_id": first["peer_id"]}).json()["code"] == "peer_gone"
    assert rtc_client.post("/api/rtc/hello", headers={"X-Meeting-Token": a["token"] + "x"}).status_code == 401
    assert sara.post(f"/api/meetings/{meeting['id']}/join").status_code == 404  # not invited

    rtc_client.post("/api/rtc/bye", headers={"X-Meeting-Token": b["token"]}, json={"peer_id": second["peer_id"]})
    after = got["messages"][-1]["seq"]
    left = rtc_client.post("/api/rtc/poll", headers={"X-Meeting-Token": a["token"]},
                           json={"peer_id": first["peer_id"], "after": after}).json()
    assert [m["type"] for m in left["messages"]] == ["leave"]


def test_call_a_person_directly(anna, lukas):
    call = anna.post("/api/calls", json={"user_id": _ids(anna)["Lukas Schmid"]})
    assert call.status_code == 201
    assert [r["caller"]["full_name"] for r in lukas.get("/api/calls/incoming").json()] == ["Anna Mayer"]
    assert anna.post("/api/calls", json={}).status_code == 404


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
    assert conn["websocket"] == "/jitsi/xmpp-websocket" and conn["mode"] == "jitsi"
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
    conversation = next(c for c in lukas.get("/api/chat").json() if c["id"] == dm["id"])
    assert conversation["last"]["call"] is True  # the list shows "Call" instead of an empty text

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


def test_shared_passwords_are_made_once(tmp_path, monkeypatch):
    """Office and meeting servers get their passwords from OfficeHub's first start – nobody types them in."""
    monkeypatch.setenv("SHARED_DIR", str(tmp_path))
    first = config._shared_secret("jitsi_app_secret")
    assert first and len(first) > 30 and config._shared_secret("jitsi_app_secret") == first
    monkeypatch.setenv("SHARED_DIR", str(tmp_path / "missing"))
    assert config._shared_secret("jitsi_app_secret") is None  # outside Docker: nothing to share


def test_jitsi_is_used_only_while_it_runs(anna, jitsi, monkeypatch):
    assert anna.get("/api/meetings/config").json()["mode"] == "jitsi"
    monkeypatch.setattr(meeting_service, "reachable", lambda url: False)  # container stopped
    assert anna.get("/api/meetings/config").json()["mode"] == "builtin"


def test_relay_for_people_on_other_networks(monkeypatch):
    """With the stack's own relay (coturn) built-in meetings work across networks: short-lived TURN passwords made
    from the shared secret, in the form coturn's use-auth-secret checks."""
    import base64
    import dataclasses
    import hashlib
    import hmac
    import time

    from app.services import meetings

    patched = dataclasses.replace(meetings.settings, turn_secret="s3cret", portal_url="https://hub.example.com",
                                  ice_servers=())
    monkeypatch.setattr(meetings, "settings", patched)
    [server] = meetings.ice_servers("u7")
    assert server["urls"] == ["stun:hub.example.com:3478", "turn:hub.example.com:3478?transport=udp",
                              "turn:hub.example.com:3478?transport=tcp"]
    expires, who = server["username"].split(":")
    assert who == "u7" and int(expires) > time.time() + 3600
    digest = hmac.new(b"s3cret", server["username"].encode(), hashlib.sha1).digest()
    assert server["credential"] == base64.b64encode(digest).decode()

    # Servers of your own replace it
    own = dataclasses.replace(patched, ice_servers=("turn:turn.example.com:3478",), ice_username="a", ice_password="b")
    monkeypatch.setattr(meetings, "settings", own)
    assert meetings.ice_servers("u7") == [{"urls": ["turn:turn.example.com:3478"], "username": "a", "credential": "b"}]


def test_public_address_is_shared_with_the_meeting_servers(monkeypatch, tmp_path):
    from app.config import _public_address

    monkeypatch.setenv("SHARED_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_IP", "203.0.113.7")
    assert _public_address("https://hub.example.com") == "203.0.113.7"
    assert (tmp_path / "public_ip").read_text() == "203.0.113.7"
    monkeypatch.delenv("PUBLIC_IP")
    monkeypatch.delenv("JITSI_PUBLIC_IP", raising=False)
    assert _public_address("http://localhost:8080") is None


def test_relay_is_reached_with_the_name_people_use(monkeypatch, tmp_path):
    """Without PORTAL_URL the relay and the meeting servers still find the server: by the name the portal was opened
    with."""
    import dataclasses

    from app.services import meetings

    monkeypatch.setenv("SHARED_DIR", str(tmp_path))
    patched = dataclasses.replace(meetings.settings, turn_secret="s3cret", portal_url="http://localhost:8080",
                                  ice_servers=(), public_address=None)
    monkeypatch.setattr(meetings, "settings", patched)
    monkeypatch.setattr(meetings, "_resolve", lambda host: "198.51.100.4" if host == "office.example.com" else None)
    monkeypatch.setattr(meetings, "_noted", set())
    token = meetings.request_host.set("office.example.com:443")
    try:
        assert meetings.ice_servers("u1")[0]["urls"][0] == "stun:office.example.com:3478"
        meetings.note_host()
    finally:
        meetings.request_host.reset(token)
    assert (tmp_path / "public_ip").read_text() == "198.51.100.4"
