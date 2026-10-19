from datetime import date, timedelta

from app.routers.time_tracking import local_today
from conftest import make_client


def _last_weekday(before: date) -> date:
    day = before - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def test_clock_in_and_out(sara):
    status = sara.get("/api/time/status").json()
    assert status["running"] is None
    running = sara.post("/api/time/clock-in", json={}).json()["running"]
    assert running and running["end_at"] is None
    assert sara.post("/api/time/clock-in", json={}).json()["code"] == "already_clocked_in"
    done = sara.post("/api/time/clock-out").json()
    assert done["running"] is None
    assert sara.post("/api/time/clock-out").json()["code"] == "not_clocked_in"


def test_manual_entries_week_and_rules(sara):
    day = _last_weekday(local_today())
    first = sara.post("/api/time/entries", json={"day": str(day), "start": "08:00", "end": "12:00"})
    assert first.status_code == 201 and first.json()["minutes"] == 240 and first.json()["edited"] is True
    overlap = sara.post("/api/time/entries", json={"day": str(day), "start": "11:30", "end": "13:00"})
    assert overlap.json()["code"] == "time_overlap"
    # 8 hours without a break triggers a hint
    sara.post("/api/time/entries", json={"day": str(day), "start": "12:00", "end": "16:30"})
    week = sara.get(f"/api/time/week?start={day}").json()
    row = next(d for d in week["days"] if d["date"] == str(day))
    assert row["worked"] == 510 and row["target"] in (0, 480)
    if row["target"]:
        assert "break_short" in row["warnings"]
    future = sara.post("/api/time/entries", json={"day": str(local_today() + timedelta(days=1)), "start": "08:00", "end": "09:00"})
    assert future.json()["code"] == "day_future"
    old = sara.post("/api/time/entries", json={"day": str(local_today() - timedelta(days=40)), "start": "08:00", "end": "09:00"})
    assert old.json()["code"] == "time_locked"
    bad = sara.post("/api/time/entries", json={"day": str(day), "start": "18:00", "end": "17:00"})
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


def test_export_csv(sara):
    day = _last_weekday(local_today())
    sara.post("/api/time/entries", json={"day": str(day), "start": "09:00", "end": "10:00", "note": "=SUM(A1)"})
    response = sara.get(f"/api/time/export.csv?month={day:%Y-%m}")
    assert response.status_code == 200 and "'=SUM(A1)" in response.text
    assert make_client().get(f"/api/time/export.csv?month={day:%Y-%m}").status_code == 401


def test_balance_starts_with_first_recorded_day(sara):
    assert sara.get("/api/time/status").json()["balance_year"] == 0
    day = _last_weekday(local_today())
    sara.post("/api/time/entries", json={"day": str(day), "start": "08:00", "end": "17:00"})
    balance = sara.get(f"/api/time/week?start={day}").json()["balance_year"]
    # Only the days since the first entry count, not every day since 1 January
    assert abs(balance) < 5 * 8 * 60


def _prev_month() -> str:
    first = local_today().replace(day=1)
    return f"{first - timedelta(days=1):%Y-%m}"


def test_month_overview(anna):
    month = anna.get("/api/time/month").json()
    assert month["status"] == "open" and month["can_submit"] is True and month["can_decide"] is False
    assert len(month["days"]) >= 28 and month["vacation"]["entitlement"] > 0
    assert anna.get("/api/time/month?month=2026-13").status_code == 422


def test_hand_in_approve_and_send_back(sara, tom, anna, julia):
    month = _prev_month()
    day = date.fromisoformat(f"{month}-15")
    assert sara.post(f"/api/time/months/{month}/submit").json()["status"] == "submitted"
    # handed in: Sara can no longer change that month, HR can
    late = sara.post("/api/time/entries", json={"day": str(day), "start": "09:00", "end": "10:00"})
    assert late.status_code in (409, 422)
    assert sara.post(f"/api/time/months/{month}/submit").status_code == 409

    sara_id = sara.get("/api/time/month").json()["person"]["id"]
    assert [p["month"] for p in tom.get("/api/time/months/pending").json()] == [month]
    assert tom.get("/api/me/summary").json()["time_months_pending"] == 1
    # only the manager (or HR) decides, never the person themself or a colleague
    assert anna.post(f"/api/time/months/{month}/approve", json={"person_id": sara_id}).status_code == 403
    assert sara.post(f"/api/time/months/{month}/approve", json={"person_id": sara_id}).status_code == 403
    view = tom.get(f"/api/time/month?month={month}&person_id={sara_id}").json()
    assert view["can_decide"] is True

    missing = tom.post(f"/api/time/months/{month}/return", json={"person_id": sara_id})
    assert missing.status_code == 422 and missing.json()["field"] == "comment"
    back = tom.post(f"/api/time/months/{month}/return", json={"person_id": sara_id, "comment": "Bitte 15. ergänzen"})
    assert back.json()["status"] == "returned"
    kinds = [n["kind"] for n in sara.get("/api/notifications").json()["items"]]
    assert "time_month_returned" in kinds

    assert sara.post(f"/api/time/months/{month}/submit").json()["status"] == "submitted"
    done = julia.post(f"/api/time/months/{month}/approve", json={"person_id": sara_id}).json()
    assert done["status"] == "approved" and done["decided_by"] == "Julia Weber"


def test_future_month_cannot_be_handed_in(sara):
    first = local_today().replace(day=28) + timedelta(days=10)
    assert sara.post(f"/api/time/months/{first:%Y-%m}/submit").status_code == 409


def test_pending_and_home_office_days(anna):
    days = anna.get("/api/time/month").json()["days"]
    assert all("pending" in d and "home_office" in d for d in days)
