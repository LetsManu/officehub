"""Leading a meeting like in Teams: moderation, town halls and breakout rooms."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services import breakouts, rtc

from test_meetings import SECRET, _ids, _plan, jitsi  # noqa: F401 - fixture

client = TestClient(app, headers={"X-Requested-With": "OfficeHub"})


def _hello(token):
    return client.post("/api/rtc/hello", headers={"X-Meeting-Token": token})


def _send(token, peer, data, to=None):
    return client.post("/api/rtc/send", headers={"X-Meeting-Token": token},
                       json={"peer_id": peer, "to": to, "type": "app", "data": data})


def _poll(token, peer, after=0):
    return client.post("/api/rtc/poll", headers={"X-Meeting-Token": token}, json={"peer_id": peer, "after": after}).json()


def test_only_the_organizer_moderates_and_can_remove(anna, lukas):
    meeting = _plan(anna, [_ids(anna)["Lukas Schmid"]])
    assert meeting["is_moderator"] is True and lukas.get(f"/api/meetings/{meeting['id']}").json()["is_moderator"] is False
    a = anna.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    b = lukas.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    assert a["moderator"] is True and b["moderator"] is False and a["who"] != b["who"]
    pa = _hello(a["token"]).json()["peer_id"]
    hello_b = _hello(b["token"]).json()
    pb = hello_b["peer_id"]
    assert hello_b["peers"][0]["mod"] is True and hello_b["peers"][0]["who"] == a["who"]

    # everyone may react; only the organizer may mute everyone
    assert _send(b["token"], pb, {"kind": "react", "emoji": "👏"}).status_code == 204
    assert _send(b["token"], pb, {"kind": "mute-all"}).status_code == 403
    assert _send(b["token"], pb, {"kind": "anything"}).status_code == 422
    assert _send(a["token"], pa, {"kind": "mute-all"}).status_code == 204
    kinds = [m["data"].get("kind") for m in _poll(b["token"], pb)["messages"] if m["type"] == "app"]
    assert kinds == ["mute-all"]

    # Lukas cannot remove Anna; Anna removes Lukas, who cannot come back
    remove = lambda token, peer, target: client.post("/api/rtc/remove", headers={"X-Meeting-Token": token},  # noqa: E731
                                                      json={"peer_id": peer, "target": target})
    assert remove(b["token"], pb, pa).status_code == 403
    assert remove(a["token"], pa, pb).status_code == 204
    assert _hello(b["token"]).json()["code"] == "removed_from_meeting"
    rtc.removed.clear()


def test_town_hall_allows_a_larger_audience(anna, lukas):
    meeting = _plan(anna, [_ids(anna)["Lukas Schmid"]], town_hall=True)
    assert meeting["town_hall"] is True
    b = lukas.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    assert b["town_hall"] is True and b["max_people"] == 30


def test_breakout_rooms(anna, lukas, sara):
    ids = _ids(anna)
    meeting = _plan(anna, [ids["Lukas Schmid"], ids["Sara Novak"]])
    a = anna.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    b = lukas.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    s = sara.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    get = lambda c: client.get("/api/rtc/breakouts", headers={"X-Meeting-Token": c["token"]})  # noqa: E731
    join = lambda c, room: client.post("/api/rtc/breakouts/join", headers={"X-Meeting-Token": c["token"]},  # noqa: E731
                                       json={"room": room})
    assert get(b).json()["open"] is False and "assign" not in get(b).json()

    body = {"rooms": ["Gruppe 1", "Gruppe 2"], "assign": {b["who"]: 0, s["who"]: 1}, "open": True, "minutes": 10}
    assert client.put("/api/rtc/breakouts", headers={"X-Meeting-Token": b["token"]}, json=body).status_code == 403
    assert client.put("/api/rtc/breakouts", headers={"X-Meeting-Token": a["token"]},
                      json={**body, "assign": {b["who"]: 5}}).json()["code"] == "invalid_room"
    state = client.put("/api/rtc/breakouts", headers={"X-Meeting-Token": a["token"]}, json=body).json()
    assert state["open"] and state["assign"] == {b["who"]: 0, s["who"]: 1}
    assert get(b).json()["mine"] == 0 and get(s).json()["mine"] == 1

    # Lukas gets a ticket for his room only; it keeps his name and role, and works in the room
    room = join(b, 0).json()
    assert room["room"] == f"{b['room']}-b1" and room["who"] == b["who"] and room["moderator"] is False
    assert join(b, 1).status_code == 403
    assert join(a, 1).status_code == 200  # the organizer can visit every room
    assert _hello(room["token"]).status_code == 200
    assert get(room).json()["current"] == room["room"]
    assert join(room, None).json()["room"] == b["room"]  # back to the meeting

    # when the time is up everyone is called back
    breakouts.get(b["room"]).ends_at = datetime.now(timezone.utc).timestamp() - 1
    assert get(b).json()["open"] is False and join(b, 0).status_code == 403
    breakouts.meetings.clear()


def test_breakout_rooms_with_jitsi(anna, lukas, jitsi):  # noqa: F811
    meeting = _plan(anna, [_ids(anna)["Lukas Schmid"]])
    a = anna.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    assert a["mode"] == "jitsi" and a["moderator"] is True
    client.put("/api/rtc/breakouts", headers={"X-Meeting-Token": a["token"]},
               json={"rooms": ["Eins"], "assign": {}, "open": True})
    room = client.post("/api/rtc/breakouts/join", headers={"X-Meeting-Token": a["token"]}, json={"room": 0}).json()
    assert room["mode"] == "jitsi" and room["room"] == f"{a['room']}-b1"
    from app.services.office import jwt_decode
    claims = jwt_decode(room["token"], SECRET)
    assert claims["room"] == room["room"] and claims["main"] == a["room"] and claims["mod"] is True
    breakouts.meetings.clear()
