from datetime import date, datetime, timedelta, timezone


def _ids(client):
    return {p["full_name"]: p["id"] for p in client.get("/api/directory").json()}


def test_my_calendar_shows_meetings_bookings_time_off_and_holidays(anna, lukas):
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    meeting = anna.post("/api/meetings", json={"title": "Kalender-Test", "starts_at": start.isoformat(),
                                               "ends_at": (start + timedelta(hours=1)).isoformat(),
                                               "invitee_ids": [_ids(anna)["Lukas Schmid"]]}).json()
    day = start.date()
    rng = f"start={day - timedelta(days=1)}&end={day + timedelta(days=6)}"
    mine = {e["id"]: e for e in lukas.get(f"/api/calendar?{rng}").json()}
    entry = mine[f"m{meeting['id']}"]
    assert entry["kind"] == "meeting" and entry["status"] == "pending" and entry["link"] == f"/meetings/{meeting['id']}"
    assert entry["start"].startswith(start.strftime("%Y-%m-%dT%H:%M"))

    # declined meetings disappear, as in Outlook
    lukas.post(f"/api/meetings/{meeting['id']}/respond", json={"response": "declined"})
    assert f"m{meeting['id']}" not in {e["id"] for e in lukas.get(f"/api/calendar?{rng}").json()}

    # a room booking shows with its room
    room = anna.get("/api/rooms").json()[0]
    booking = anna.post("/api/rooms/bookings", json={"room_id": room["id"], "day": str(day), "start_time": "10:00",
                                                     "end_time": "11:00", "title": "Raum-Test"})
    assert booking.status_code == 201, booking.text
    entries = anna.get(f"/api/calendar?{rng}").json()
    assert any(e["kind"] == "booking" and e["detail"] == room["name"] for e in entries)

    # public holidays: 25 December is one in Austria (the default)
    christmas = date(day.year, 12, 25)
    holidays = anna.get(f"/api/calendar?start={christmas}&end={christmas}").json()
    assert any(e["kind"] == "holiday" for e in holidays)
    assert anna.get(f"/api/calendar?start={day}&end={day + timedelta(days=90)}").status_code == 422


def test_recent_files_only_from_my_spaces(anna, sara):
    space = anna.post("/api/spaces", json={"name": "Dateien-Test"}).json()
    anna.post(f"/api/spaces/{space['id']}/files/new", json={"kind": "docx", "name": "Protokoll"})
    recent = anna.get("/api/spaces/files/recent").json()
    assert recent[0]["name"].startswith("Protokoll") and recent[0]["space_name"] == "Dateien-Test"
    assert "Dateien-Test" not in {f["space_name"] for f in sara.get("/api/spaces/files/recent").json()}
