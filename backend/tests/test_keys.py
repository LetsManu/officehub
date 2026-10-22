"""Identity keys for end-to-end encrypted meetings: OfficeHub stores and hands out public keys and signatures, the
browsers check them. Here: who may change what, and that the keys reach the MLS roster."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

KEY_A = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFB"
KEY_B = "QkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJC"
KEY_C = "Q0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0ND"
SIG = "c2lnbmF0dXJlc2lnbmF0dXJl"


def _device(client, key, name="Browser"):
    response = client.post("/api/keys/devices", json={"public_key": key, "name": name, "signature": SIG})
    assert response.status_code == 201, response.text
    return response.json()


def test_first_device_is_the_root_and_later_ones_wait(anna, lukas):
    root = _device(anna, KEY_A, "Laptop")
    assert root["root"] is True and root["pending"] is False
    phone = _device(anna, KEY_B, "Handy")
    assert phone["root"] is False and phone["pending"] is True
    assert anna.get("/api/me/summary").json()["devices_pending"] == 1
    assert anna.post("/api/keys/devices", json={"public_key": KEY_A, "signature": SIG}).json()["code"] == "device_exists"

    # Only Anna, and only from a confirmed device, confirms the new one
    assert lukas.post(f"/api/keys/devices/{phone['id']}/approve", json={"signed_by": root["id"], "signature": SIG}).status_code == 404
    assert anna.post(f"/api/keys/devices/{phone['id']}/approve", json={"signed_by": phone["id"], "signature": SIG}).status_code == 422
    confirmed = anna.post(f"/api/keys/devices/{phone['id']}/approve", json={"signed_by": root["id"], "signature": SIG}).json()
    assert confirmed["signed_by"] == root["id"] and confirmed["pending"] is False
    assert anna.get("/api/me/summary").json()["devices_pending"] == 0

    # Everyone can fetch Anna's keys to check them; the root cannot simply be removed
    people = lukas.get(f"/api/keys/users/{anna.get('/api/auth/me').json()['id']}").json()
    assert [d["public_key"] for d in people["devices"]] == [KEY_A, KEY_B]
    assert anna.delete(f"/api/keys/devices/{root['id']}").json()["code"] == "root_device"

    # Removing the phone takes back what it confirmed
    tablet = _device(anna, KEY_C, "Tablet")
    anna.post(f"/api/keys/devices/{tablet['id']}/approve", json={"signed_by": phone["id"], "signature": SIG})
    assert anna.delete(f"/api/keys/devices/{phone['id']}").status_code == 204
    devices = anna.get("/api/keys/me").json()["devices"]
    assert [(d["public_key"], d["pending"]) for d in devices] == [(KEY_A, False), (KEY_C, True)]


def test_starting_anew_replaces_all_keys_and_own_checks(anna, lukas):
    lukas_id = lukas.get("/api/auth/me").json()["id"]
    root = _device(anna, KEY_A)
    _device(anna, KEY_B)
    note = {"subject_id": lukas_id, "root": "ab" * 32, "signed_by": root["id"], "signature": SIG}
    assert anna.put("/api/keys/verifications", json=note).status_code == 200
    assert anna.put("/api/keys/verifications", json=note | {"root": "cd" * 32}).json()["root"] == "cd" * 32
    assert len(anna.get("/api/keys/me").json()["verifications"]) == 1
    # Lukas cannot sign in Anna's name with her device
    assert lukas.put("/api/keys/verifications", json=note | {"subject_id": anna.get("/api/auth/me").json()["id"]}).status_code == 404

    fresh = anna.post("/api/keys/reset", json={"public_key": KEY_C, "name": "Neu", "signature": SIG}).json()
    assert fresh["root"] is True
    mine = anna.get("/api/keys/me").json()
    assert [d["public_key"] for d in mine["devices"]] == [KEY_C] and mine["verifications"] == []


def test_strict_rule_keeps_guests_out_and_keys_travel_with_the_roster(julia, anna, lukas):
    assert anna.put("/api/keys/policy", json={"policy": "strict"}).status_code == 403
    assert julia.put("/api/keys/policy", json={"policy": "strict"}).json()["policy"] == "strict"
    _device(lukas, KEY_B)

    start = datetime.now(timezone.utc) + timedelta(hours=1)
    lukas_id = lukas.get("/api/auth/me").json()["id"]
    meeting = anna.post("/api/meetings", json={"title": "Vertraulich", "starts_at": start.isoformat(),
                                               "ends_at": (start + timedelta(hours=1)).isoformat(),
                                               "invitee_ids": [lukas_id], "e2ee": True, "allow_guests": True}).json()
    connection = lukas.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    assert connection["e2ee"]["policy"] == "strict"
    client = TestClient(app, headers={"X-Requested-With": "OfficeHub"})
    roster = client.post("/api/rtc/mls/hello", headers={"X-Meeting-Token": connection["e2ee"]["token"]}).json()["roster"]
    assert [d["public_key"] for d in roster["members"][-1]["keys"]] == [KEY_B]

    refused = client.post(f"/api/guest{meeting['guest_link'].removeprefix('/guest')}/request", json={"name": "Besuch"})
    assert refused.json()["code"] == "e2ee_guests_blocked"
    julia.put("/api/keys/policy", json={"policy": "warn"})
