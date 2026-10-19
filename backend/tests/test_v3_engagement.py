from datetime import date, timedelta

from conftest import make_client

EMAILS = ["anna.mayer", "lukas.schmid", "sara.novak", "tom.huber", "julia.weber", "max.gruber"]


def _id(client, admin, prefix):
    return next(u["id"] for u in admin.get("/api/admin/users").json() if u["email"].startswith(prefix))


# ---------- Surveys ----------


def _new_survey(julia, **extra):
    body = {
        "title": "Wie geht's?",
        "questions": [
            {"text": "Wie zufrieden bist du?", "kind": "scale"},
            {"text": "Lieblingsort?", "kind": "choice", "options": ["Büro", "Zuhause"]},
            {"text": "Was wünschst du dir?", "kind": "text"},
        ],
    } | extra
    survey = julia.post("/api/surveys", json=body)
    assert survey.status_code == 201, survey.text
    return survey.json()


def test_survey_lifecycle_and_anonymity(julia, anna):
    survey = _new_survey(julia)
    assert all(s["id"] != survey["id"] for s in anna.get("/api/surveys").json())  # drafts are hidden
    julia.patch(f"/api/surveys/{survey['id']}", json={"status": "open"})
    assert anna.get("/api/notifications").json()["items"][0]["kind"] == "survey_new"
    assert anna.get("/api/me/summary").json()["surveys_open"] >= 1

    assert anna.post(f"/api/surveys/{survey['id']}/respond", json={"answers": [9, 0, ""]}).status_code == 422
    done = anna.post(f"/api/surveys/{survey['id']}/respond", json={"answers": [4, 1, "Mehr Pflanzen"]}).json()
    assert done["answered"] is True
    assert anna.post(f"/api/surveys/{survey['id']}/respond", json={"answers": [4, 1, ""]}).json()["code"] == "survey_answered"

    # Fewer than five answers: HR sees no numbers yet
    early = julia.get(f"/api/surveys/{survey['id']}/results").json()
    assert early["enough"] is False and early["questions"][0]["counts"] == [0, 0, 0, 0, 0]
    for email in EMAILS[1:5]:
        make_client(f"{email}@example.com").post(f"/api/surveys/{survey['id']}/respond", json={"answers": [5, 0, None]})
    results = julia.get(f"/api/surveys/{survey['id']}/results").json()
    assert results["enough"] is True and results["responses"] == 5
    assert results["questions"][0]["average"] == 4.8 and results["questions"][2]["texts"] == ["Mehr Pflanzen"]
    assert anna.get(f"/api/surveys/{survey['id']}/results").status_code == 404


def test_survey_answers_are_not_linked_to_people():
    from app.models import SurveyResponse

    assert {c.name for c in SurveyResponse.__table__.columns} == {"id", "survey_id", "answers"}


def test_closed_survey_and_public_results(julia, anna):
    survey = _new_survey(julia, results_public=True)
    julia.patch(f"/api/surveys/{survey['id']}", json={"status": "open"})
    julia.patch(f"/api/surveys/{survey['id']}", json={"status": "closed"})
    assert anna.post(f"/api/surveys/{survey['id']}/respond", json={"answers": [3, 0, ""]}).json()["code"] == "survey_closed"
    assert anna.get(f"/api/surveys/{survey['id']}/results").status_code == 200


# ---------- Ideas ----------


def test_ideas_vote_and_status(anna, lukas, julia):
    idea = anna.post("/api/ideas", json={"title": "Obstkorb", "body": "Jeden Montag frisches Obst."}).json()
    assert idea["votes"] == 1 and idea["voted"] is True
    assert lukas.post(f"/api/ideas/{idea['id']}/vote").json()["votes"] == 2
    assert lukas.post(f"/api/ideas/{idea['id']}/vote").json()["votes"] == 1
    assert lukas.delete(f"/api/ideas/{idea['id']}").status_code == 403
    assert lukas.put(f"/api/ideas/{idea['id']}/status", json={"status": "done"}).status_code == 403
    decided = julia.put(f"/api/ideas/{idea['id']}/status", json={"status": "planned", "response": "Ab nächstem Monat."}).json()
    assert decided["status"] == "planned"
    assert anna.get("/api/notifications").json()["items"][0]["kind"] == "idea_status"
    assert anna.delete(f"/api/ideas/{idea['id']}").status_code == 403  # no longer "new"
    assert any(i["id"] == idea["id"] for i in lukas.get("/api/ideas?status=planned").json())


# ---------- Trainings ----------


