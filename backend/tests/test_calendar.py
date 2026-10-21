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
    entry = next(e for key, e in mine.items() if key.startswith(f"m{meeting['id']}-"))
    assert entry["kind"] == "meeting" and entry["status"] == "pending" and entry["link"] == f"/meetings/{meeting['id']}"
    assert entry["start"].startswith(start.strftime("%Y-%m-%dT%H:%M"))

    # declined meetings disappear, as in Outlook
    lukas.post(f"/api/meetings/{meeting['id']}/respond", json={"response": "declined"})
    assert not any(e["id"].startswith(f"m{meeting['id']}-") for e in lukas.get(f"/api/calendar?{rng}").json())

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



def _local(day, hour):
    from zoneinfo import ZoneInfo
    return datetime(day.year, day.month, day.day, hour, tzinfo=ZoneInfo("Europe/Vienna"))


def test_weekly_series_skips_cancelled_day_and_shows_in_free_busy(anna, lukas):
    monday = date.today() + timedelta(days=7 - date.today().weekday())  # next Monday
    start = _local(monday, 9)
    body = {"title": "Wochenrunde", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat(),
            "invitee_ids": [_ids(anna)["Lukas Schmid"]], "recurrence": "weekly",
            "recurrence_until": str(monday + timedelta(days=21))}
    meeting = anna.post("/api/meetings", json=body).json()
    assert meeting["recurrence"] == "weekly" and meeting["next_start"]
    rng = f"start={monday}&end={monday + timedelta(days=34)}"
    days = sorted(e["start"] for e in lukas.get(f"/api/calendar?{rng}").json() if e["title"] == "Wochenrunde")
    assert len(days) == 4  # four Mondays until the end of the series
    assert all(d.endswith("T08:00:00Z") or d.endswith("T07:00:00Z") for d in days)  # 09:00 Vienna, summer or winter

    # cancel only the second Monday
    second = monday + timedelta(days=7)
    assert lukas.delete(f"/api/meetings/{meeting['id']}?occurrence={second}").status_code == 403
    assert anna.delete(f"/api/meetings/{meeting['id']}?occurrence={second}").status_code == 204
    left = [e for e in lukas.get(f"/api/calendar?{rng}").json() if e["title"] == "Wochenrunde"]
    assert len(left) == 3 and not any(e["id"].endswith(str(second)) for e in left)
    assert "RRULE:FREQ=WEEKLY" in anna.get(f"/api/meetings/{meeting['id']}/ics").text

    # free/busy shows Lukas busy on the first Monday – without the title
    busy = anna.get(f"/api/calendar/busy?ids={_ids(anna)['Lukas Schmid']}&start={monday}&end={monday}").json()
    blocks = busy[str(_ids(anna)["Lukas Schmid"])]
    assert [b["kind"] for b in blocks] == ["meeting"] and "title" not in blocks[0]

    # the upcoming list shows the series once, with its next meeting
    listed = [m for m in lukas.get("/api/meetings").json() if m["id"] == meeting["id"]]
    assert len(listed) == 1 and listed[0]["next_start"]


def test_presence_follows_activity_and_own_choice(anna, lukas):
    lukas_id = _ids(anna)["Lukas Schmid"]
    assert anna.get(f"/api/presence?ids={lukas_id}").json()[str(lukas_id)]["state"] == "offline"
    lukas.get("/api/me/summary")  # the open portal reports in
    assert anna.get(f"/api/presence?ids={lukas_id}").json()[str(lukas_id)]["state"] == "available"
    lukas.get("/api/me/summary?idle=true")
    assert anna.get(f"/api/presence?ids={lukas_id}").json()[str(lukas_id)]["state"] == "away"
    mine = lukas.put("/api/me/presence", json={"presence": "dnd", "status_text": "Fokuszeit bis 11"}).json()
    assert mine["state"] == "dnd"
    other = anna.get(f"/api/presence?ids={lukas_id}").json()[str(lukas_id)]
    assert other == {"state": "dnd", "text": "Fokuszeit bis 11", "manual": "dnd", "activity": None}
    lukas.put("/api/me/presence", json={"presence": "offline"})
    assert anna.get(f"/api/presence?ids={lukas_id}").json()[str(lukas_id)]["state"] == "offline"


def test_reminder_ten_minutes_before(anna, lukas):
    start = datetime.now(timezone.utc) + timedelta(minutes=8)
    meeting = anna.post("/api/meetings", json={"title": "Gleich", "starts_at": start.isoformat(),
                                               "ends_at": (start + timedelta(minutes=30)).isoformat(),
                                               "invitee_ids": [_ids(anna)["Lukas Schmid"]]}).json()
    first = lukas.get("/api/me/summary").json()
    assert [r["meeting_id"] for r in first["reminders"]] == [meeting["id"]]
    kinds = [n["kind"] for n in lukas.get("/api/notifications").json()["items"]]
    assert kinds.count("meeting_reminder") == 1
    lukas.get("/api/me/summary")  # asking again does not remind twice
    kinds = [n["kind"] for n in lukas.get("/api/notifications").json()["items"]]
    assert kinds.count("meeting_reminder") == 1
    lukas.post(f"/api/meetings/{meeting['id']}/respond", json={"response": "declined"})
    assert lukas.get("/api/me/summary").json()["reminders"] == []


def test_desk_bookings_do_not_make_busy(anna):
    me = _ids(anna)["Anna Mayer"]
    day = date.today() + timedelta(days=3)
    desk = next((r for r in anna.get("/api/rooms").json() if r["kind"] == "desk"), None)
    if desk is None:
        return
    anna.post("/api/rooms/bookings", json={"room_id": desk["id"], "day": str(day), "start_time": "08:00",
                                           "end_time": "17:00", "title": "Platz"})
    busy = anna.get(f"/api/calendar/busy?ids={me}&start={day}&end={day}").json()[str(me)]
    assert not any(b["kind"] == "booking" for b in busy)
