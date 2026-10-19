from datetime import date, timedelta

from conftest import make_client


def _me(client):
    return client.get("/api/profile").json()


def _announcement(client, category):
    return next(a for a in client.get("/api/announcements").json() if a["category"] == category)


# ---------- Must-read ----------


def test_must_read_confirm_and_hr_overview(anna, julia):
    item = _announcement(anna, "it")
    assert item["must_read"] and item["confirmed_at"] is None
    assert anna.get("/api/me/summary").json()["must_read_open"] == 1

    assert anna.get(f"/api/announcements/{item['id']}/confirmations").status_code == 403
    before = julia.get(f"/api/announcements/{item['id']}/confirmations").json()
    assert any(p["full_name"] == "Anna Mayer" for p in before["missing"])

    confirmed = anna.post(f"/api/announcements/{item['id']}/confirm").json()
    assert confirmed["confirmed_at"] is not None
    assert anna.get("/api/me/summary").json()["must_read_open"] == 0
    after = julia.get(f"/api/announcements/{item['id']}/confirmations").json()
    assert any(p["full_name"] == "Anna Mayer" for p in after["confirmed"])

    result = julia.post(f"/api/announcements/{item['id']}/remind").json()
    assert result["reminded"] == len(after["missing"]) - 1  # Julia does not remind herself


def test_confirm_only_for_must_read(anna):
    item = _announcement(anna, "general")
    assert anna.post(f"/api/announcements/{item['id']}/confirm").status_code == 409


def test_new_must_read_notifies_everyone(julia, lukas):
    body = {"title": "Neue Hausordnung", "body": "Bitte lesen.", "must_read": True}
    assert julia.post("/api/announcements", json=body).status_code == 201
    assert lukas.get("/api/notifications").json()["items"][0]["kind"] == "must_read_new"


# ---------- Polls ----------


def test_poll_hides_results_until_voted(anna, julia):
    item = _announcement(anna, "event")
    assert item["poll"]["counts"] is None and item["poll"]["my_vote"] is None
    assert anna.post(f"/api/announcements/{item['id']}/vote", json={"option": 9}).status_code == 422
    voted = anna.post(f"/api/announcements/{item['id']}/vote", json={"option": 1}).json()["poll"]
    assert voted["my_vote"] == 1 and voted["counts"][1] == 1 and voted["total"] == 1
    # Changing the vote does not count twice
    again = anna.post(f"/api/announcements/{item['id']}/vote", json={"option": 0}).json()["poll"]
    assert again["counts"] == [1, 0, 0] and again["total"] == 1
    # HR always sees results
    assert _announcement(julia, "event")["poll"]["counts"] == [1, 0, 0]


def test_poll_needs_options(julia):
    body = {"title": "Umfrage", "body": "Text", "poll_question": "Frage?"}
    response = julia.post("/api/announcements", json=body)
    assert response.status_code == 422 and response.json()["code"] == "poll_options_required"


def test_changing_poll_options_resets_votes(anna, julia):
    item = _announcement(anna, "event")
    anna.post(f"/api/announcements/{item['id']}/vote", json={"option": 2})
    julia.patch(f"/api/announcements/{item['id']}", json={"poll_options": ["Ja", "Nein"]})
    assert _announcement(julia, "event")["poll"]["total"] == 0


# ---------- Team ----------


def test_who_is_away_without_reasons(anna):
    away = anna.get("/api/team/away").json()
    names = {a["person"]["full_name"]: a for a in away}
    assert names["Sara Novak"]["type"] == "vacation"
    assert "description" not in names["Sara Novak"] and "title" not in names["Sara Novak"]
    assert names["Anna Mayer"]["type"] == "home_office"


def test_celebrations_respect_opt_in(anna):
    items = anna.get("/api/team/celebrations").json()
    kinds = {(c["person"]["full_name"], c["kind"]) for c in items}
    assert ("Lukas Schmid", "birthday") in kinds
    assert ("Max Gruber", "new") in kinds
    assert ("Anna Mayer", "anniversary") in kinds
    assert not any(name == "Sara Novak" and kind == "birthday" for name, kind in kinds)


def test_birthday_validation(anna):
    assert anna.patch("/api/profile", json={"birthday_day": 31, "birthday_month": 2}).status_code == 422
    assert anna.patch("/api/profile", json={"birthday_day": 5}).status_code == 422
    ok = anna.patch("/api/profile", json={"birthday_day": 29, "birthday_month": 2, "show_birthday": True}).json()
    assert (ok["birthday_day"], ok["birthday_month"], ok["show_birthday"]) == (29, 2, True)
    cleared = anna.patch("/api/profile", json={"birthday_day": None, "birthday_month": None}).json()
    assert cleared["birthday_day"] is None


