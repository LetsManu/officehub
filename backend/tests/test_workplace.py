from datetime import date, datetime, timedelta

from conftest import make_client


def me(client):
    return client.get("/api/auth/me").json()


# ---------- Directory, org chart, phone list ----------


def test_directory_search_and_privacy(anna, julia):
    people = anna.get("/api/directory").json()
    assert len(people) == 6
    sara = next(p for p in people if p["first_name"] == "Sara")
    assert sara["phone"] and sara["mobile"] == ""  # Sara has no mobile
    julia_entry = next(p for p in people if p["first_name"] == "Julia")
    assert julia_entry["mobile"] == ""  # hidden by Julia's setting
    assert next(p for p in julia.get("/api/directory").json() if p["first_name"] == "Julia")["mobile"]  # visible to HR / self
    assert [p["first_name"] for p in anna.get("/api/directory?q=finance").json()] == ["Sara"]
    assert anna.get("/api/directory?q=%25").json() == []
    assert "Marketing" in anna.get("/api/directory/departments").json()


def test_org_chart_manager_rules(julia):
    people = {p["first_name"]: p for p in julia.get("/api/directory").json()}
    tom, julia_id, anna = people["Tom"]["id"], people["Julia"]["id"], people["Anna"]["id"]
    assert people["Anna"]["manager_id"] == tom
    # Julia -> Anna would create a loop (Anna reports to Tom, Tom to Julia)
    assert julia.patch(f"/api/admin/users/{julia_id}", json={"manager_id": anna}).json()["code"] == "manager_cycle"
    assert julia.patch(f"/api/admin/users/{anna}", json={"manager_id": anna}).status_code == 422
    assert julia.patch(f"/api/admin/users/{anna}", json={"manager_id": None}).json()["manager_id"] is None


def test_profile_contact_fields(anna):
    data = anna.patch("/api/profile", json={"phone": "+1 555 0199", "show_mobile": False, "pinned_tiles": ["rooms", "rooms"]}).json()
    assert data["phone"] == "+1 555 0199" and data["pinned_tiles"] == ["rooms"]
    assert anna.patch("/api/profile", json={"phone": "<script>"}).status_code == 422
    assert anna.patch("/api/profile", json={"pinned_tiles": ["a", "b"]}).status_code == 422


def test_admin_password_reset(julia, tom):
    anna_id = next(p["id"] for p in julia.get("/api/directory").json() if p["first_name"] == "Anna")
    anna = make_client("anna.mayer@example.com")
    assert tom.post(f"/api/admin/users/{anna_id}/password", json={"password": "newsecret1"}).status_code == 403
    assert julia.post(f"/api/admin/users/{anna_id}/password", json={"password": "newsecret1"}).status_code == 204
    assert anna.get("/api/auth/me").status_code == 401  # signed out everywhere
    client = make_client()
    assert client.post("/api/auth/login", json={"email": "anna.mayer@example.com", "password": "newsecret1"}).status_code == 200
    assert julia.post(f"/api/admin/users/{me(julia)['id']}/password", json={"password": "newsecret1"}).status_code == 409


# ---------- Rooms ----------


def test_room_booking_rules(anna, lukas):
    room = anna.get("/api/rooms").json()[0]
    tomorrow = str(date.today() + timedelta(days=1))
    body = {"room_id": room["id"], "day": tomorrow, "start_time": "11:00", "end_time": "12:00", "title": "Planning"}
    created = anna.post("/api/rooms/bookings", json=body)
    assert created.status_code == 201, created.text
    clash = lukas.post("/api/rooms/bookings", json=body | {"start_time": "11:30", "end_time": "12:30"})
    assert clash.json()["code"] == "room_taken"
    assert lukas.post("/api/rooms/bookings", json=body | {"start_time": "12:00", "end_time": "12:30"}).status_code == 201  # back-to-back is fine
    assert anna.post("/api/rooms/bookings", json=body | {"start_time": "13:00", "end_time": "12:00"}).json()["code"] == "end_before_start_time"
    assert anna.post("/api/rooms/bookings", json=body | {"start_time": "13:10", "end_time": "14:00"}).json()["code"] == "time_step"
    assert anna.post("/api/rooms/bookings", json=body | {"day": str(date.today() - timedelta(days=1))}).json()["code"] == "day_past"
    booking_id = created.json()["id"]
    assert lukas.delete(f"/api/rooms/bookings/{booking_id}").status_code == 403
    assert anna.delete(f"/api/rooms/bookings/{booking_id}").status_code == 204


