from datetime import date, timedelta

from conftest import make_client


def _vacation(client, submit=True):
    start = date.today() + timedelta(days=40)
    while start.weekday() >= 5:
        start += timedelta(days=1)
    response = client.post(
        "/api/requests",
        json={"type": "vacation", "title": "Summer", "start_date": start.isoformat(), "end_date": start.isoformat(), "submit": submit},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _kinds(client):
    return [n["kind"] for n in client.get("/api/notifications").json()["items"]]


def test_submit_notifies_manager_and_decision_notifies_requester(anna, tom):
    before = tom.get("/api/notifications").json()["unread"]
    req = _vacation(anna)
    data = tom.get("/api/notifications").json()
    assert data["unread"] == before + 1
    newest = data["items"][0]
    assert newest["kind"] == "request_submitted"
    assert newest["params"]["name"] == "Anna Mayer"
    assert newest["link"] == f"/requests/{req['id']}"

    assert tom.post(f"/api/requests/{req['id']}/approve", json={}).status_code == 200
    assert _kinds(anna)[0] == "request_approved"


def test_comment_notifies_other_side_only(anna, tom):
    req = _vacation(anna)
    tom.post(f"/api/requests/{req['id']}/comments", json={"body": "Looks fine"})
    assert _kinds(anna)[0] == "request_comment"
    count = len(_kinds(tom))
    anna.post(f"/api/requests/{req['id']}/comments", json={"body": "Thanks"})
    kinds = _kinds(tom)
    assert len(kinds) == count + 1 and kinds[0] == "request_comment"
    # Anna does not hear about her own comment
    assert _kinds(anna).count("request_comment") == 1


def test_draft_does_not_notify(anna, tom):
    before = len(_kinds(tom))
    _vacation(anna, submit=False)
    assert len(_kinds(tom)) == before


def test_mark_read_and_privacy(anna, tom):
    item = tom.get("/api/notifications").json()["items"][0]
    assert anna.post(f"/api/notifications/{item['id']}/read").status_code == 404
    assert tom.post(f"/api/notifications/{item['id']}/read").json()["read"] is True
    assert tom.post("/api/notifications/read-all").status_code == 204
    assert tom.get("/api/notifications").json()["unread"] == 0
    assert tom.get("/api/me/summary").json()["unread"] == 0


def test_summary_counts(anna, tom):
    summary = tom.get("/api/me/summary").json()
    assert summary["approvals_pending"] >= 1
    assert summary["visitors_today"] >= 1
    assert anna.get("/api/me/summary").json()["approvals_pending"] == 0


def test_visitor_check_in_notifies_host(tom, julia):
    visitors = julia.get("/api/visitors?scope=day").json()
    guest = next(v for v in visitors if v["host_name"] == "Tom Huber")
    assert julia.post(f"/api/visitors/{guest['id']}/status", json={"action": "check_in"}).status_code == 200
    newest = tom.get("/api/notifications").json()["items"][0]
    assert newest["kind"] == "visitor_arrived" and newest["params"]["name"] == guest["name"]


def test_search_groups_and_permissions(anna, tom):
    assert anna.get("/api/search?q=a").status_code == 422
    result = anna.get("/api/search?q=weber").json()
    assert any(p["last_name"] == "Weber" for p in result["people"])
    # Anna only finds her own requests; Tom (approver) sees others too.
    titles = [r["title"] for r in tom.get("/api/search?q=laptop").json()["requests"]]
    assert titles
    assert anna.get("/api/search?q=laptop").json()["requests"] == []


def test_search_escapes_wildcards(anna):
    result = anna.get("/api/search?q=%25%25").json()
    assert all(not v for v in result.values())


def test_unauthenticated():
    client = make_client()
    assert client.get("/api/notifications").status_code == 401
    assert client.get("/api/search?q=test").status_code == 401


def test_admin_cancelling_booking_notifies_owner(anna, julia):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    bookings = julia.get(f"/api/rooms/bookings?day={tomorrow}").json()
    booking = next(b for b in bookings if b["person_name"] == "Anna Mayer")
    assert julia.delete(f"/api/rooms/bookings/{booking['id']}").status_code == 204
    newest = anna.get("/api/notifications").json()["items"][0]
    assert newest["kind"] == "booking_cancelled" and newest["params"]["day"] == tomorrow


def test_review_created_notifies_both(julia, lukas, tom):
    people = {p["full_name"]: p["id"] for p in julia.get("/api/directory").json()}
    response = julia.post(
        "/api/reviews",
        json={"employee_id": people["Lukas Schmid"], "reviewer_id": people["Tom Huber"], "year": date.today().year},
    )
    assert response.status_code == 201, response.text
    assert _kinds(lukas)[0] == "review_created"
    assert tom.get("/api/notifications").json()["items"][0]["params"]["name"] == "Lukas Schmid"
