from datetime import date, timedelta

from conftest import make_client


def next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) or 7)


def vacation(**overrides):
    start = next_monday()
    body = {"type": "vacation", "title": "Vacation", "start_date": str(start), "end_date": str(start + timedelta(days=4)), "submit": True}
    body.update(overrides)
    return body


def test_vacation_counts_working_days(anna):
    response = anna.post("/api/requests", json=vacation())
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["working_days"] == 5
    assert data["status"] == "submitted"


def test_vacation_end_before_start(anna):
    start = next_monday()
    response = anna.post("/api/requests", json=vacation(end_date=str(start - timedelta(days=1))))
    assert response.status_code == 422
    assert response.json()["code"] == "end_before_start"
    assert response.json()["field"] == "end_date"


def test_vacation_missing_start(anna):
    response = anna.post("/api/requests", json=vacation(start_date=None))
    assert response.json()["code"] == "start_required"


def test_expense_validation(anna):
    body = {"type": "expense", "title": "Taxi", "amount": "23.50", "currency": "EUR", "category": "travel", "start_date": str(date.today())}
    response = anna.post("/api/requests", json=body)
    assert response.status_code == 201
    assert response.json()["amount"] == "23.50"
    future = body | {"start_date": str(date.today() + timedelta(days=3))}
    assert anna.post("/api/requests", json=future).json()["code"] == "expense_date_future"
    assert anna.post("/api/requests", json=body | {"amount": "-5"}).status_code == 422


def test_equipment_parking_category(anna):
    body = {"type": "equipment", "title": "Parkplatz", "item": "Parking space", "category": "parking"}
    response = anna.post("/api/requests", json=body)
    assert response.status_code == 201
    assert response.json()["category"] == "parking"
    unknown = anna.post("/api/requests", json=body | {"category": "boat"})
    assert unknown.json()["code"] == "category_required"


def test_irrelevant_fields_are_dropped(anna):
    body = {"type": "general", "title": "Parking", "description": "Need a parking spot", "amount": "10", "currency": "EUR"}
    data = anna.post("/api/requests", json=body).json()
    assert data["amount"] is None and data["currency"] is None


def test_employee_sees_only_own_requests(anna, lukas):
    created = anna.post("/api/requests", json=vacation()).json()
    assert lukas.get(f"/api/requests/{created['id']}").status_code == 404
    ids = [r["id"] for r in lukas.get("/api/requests").json()["items"]]
    assert created["id"] not in ids
    assert lukas.get("/api/requests?scope=all").status_code == 403


def test_approval_flow(anna, tom):
    created = anna.post("/api/requests", json=vacation()).json()
    assert created["permissions"]["can_cancel"]
    assert anna.post(f"/api/requests/{created['id']}/approve").status_code == 403

    pending = tom.get("/api/requests?scope=all&status=submitted,in_review").json()["items"]
    assert created["id"] in [r["id"] for r in pending]

    detail = tom.patch(f"/api/requests/{created['id']}", json={"status": "in_review"}).json()
    assert detail["status"] == "in_review"
    detail = tom.post(f"/api/requests/{created['id']}/approve", json={"comment": "Enjoy!"}).json()
    assert detail["status"] == "approved"
    assert detail["decision_comment"] == "Enjoy!"
    assert detail["decided_by"]["full_name"] == "Tom Huber"

    # A decided request cannot be decided again or cancelled.
    assert tom.post(f"/api/requests/{created['id']}/reject").status_code == 409
    assert anna.patch(f"/api/requests/{created['id']}", json={"status": "cancelled"}).status_code == 409


def test_reject_with_comment(anna, julia):
    created = anna.post("/api/requests", json=vacation()).json()
    detail = julia.post(f"/api/requests/{created['id']}/reject", json={"comment": "Team is fully booked."}).json()
    assert detail["status"] == "rejected"


def test_manager_cannot_approve_own_request(tom, julia):
    created = tom.post("/api/requests", json=vacation()).json()
    assert tom.post(f"/api/requests/{created['id']}/approve").status_code == 403
    assert julia.post(f"/api/requests/{created['id']}/approve").json()["status"] == "approved"


def test_drafts_are_private_and_editable(anna, tom):
    draft = anna.post("/api/requests", json=vacation(submit=False)).json()
    assert draft["status"] == "draft"
    assert tom.get(f"/api/requests/{draft['id']}").status_code == 404
    updated = anna.patch(f"/api/requests/{draft['id']}", json={"title": "Autumn break"}).json()
    assert updated["title"] == "Autumn break"
    submitted = anna.patch(f"/api/requests/{draft['id']}", json={"status": "submitted"}).json()
    assert submitted["status"] == "submitted"
    assert anna.patch(f"/api/requests/{draft['id']}", json={"title": "Changed"}).status_code == 409


def test_cancel_pending(anna):
    created = anna.post("/api/requests", json=vacation()).json()
    assert anna.patch(f"/api/requests/{created['id']}", json={"status": "cancelled"}).json()["status"] == "cancelled"


def test_comments(anna, tom):
    created = anna.post("/api/requests", json=vacation()).json()
    detail = tom.post(f"/api/requests/{created['id']}/comments", json={"body": "<b>Looks good</b>"}).json()
    assert detail["comments"][0]["body"] == "<b>Looks good</b>"  # stored as text, escaped by the frontend
    assert anna.post(f"/api/requests/{created['id']}/comments", json={"body": "   "}).status_code == 422


def test_receipt_upload(anna):
    body = {"type": "expense", "title": "Taxi", "amount": "23.50", "currency": "EUR", "category": "travel", "start_date": str(date.today()), "submit": True}
    created = anna.post("/api/requests", json=body).json()
    bad = anna.post(f"/api/requests/{created['id']}/attachment", files={"file": ("receipt.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 422
    fake_pdf = anna.post(f"/api/requests/{created['id']}/attachment", files={"file": ("receipt.pdf", b"hello", "application/pdf")})
    assert fake_pdf.json()["code"] == "file_invalid"
    ok = anna.post(f"/api/requests/{created['id']}/attachment", files={"file": ("receipt.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert ok.status_code == 200
    assert ok.json()["attachment_name"] == "receipt.pdf"
    assert anna.get(f"/api/requests/{created['id']}/attachment").status_code == 200


def test_filters(tom):
    items = tom.get("/api/requests?scope=all&type=equipment").json()["items"]
    assert items and all(r["type"] == "equipment" for r in items)
    assert tom.get("/api/requests?scope=all&status=unknown").status_code == 422


def test_demo_data_has_all_statuses(tom, julia):
    statuses = {r["status"] for r in tom.get("/api/requests?scope=all").json()["items"]}
    assert {"submitted", "in_review", "approved", "rejected"} <= statuses
    sara = make_client("sara.novak@example.com")
    assert "draft" in {r["status"] for r in sara.get("/api/requests").json()["items"]}


def test_timestamps_are_valid_iso(anna):
    created = anna.post("/api/requests", json=vacation()).json()
    for value in (created["created_at"], created["updated_at"], created["events"][0]["created_at"]):
        assert value.endswith("Z") and "+" not in value
    listed = anna.get("/api/requests").json()["items"][0]
    assert listed["created_at"].endswith("Z") and "+" not in listed["created_at"]