def test_only_admin_manages_rooms(tom, julia):
    assert tom.post("/api/rooms", json={"name": "Lab"}).status_code == 403
    assert julia.post("/api/rooms", json={"name": "Lab", "seats": 6}).status_code == 201


# ---------- Visitors ----------


def test_visitor_flow(anna, tom):
    created = anna.post("/api/visitors", json={"name": "Guest Person", "visit_date": str(date.today()), "expected_time": "15:00"}).json()
    assert created["status"] == "expected" and created["can_cancel"] and not created["can_check_in"]
    assert anna.get("/api/visitors?scope=day").status_code == 403
    today = tom.get("/api/visitors?scope=day").json()
    assert created["id"] in [v["id"] for v in today]
    assert tom.post(f"/api/visitors/{created['id']}/status", json={"action": "check_out"}).status_code == 409
    assert tom.post(f"/api/visitors/{created['id']}/status", json={"action": "check_in"}).json()["status"] == "checked_in"
    assert anna.post(f"/api/visitors/{created['id']}/status", json={"action": "cancel"}).status_code == 403
    assert tom.post(f"/api/visitors/{created['id']}/status", json={"action": "check_out"}).json()["status"] == "checked_out"


# ---------- Appointment requests ----------


def future(days: int, hour: str = "10:00") -> str:
    return f"{date.today() + timedelta(days=days)}T{hour}"


def test_appointment_request(anna, julia):
    body = {"type": "appointment", "title": "Talk", "category": "it", "proposed_times": [future(3), future(4, "14:30")], "submit": True}
    created = anna.post("/api/requests", json=body)
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    assert created.json()["proposed_times"] == [future(3), future(4, "14:30")]
    assert anna.post("/api/requests", json=body | {"proposed_times": []}).json()["code"] == "times_required"
    assert anna.post("/api/requests", json=body | {"proposed_times": ["2020-01-01T10:00"]}).json()["code"] == "time_past"
    assert anna.post("/api/requests", json=body | {"category": "x"}).json()["code"] == "topic_required"
    assert julia.post(f"/api/requests/{request_id}/approve", json={}).json()["code"] == "time_choose"
    approved = julia.post(f"/api/requests/{request_id}/approve", json={"chosen_time": future(4, "14:30")}).json()
    assert approved["status"] == "approved" and approved["confirmed_time"] == future(4, "14:30")


# ---------- Reviews ----------


def test_review_privacy_and_flow(julia, tom):
    anna = make_client("anna.mayer@example.com")
    lukas = make_client("lukas.schmid@example.com")
    review = next(r for r in anna.get("/api/reviews").json() if r["status"] == "preparation")
    assert review["my_side"] == "employee"
    # Tom has not finished his preparation, so he cannot see Anna's answers yet
    tom_view = tom.get(f"/api/reviews/{review['id']}").json()
    assert tom_view["employee_prep"] is None and tom_view["reviewer_prep"] == {}
    assert lukas.get(f"/api/reviews/{review['id']}").status_code == 404
    tom.put(f"/api/reviews/{review['id']}/prep", json={"answers": {"strengths": "Reliable", "ignored": "x"}, "done": True})
    tom_view = tom.get(f"/api/reviews/{review['id']}").json()
    assert tom_view["employee_prep"]["achievements"]
    assert "ignored" not in tom_view["reviewer_prep"]
    assert anna.post(f"/api/reviews/{review['id']}/confirm").json()["code"] == "goals_missing"
    assert anna.patch(f"/api/reviews/{review['id']}", json={"goals": "x"}).status_code == 403
    tom.patch(f"/api/reviews/{review['id']}", json={"goals": "1. Learn data analysis"})
    anna.post(f"/api/reviews/{review['id']}/confirm")
    done = tom.post(f"/api/reviews/{review['id']}/confirm").json()
    assert done["status"] == "completed"
    assert tom.put(f"/api/reviews/{review['id']}/prep", json={"answers": {}}).status_code == 409
    # HR sees everything and can start new reviews
    assert len(julia.get("/api/reviews").json()) == 2
    assert tom.post("/api/reviews", json={"employee_id": 1, "reviewer_id": 4, "year": 2030}).status_code == 403
    assert julia.post("/api/reviews", json={"employee_id": 1, "reviewer_id": 4, "year": 2030}).status_code == 201
    assert julia.post("/api/reviews", json={"employee_id": 1, "reviewer_id": 4, "year": 2030}).status_code == 409