def test_calendar_and_ical(anna):
    month = date.today().strftime("%Y-%m")
    cal = anna.get(f"/api/team/calendar?month={month}").json()
    assert any(a["person"]["full_name"] == "Sara Novak" for a in cal["absences"])
    finance = anna.get(f"/api/team/calendar?month={month}&department=Finance").json()
    assert {a["person"]["department"] for a in finance["absences"]} == {"Finance"}
    assert anna.get("/api/team/calendar?month=2026-13").status_code == 422
    ics = anna.get(f"/api/team/calendar.ics?month={month}")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    assert ics.text.startswith("BEGIN:VCALENDAR") and "Sara Novak" in ics.text


def test_vacation_balance(anna, julia):
    balance = anna.get("/api/me/vacation").json()
    assert balance["entitlement"] == 25
    assert balance["remaining"] == balance["entitlement"] - balance["taken"] - balance["planned"]
    anna_id = _me(anna)["id"]
    assert julia.patch(f"/api/admin/users/{anna_id}", json={"vacation_days": 30}).status_code == 200
    assert anna.get("/api/me/vacation").json()["entitlement"] == 30


def test_activity_feed(anna):
    kinds = {i["kind"] for i in anna.get("/api/activity").json()}
    assert {"announcement", "document", "new_colleague"} <= kinds


# ---------- Desks and parking ----------


def test_desk_booking_one_per_person(lukas):
    desks = lukas.get("/api/rooms?kind=desk").json()
    assert len(desks) == 4 and all(d["kind"] == "desk" for d in desks)
    day = (date.today() + timedelta(days=7)).isoformat()
    first = {"room_id": desks[1]["id"], "day": day, "start_time": "08:00", "end_time": "12:00", "title": "Desk"}
    assert lukas.post("/api/rooms/bookings", json=first).status_code == 201
    second = first | {"room_id": desks[2]["id"]}
    response = lukas.post("/api/rooms/bookings", json=second)
    assert response.status_code == 422 and response.json()["code"] == "already_booked_kind"
    afternoon = second | {"start_time": "12:00", "end_time": "17:00"}
    assert lukas.post("/api/rooms/bookings", json=afternoon).status_code == 201


# ---------- Personal documents ----------


def test_personal_documents_are_private(anna, lukas, julia):
    mine = anna.get("/api/personal-documents").json()
    assert len(mine) == 1
    doc_id = mine[0]["id"]
    assert lukas.get(f"/api/personal-documents/{doc_id}/download").status_code == 404
    assert anna.get("/api/me/summary").json()["personal_documents_new"] == 1
    assert anna.get(f"/api/personal-documents/{doc_id}/download").status_code == 200
    assert anna.get("/api/me/summary").json()["personal_documents_new"] == 0
    # Lukas cannot list Anna's documents by passing her id
    assert lukas.get(f"/api/personal-documents?person_id={_me(anna)['id']}").json() == []


def test_hr_uploads_personal_document_and_person_is_notified(julia, lukas):
    lukas_id = _me(lukas)["id"]
    response = julia.post(
        "/api/personal-documents",
        data={"person_id": str(lukas_id), "title": "Arbeitszeugnis"},
        files={"file": ("zeugnis.txt", b"Hallo", "text/plain")},
    )
    assert response.status_code == 201, response.text
    assert lukas.get("/api/notifications").json()["items"][0]["kind"] == "personal_document"
    assert lukas.post(
        "/api/personal-documents", data={"person_id": str(lukas_id), "title": "x"}, files={"file": ("a.txt", b"x", "text/plain")}
    ).status_code == 403


# ---------- Help ----------


def test_help_articles_and_feedback(anna, julia):
    articles = anna.get("/api/help").json()
    assert len(articles) == 5
    assert anna.get("/api/help?q=passwor").json()[0]["section"] == "general"
    first = articles[0]
    updated = anna.post(f"/api/help/{first['id']}/feedback", json={"helpful": False}).json()
    assert updated["helpful_no"] == first["helpful_no"] + 1
    body = {"section": "rooms", "question": "Neu?", "answer": "Ja.", "active": False}
    assert anna.post("/api/help", json=body).status_code == 403
    created = julia.post("/api/help", json=body).json()
    assert all(a["id"] != created["id"] for a in anna.get("/api/help").json())
    assert any(a["id"] == created["id"] for a in julia.get("/api/help?include_inactive=true").json())


def test_unauthenticated_v2():
    client = make_client()
    for path in ("/api/team/away", "/api/me/vacation", "/api/activity", "/api/help", "/api/personal-documents"):
        assert client.get(path).status_code == 401
