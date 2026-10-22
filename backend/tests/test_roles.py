"""Roles: employee, team lead, manager, HR, service desk and admin (several per person)."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from conftest import make_client
from test_requests import vacation


def _set(email: str, roles: list[str], manager_email: str | None = None) -> int:
    with SessionLocal() as db:
        person = db.scalar(select(User).where(User.email == email))
        person.set_roles(roles)
        if manager_email:
            person.manager_id = db.scalar(select(User.id).where(User.email == manager_email))
        db.commit()
        return person.id


def _it_request():
    return {"type": "it_access", "title": "CRM access", "item": "CRM", "access_level": "view", "submit": True}


def test_old_admin_role_means_admin_and_hr():
    with SessionLocal() as db:
        julia = db.scalar(select(User).where(User.email == "julia.weber@example.com"))
        assert julia.role == "admin" and julia.roles == ["admin", "hr"]
        assert julia.is_admin and julia.is_hr and julia.is_servicedesk


def test_team_lead_sees_and_decides_only_own_team(anna, lukas):
    _set("sara.novak@example.com", ["teamlead"])
    _set("anna.mayer@example.com", [], manager_email="sara.novak@example.com")
    sara = make_client("sara.novak@example.com")
    own = anna.post("/api/requests", json=vacation()).json()
    other = lukas.post("/api/requests", json=vacation()).json()

    listed = {r["id"] for r in sara.get("/api/requests?scope=all").json()["items"]}
    assert own["id"] in listed and other["id"] not in listed
    assert sara.get(f"/api/requests/{other['id']}").status_code == 404
    assert sara.post(f"/api/requests/{own['id']}/approve", json={}).status_code == 200
    # Company-wide reports stay with managers and HR
    assert sara.get("/api/reports/absences").status_code == 403


def test_service_desk_handles_it_requests_only(anna):
    max_ = make_client("max.gruber@example.com")
    it = anna.post("/api/requests", json=_it_request())
    assert it.status_code == 201, it.text
    leave = anna.post("/api/requests", json=vacation()).json()

    listed = {r["id"] for r in max_.get("/api/requests?scope=all").json()["items"]}
    assert it.json()["id"] in listed and leave["id"] not in listed
    assert max_.post(f"/api/requests/{it.json()['id']}/approve", json={}).status_code == 200
    assert max_.get(f"/api/requests/{leave['id']}").status_code == 404
    # The equipment register is theirs, HR areas are not
    assert max_.get("/api/assets").status_code == 200
    assert max_.post("/api/announcements", json={"title": "x", "body": "y"}).status_code == 403


def test_service_desk_resets_passwords_but_never_an_admins(anna):
    max_ = make_client("max.gruber@example.com")
    anna_id = anna.get("/api/auth/me").json()["id"]
    assert max_.post(f"/api/admin/users/{anna_id}/password", json={"password": "a-new-password-1"}).status_code == 204
    with SessionLocal() as db:
        julia_id = db.scalar(select(User.id).where(User.email == "julia.weber@example.com"))
    assert max_.post(f"/api/admin/users/{julia_id}/password", json={"password": "a-new-password-1"}).status_code == 403
    assert max_.patch(f"/api/admin/users/{anna_id}", json={"department": "IT"}).status_code == 403


def test_hr_gives_roles_but_not_admin(julia, anna):
    _set("sara.novak@example.com", ["hr"])
    sara = make_client("sara.novak@example.com")
    anna_id = anna.get("/api/auth/me").json()["id"]

    changed = sara.patch(f"/api/admin/users/{anna_id}", json={"roles": ["teamlead", "servicedesk"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["roles"] == ["servicedesk", "teamlead"] and changed.json()["role"] == "servicedesk"
    assert sara.patch(f"/api/admin/users/{anna_id}", json={"roles": ["admin"]}).status_code == 403
    # HR keeps their own HR access
    sara_id = sara.get("/api/auth/me").json()["id"]
    assert sara.patch(f"/api/admin/users/{sara_id}", json={"roles": []}).json()["code"] == "self_lockout"
    # Only an administrator makes administrators, and the system settings stay theirs
    assert julia.patch(f"/api/admin/users/{anna_id}", json={"roles": ["admin"]}).status_code == 200
    assert sara.get("/api/admin/backups").status_code == 403


def test_legacy_single_role_still_accepted(julia, anna):
    anna_id = anna.get("/api/auth/me").json()["id"]
    response = julia.patch(f"/api/admin/users/{anna_id}", json={"role": "manager"})
    assert response.status_code == 200 and response.json()["roles"] == ["manager"]


def test_pending_count_follows_what_people_decide(anna):
    max_ = make_client("max.gruber@example.com")
    before = max_.get("/api/me/summary").json()["approvals_pending"]
    anna.post("/api/requests", json=vacation())
    assert max_.get("/api/me/summary").json()["approvals_pending"] == before
    anna.post("/api/requests", json=_it_request())
    assert max_.get("/api/me/summary").json()["approvals_pending"] == before + 1
