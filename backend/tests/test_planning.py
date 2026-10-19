from datetime import date, timedelta

from app.routers.time_tracking import local_today


def _monday(offset_weeks: int = 0) -> date:
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=offset_weeks)


def _person_id(client, email_name: str, people) -> int:
    return next(p["id"] for p in people if p["full_name"] == email_name)


def _people(client):
    return client.get("/api/directory").json()


def _new_project(client, **fields):
    body = {"name": "Testprojekt", "color": "blue", "budget_hours": 40, **fields}
    return client.post("/api/planning/projects", json=body)


def test_only_managers_create_projects(anna, tom):
    assert _new_project(anna).status_code == 403
    response = _new_project(tom)
    assert response.status_code == 201
    assert response.json()["budget_minutes"] == 40 * 60
    bad = _new_project(tom, color="neon")
    assert bad.status_code == 422 and bad.json()["field"] == "color"
    bad = _new_project(tom, start_date="2026-05-10", end_date="2026-05-01")
    assert bad.status_code == 422 and bad.json()["code"] == "end_before_start"


def test_manager_plans_own_team_only(anna, tom, julia):
    people = _people(tom)
    project = _new_project(tom).json()
    anna_id = _person_id(tom, "Anna Mayer", people)
    julia_id = _person_id(tom, "Julia Weber", people)
    body = {"project_id": project["id"], "user_id": anna_id, "start_date": str(_monday(1)),
            "end_date": str(_monday(1) + timedelta(days=4)), "minutes_per_day": 240}
    assert tom.post("/api/planning/allocations", json=body).status_code == 201
    assert tom.post("/api/planning/allocations", json={**body, "user_id": julia_id}).status_code == 403
    assert anna.post("/api/planning/allocations", json=body).status_code == 403
    assert julia.post("/api/planning/allocations", json={**body, "user_id": julia_id}).status_code == 201
    kinds = [n["kind"] for n in anna.get("/api/notifications").json()["items"]]
    assert "planned" in kinds
    bad = tom.post("/api/planning/allocations", json={**body, "minutes_per_day": 5})
    assert bad.status_code == 422


def test_board_shows_own_row_to_employees_and_team_to_managers(anna, tom, julia):
    start = str(_monday())
    mine = anna.get(f"/api/planning/board?start={start}&days=14").json()
    assert [r["person"]["full_name"] for r in mine["rows"]] == ["Anna Mayer"]
    assert mine["can_plan"] is False and mine["rows"][0]["editable"] is False
    team = tom.get(f"/api/planning/board?start={start}&days=14").json()
    names = {r["person"]["full_name"] for r in team["rows"]}
    assert {"Anna Mayer", "Lukas Schmid", "Tom Huber"} <= names and "Julia Weber" not in names
    assert len(julia.get(f"/api/planning/board?start={start}&days=14").json()["rows"]) >= 6
    assert len(team["days"]) == 14 and team["days"][5]["off"] == "weekend"
    assert anna.get(f"/api/planning/board?start={start}&days=200").status_code == 422


def test_planned_hours_skip_weekends_holidays_and_vacation(tom, sara):
    people = _people(tom)
    sara_id = _person_id(tom, "Sara Novak", people)
    project = _new_project(tom).json()
    start = _monday(10)
    tom.post("/api/planning/allocations", json={
        "project_id": project["id"], "user_id": sara_id, "start_date": str(start),
        "end_date": str(start + timedelta(days=6)), "minutes_per_day": 240,
    })
    board = tom.get(f"/api/planning/board?start={start}&days=7").json()
    row = next(r for r in board["rows"] if r["person"]["id"] == sara_id)
    working_days = row["capacity"] // 480
    assert 0 < working_days <= 5
    assert row["planned"] >= 240 * working_days  # the demo plan may add more


def test_booking_time_on_projects(anna, tom, julia):
    project = _new_project(tom).json()
    day = local_today() - timedelta(days=1)
    entry = anna.post("/api/time/entries", json={"day": str(day), "start": "06:00", "end": "07:00",
                                                 "project_id": project["id"]})
    assert entry.status_code == 201 and entry.json()["project_name"] == "Testprojekt"
    report = tom.get(f"/api/planning/projects/{project['id']}").json()
    assert report["project"]["booked_minutes"] == 60
    assert report["rows"][0]["booked"] == 60
    assert anna.get(f"/api/planning/projects/{project['id']}").status_code == 403

    # Finished projects can no longer be booked, and booked projects cannot be deleted
    tom.put(f"/api/planning/projects/{project['id']}", json={"name": "Testprojekt", "color": "blue", "active": False})
    late = anna.post("/api/time/entries", json={"day": str(day), "start": "05:00", "end": "05:30",
                                                "project_id": project["id"]})
    assert late.status_code == 422 and late.json()["code"] == "project_inactive"
    assert tom.delete(f"/api/planning/projects/{project['id']}").status_code == 409
    assert project["id"] not in [p["id"] for p in anna.get("/api/planning/projects").json()]

    unused = _new_project(julia, name="Leer").json()
    assert julia.delete(f"/api/planning/projects/{unused['id']}").status_code == 204


def test_my_plan(anna):
    plan = anna.get(f"/api/planning/mine?start={_monday()}&end={_monday() + timedelta(days=6)}").json()
    assert plan and all(p["project"]["name"] for p in plan)