def test_trainings_status_and_records(julia, anna, lukas):
    training = julia.post("/api/trainings", json={"title": "Brandschutz", "interval_months": 12, "due_within_days": 14}).json()
    mine = {t["training"]["id"]: t for t in anna.get("/api/trainings/mine").json()}
    assert mine[training["id"]]["status"] in ("open", "due_soon", "overdue")
    assert anna.get("/api/me/summary").json()["trainings_due"] >= 0

    done = anna.post(
        f"/api/trainings/{training['id']}/complete",
        data={"completed_on": str(date.today())},
        files={"file": ("zertifikat.pdf", b"%PDF-1.4 test", "application/pdf")},
    ).json()
    assert done["status"] == "valid" and done["valid_until"] and done["has_certificate"]
    assert anna.get(f"/api/trainings/records/{done['record_id']}/certificate").status_code == 200
    assert lukas.get(f"/api/trainings/records/{done['record_id']}/certificate").status_code == 404

    future = anna.post(f"/api/trainings/{training['id']}/complete", data={"completed_on": str(date.today() + timedelta(days=2))})
    assert future.json()["code"] == "day_future"

    people = julia.get(f"/api/trainings/{training['id']}/people").json()
    assert {p["person"]["full_name"] for p in people} >= {"Anna Mayer", "Lukas Schmid"}
    lukas_id = _id(lukas, julia, "lukas")
    recorded = julia.post(f"/api/trainings/{training['id']}/people/{lukas_id}", data={"completed_on": str(date.today() - timedelta(days=400))}).json()
    assert recorded["status"] == "overdue"  # expired after 12 months
    reminded = julia.post(f"/api/trainings/{training['id']}/remind").json()["reminded"]
    assert reminded >= 1
    assert "Brandschutz" not in anna.get(f"/api/trainings/{training['id']}/export.csv").text
    assert "Lukas Schmid" in julia.get(f"/api/trainings/{training['id']}/export.csv").text


def test_department_trainings(julia, anna, lukas):
    t = julia.post("/api/trainings", json={"title": "Kassenschulung", "department": "Sales"}).json()
    assert any(r["training"]["id"] == t["id"] for r in lukas.get("/api/trainings/mine").json())
    assert all(r["training"]["id"] != t["id"] for r in anna.get("/api/trainings/mine").json())


# ---------- Equipment and offboarding ----------


def test_assets_and_offboarding(julia, lukas):
    lukas_id = _id(lukas, julia, "lukas")
    laptop = julia.post("/api/assets", json={"name": "Test-Notebook", "kind": "laptop", "serial": "SN-1"}).json()
    assert laptop["status"] == "in_stock"
    assigned = julia.post(f"/api/assets/{laptop['id']}/assign", json={"person_id": lukas_id}).json()
    assert assigned["status"] == "assigned" and assigned["assigned_to"]["id"] == lukas_id
    assert any(a["id"] == laptop["id"] for a in lukas.get("/api/assets/mine").json())
    assert lukas.get("/api/assets").status_code == 403

    checklist = julia.post(f"/api/onboarding/{lukas_id}/offboarding", json={"last_day": str(date.today() + timedelta(days=30))}).json()
    assert checklist["kind"] == "offboarding" and checklist["last_day"]
    returns = [t for t in checklist["tasks"] if t["key"] == "asset_return" and t["title"] == "Test-Notebook"]
    assert returns
    julia.patch(f"/api/onboarding/tasks/{returns[0]['id']}", json={"done": True})
    back = julia.get(f"/api/assets/{laptop['id']}").json()
    assert back["status"] == "in_stock" and back["assigned_to"] is None
    assert [h["action"] for h in back["history"]][:2] == ["returned", "assigned"]

    overview = julia.get("/api/onboarding?kind=offboarding").json()
    assert any(s["person"]["id"] == lukas_id for s in overview)
    # The onboarding view stays separate
    assert all(s["kind"] == "onboarding" for s in julia.get("/api/onboarding").json())
    julia_id = _id(julia, julia, "julia")
    assert julia.post(f"/api/onboarding/{julia_id}/offboarding", json={"last_day": str(date.today())}).status_code == 409


def test_asset_status_rules(julia, anna):
    anna_id = _id(anna, julia, "anna")
    phone = julia.post("/api/assets", json={"name": "Diensthandy", "kind": "phone"}).json()
    julia.put(f"/api/assets/{phone['id']}", json={"name": "Diensthandy", "kind": "phone", "status": "repair"})
    assert julia.post(f"/api/assets/{phone['id']}/assign", json={"person_id": anna_id}).json()["code"] == "asset_unavailable"
    assert julia.post(f"/api/assets/{phone['id']}/return", json={}).json()["code"] == "asset_not_assigned"
    assert any(a["id"] == phone["id"] for a in julia.get("/api/assets?q=handy").json())