# ---------- Onboarding ----------


def test_onboarding_permissions(julia, tom, anna):
    max_client = make_client("max.gruber@example.com")
    max_id = me(max_client)["id"]
    checklist = max_client.get(f"/api/onboarding/{max_id}").json()
    assert checklist["total"] == 8 and checklist["done"] == 3
    assert not any(t["can_toggle"] for t in checklist["tasks"])
    assert anna.get(f"/api/onboarding/{max_id}").status_code == 404
    tom_view = tom.get(f"/api/onboarding/{max_id}").json()
    manager_task = next(t for t in tom_view["tasks"] if t["owner"] == "manager")
    it_task = next(t for t in tom_view["tasks"] if t["owner"] == "it" and not t["done"])
    assert manager_task["can_toggle"] and not it_task["can_toggle"]
    assert tom.patch(f"/api/onboarding/tasks/{manager_task['id']}", json={"done": True}).json()["done"] == 4
    assert tom.patch(f"/api/onboarding/tasks/{it_task['id']}", json={"done": True}).status_code == 403
    assert julia.patch(f"/api/onboarding/tasks/{it_task['id']}", json={"done": True}).json()["done"] == 5
    added = julia.post(f"/api/onboarding/{max_id}/tasks", json={"title": "Parking card", "owner": "hr"}).json()
    assert added["total"] == 9
    assert [s["person"]["id"] for s in tom.get("/api/onboarding").json()] == [max_id]


def test_new_person_gets_checklist(julia):
    body = {"email": "new.colleague@example.com", "first_name": "New", "last_name": "Colleague", "password": "welcome123"}
    person = julia.post("/api/admin/users", json=body).json()
    assert julia.get(f"/api/onboarding/{person['id']}").json()["total"] == 8


# ---------- Quick links, settings, reports ----------


def test_quick_links(anna, julia):
    assert len(anna.get("/api/portal/links").json()) == 4
    assert julia.post("/api/portal/links", json={"title": "Bad", "url": "javascript:alert(1)"}).status_code == 422
    assert anna.post("/api/portal/links", json={"title": "x", "url": "https://x.example.com"}).status_code == 403
    link = julia.post("/api/portal/links", json={"title": "Wiki", "url": "https://wiki2.example.com", "icon": "evil"}).json()
    assert link["icon"] == "link"
    assert julia.delete(f"/api/portal/links/{link['id']}").status_code == 204


def test_portal_settings(anna, julia):
    settings = anna.get("/api/portal/settings").json()
    assert "rooms" in settings["dashboard_tiles"]
    assert settings["section_contacts"]["requests"]["full_name"] == "Julia Weber"
    assert anna.put("/api/portal/settings", json={"dashboard_tiles": ["vacation"]}).status_code == 403
    updated = julia.put("/api/portal/settings", json={"dashboard_tiles": ["visitors", "vacation"], "section_contacts": {"requests": None, "unknown": 1}}).json()
    assert updated["dashboard_tiles"] == ["visitors", "vacation"]
    assert "requests" not in updated["section_contacts"] and "unknown" not in updated["section_contacts"]
    assert julia.put("/api/portal/settings", json={"dashboard_tiles": ["nope"]}).status_code == 422


def test_reports(anna, tom):
    assert anna.get("/api/reports/overdue").status_code == 403
    expenses = tom.get("/api/reports/expenses").json()
    assert expenses["rows"] == [["meals", "EUR", 1, "86.40"]]
    overdue = tom.get("/api/reports/overdue?days=3").json()
    assert [row[2] for row in overdue["rows"]] == ["equipment"]  # the 4-day-old laptop request
    assert tom.get("/api/reports/absences?month=2026-13").status_code == 422
    csv_text = tom.get("/api/reports/expenses?format=csv").text
    assert csv_text.splitlines()[0].endswith("category;currency;count;total")


def test_add_missing_columns_upgrades_old_database(tmp_path):
    """An older database without the new columns gets them on startup."""
    import sqlalchemy as sa

    from app import db as db_module

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(254))")
    original = db_module.engine
    db_module.engine = engine
    try:
        db_module.add_missing_columns()
    finally:
        db_module.engine = original
    columns = {c["name"] for c in sa.inspect(engine).get_columns("users")}
    assert {"phone", "show_mobile", "manager_id", "pinned_tiles"} <= columns
