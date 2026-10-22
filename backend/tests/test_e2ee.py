"""End-to-end encrypted meetings: who must have them, and OfficeHub as the MLS delivery service."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

KP = "a2V5LXBhY2thZ2U="  # stands in for a key package (the server never reads it)


def _ids(client):
    return {p["full_name"]: p["id"] for p in client.get("/api/directory").json()}


def _plan(client, invitees, **extra):
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    body = {"title": "Vertraulich", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat(),
            "invitee_ids": invitees} | extra
    response = client.post("/api/meetings", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _users(julia):
    return {u["full_name"]: u for u in julia.get("/api/admin/users").json()}


def test_hr_makes_encryption_required_for_a_person(julia, lukas, anna):
    lukas_row = _users(julia)["Lukas Schmid"]
    assert lukas_row["e2ee_required"] is False
    assert julia.patch(f"/api/admin/users/{lukas_row['id']}", json={"e2ee_required": True}).status_code == 200
    assert anna.patch(f"/api/admin/users/{lukas_row['id']}", json={"e2ee_required": False}).status_code == 403

    # Lukas's meetings are encrypted even when he does not tick it, and stay so when he edits them
    meeting = _plan(lukas, [_ids(lukas)["Anna Mayer"]])
    assert meeting["e2ee"] is True and meeting["e2ee_forced"] is True
    body = {"title": "Neu", "starts_at": meeting["starts_at"], "ends_at": meeting["ends_at"], "e2ee": False}
    assert lukas.put(f"/api/meetings/{meeting['id']}", json=body).json()["e2ee"] is True

    # a call that rings Lukas is encrypted; Anna's own meetings are as she chooses
    call = anna.post("/api/calls", json={"user_id": lukas_row["id"]}).json()
    assert call["connection"]["e2ee"]["signal"] == "/api/rtc/mls"
    assert _plan(anna, [])["e2ee"] is False
    assert _plan(anna, [], e2ee=True)["e2ee"] is True


def test_mls_delivery_orders_commits_and_never_sees_plaintext(anna, lukas):
    meeting = _plan(anna, [_ids(anna)["Lukas Schmid"]], e2ee=True)
    a = anna.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    b = lukas.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    ta, tb = a["e2ee"]["token"], b["e2ee"]["token"]
    client = TestClient(app, headers={"X-Requested-With": "OfficeHub"})

    def post(token, path, **body):
        return client.post(f"/api/rtc/mls/{path}", headers={"X-Meeting-Token": token}, json=body or None)

    first = post(ta, "hello").json()
    assert first["roster"]["epoch"] is None  # nobody has made the group yet
    second = post(tb, "hello").json()
    ma, mb = first["member_id"], second["member_id"]
    assert post(ta, "create", member_id=ma).json()["created"] is True
    assert post(tb, "create", member_id=mb).json()["created"] is False  # Anna was quicker
    assert post(tb, "publish", member_id=mb, key_package=KP).status_code == 200

    roster = post(ta, "poll", member_id=ma).json()["messages"][-1]["data"]
    assert roster["leader"] == ma and roster["epoch"] == 0
    assert [m["key_package"] for m in roster["members"]] == ["", KP]

    # only a member of the group, on the current epoch, can commit
    assert post(tb, "commit", member_id=mb, epoch=0, message="Yw==").status_code == 409
    assert post(ta, "commit", member_id=ma, epoch=0, message="Yw==", welcome="dw==", added=[mb]).json()["epoch"] == 1
    assert post(ta, "commit", member_id=ma, epoch=0, message="Yw==").json()["code"] == "epoch_conflict"
    got = post(tb, "poll", member_id=mb).json()["messages"]
    assert any(m["type"] == "welcome" and m["data"] == {"epoch": 1, "message": "dw=="} for m in got)

    # sealed messages pass to the group as they are
    assert post(ta, "app", member_id=ma, epoch=1, message="c2VhbGVk").status_code == 204
    after = got[-1]["seq"]
    sealed = post(tb, "poll", member_id=mb, after=after).json()["messages"]
    assert sealed[0]["type"] == "app" and sealed[0]["data"] == {"epoch": 1, "message": "c2VhbGVk"}

    # plaintext chat and reactions are refused in this meeting
    rtc = client.post("/api/rtc/hello", headers={"X-Meeting-Token": a["token"]}).json()
    plain = client.post("/api/rtc/send", headers={"X-Meeting-Token": a["token"]},
                        json={"peer_id": rtc["peer_id"], "type": "chat", "data": {"text": "geheim"}})
    assert plain.json()["code"] == "encrypted_only"
    react = client.post("/api/rtc/send", headers={"X-Meeting-Token": a["token"]},
                        json={"peer_id": rtc["peer_id"], "type": "app", "data": {"kind": "react", "emoji": "x"}})
    assert react.status_code == 422

    # Anna leaves: Lukas becomes the leader and is asked to remove her
    assert post(ta, "bye", member_id=ma).status_code == 204
    last = post(tb, "poll", member_id=mb, after=sealed[-1]["seq"]).json()["messages"][-1]["data"]
    assert last["leader"] == mb and last["gone"] == [ma]
    assert post(tb, "commit", member_id=mb, epoch=1, message="cg==", removed=[ma]).json()["epoch"] == 2


def test_unencrypted_meetings_have_no_mls_group(anna):
    meeting = _plan(anna, [])
    connection = anna.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]
    assert "e2ee" not in connection
    client = TestClient(app, headers={"X-Requested-With": "OfficeHub"})
    assert client.post("/api/rtc/mls/hello", headers={"X-Meeting-Token": connection["token"]}).status_code == 403


def test_a_closed_page_leaves_the_group(anna, lukas, monkeypatch):
    from app.services import mls

    meeting = _plan(anna, [_ids(anna)["Lukas Schmid"]], e2ee=True)
    ta = anna.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]["e2ee"]["token"]
    tb = lukas.post(f"/api/meetings/{meeting['id']}/join").json()["connection"]["e2ee"]["token"]
    client = TestClient(app, headers={"X-Requested-With": "OfficeHub"})
    ma = client.post("/api/rtc/mls/hello", headers={"X-Meeting-Token": ta}).json()["member_id"]
    client.post("/api/rtc/mls/create", headers={"X-Meeting-Token": ta}, json={"member_id": ma})
    mb = client.post("/api/rtc/mls/hello", headers={"X-Meeting-Token": tb}).json()["member_id"]
    room = next(r for r, g in mls.groups.items() if mb in g.members)
    mls.groups[room].members[ma].seen -= mls.GONE_SECONDS + 1  # Anna's tab closed long ago
    monkeypatch.setattr(mls, "POLL_SECONDS", 0)
    roster = client.post("/api/rtc/mls/poll", headers={"X-Meeting-Token": tb}, json={"member_id": mb}).json()["messages"][-1]["data"]
    assert [m["id"] for m in roster["members"]] == [mb]
    assert roster["epoch"] is None  # nobody holds the keys any more: Lukas starts a new group
