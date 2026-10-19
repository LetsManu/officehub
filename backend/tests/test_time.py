from datetime import date, timedelta

from app.routers.time_tracking import local_today
from conftest import make_client


def _last_weekday(before: date) -> date:
    day = before - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def test_clock_in_and_out(anna):
    status = anna.get("/api/time/status").json()
    assert status["running"] is None
    running = anna.post("/api/time/clock-in", json={}).json()["running"]
    assert running and running["end_at"] is None
    assert anna.post("/api/time/clock-in", json={}).json()["code"] == "already_clocked_in"
    done = anna.post("/api/time/clock-out").json()
    assert done["running"] is None
    assert anna.post("/api/time/clock-out").json()["code"] == "not_clocked_in"


def test_manual_entries_week_and_rules(anna):
    day = _last_weekday(local_today())
    first = anna.post("/api/time/entries", json={"day": str(day), "start": "08:00", "end": "12:00"})
    assert first.status_code == 201 and first.json()["minutes"] == 240 and first.json()["edited"] is True
    overlap = anna.post("/api/time/entries", json={"day": str(day), "start": "11:30", "end": "13:00"})
    assert overlap.json()["code"] == "time_overlap"
    # 8 hours without a break triggers a hint
    anna.post("/api/time/entries", json={"day": str(day), "start": "12:00", "end": "16:30"})
    week = anna.get(f"/api/time/week?start={day}").json()
    row = next(d for d in week["days"] if d["date"] == str(day))
    assert row["worked"] == 510 and row["target"] in (0, 480)
    if row["target"]:
        assert "break_short" in row["warnings"]
    future = anna.post("/api/time/entries", json={"day": str(local_today() + timedelta(days=1)), "start": "08:00", "end": "09:00"})
    assert future.json()["code"] == "day_future"
    old = anna.post("/api/time/entries", json={"day": str(local_today() - timedelta(days=40)), "start": "08:00", "end": "09:00"})
    assert old.json()["code"] == "time_locked"
    bad = anna.post("/api/time/entries", json={"day": str(day), "start": "18:00", "end": "17:00"})
    assert bad.json()["code"] == "end_before_start_time"


def test_edit_and_delete_own_only(anna, lukas):
    day = _last_weekday(local_today())
    entry = anna.post("/api/time/entries", json={"day": str(day), "start": "07:00", "end": "07:30"}).json()
    assert lukas.put(f"/api/time/entries/{entry['id']}", json={"start": "07:00", "end": "08:00"}).status_code == 404
    assert anna.put(f"/api/time/entries/{entry['id']}", json={"start": "07:00", "end": "08:00"}).json()["minutes"] == 60
    assert lukas.delete(f"/api/time/entries/{entry['id']}").status_code == 404
    assert anna.delete(f"/api/time/entries/{entry['id']}").status_code == 204


def test_holidays_and_vacation_have_no_target(anna, julia):
    julia.put("/api/holidays/config", json={"country": "AT", "region": ""})
    year = local_today().year
    week = anna.get(f"/api/time/week?start={year}-12-21").json()
    christmas = next(d for d in week["days"] if d["date"] == f"{year}-12-25")
    assert christmas["target"] == 0 and christmas["off"].startswith("holiday:")


def test_team_view_and_privacy(tom, anna, lukas, julia):
    rows = tom.get("/api/time/team").json()
    names = {r["person"]["full_name"] for r in rows}
    assert "Anna Mayer" in names and "Julia Weber" not in names
    anna_id = next(r["person"]["id"] for r in rows if r["person"]["full_name"] == "Anna Mayer")
    assert tom.get(f"/api/time/week?person_id={anna_id}").status_code == 200
    assert lukas.get(f"/api/time/week?person_id={anna_id}").status_code == 403
    assert lukas.get("/api/time/team").status_code == 403
    assert len(julia.get("/api/time/team").json()) >= 6


def test_export_csv(anna):
    day = _last_weekday(local_today())
    anna.post("/api/time/entries", json={"day": str(day), "start": "09:00", "end": "10:00", "note": "=SUM(A1)"})
    response = anna.get(f"/api/time/export.csv?month={day:%Y-%m}")
    assert response.status_code == 200 and "'=SUM(A1)" in response.text
    assert make_client().get(f"/api/time/export.csv?month={day:%Y-%m}").status_code == 401
