from datetime import date, timedelta


def test_announcements_visible_to_employees(anna):
    items = anna.get("/api/announcements").json()
    assert len(items) == 3
    assert items[0]["pinned"] is True


def test_only_admin_manages_announcements(anna, tom, julia):
    body = {"title": "Summer party", "body": "Join us!", "category": "event", "event_date": str(date.today() + timedelta(days=10))}
    assert anna.post("/api/announcements", json=body).status_code == 403
    assert tom.post("/api/announcements", json=body).status_code == 403
    created = julia.post("/api/announcements", json=body).json()
    assert created["publish_date"] == str(date.today())
    archived = julia.patch(f"/api/announcements/{created['id']}", json={"archived": True}).json()
    assert archived["archived"] is True
    assert created["id"] not in [a["id"] for a in anna.get("/api/announcements").json()]


def test_scheduled_and_expired_announcements_hidden(anna, julia):
    future = {"title": "Later", "body": "x", "publish_date": str(date.today() + timedelta(days=5))}
    julia.post("/api/announcements", json=future)
    titles = [a["title"] for a in anna.get("/api/announcements").json()]
    assert "Later" not in titles
    assert anna.get("/api/announcements?include=all").status_code == 403
    assert "Later" in [a["title"] for a in julia.get("/api/announcements?include=all").json()]


def test_expiry_before_publish(julia):
    body = {"title": "x", "body": "y", "publish_date": str(date.today()), "expiry_date": str(date.today() - timedelta(days=1))}
    assert julia.post("/api/announcements", json=body).json()["code"] == "expiry_before_publish"


def test_document_search(anna):
    docs = anna.get("/api/documents?q=25 vacation days").json()
    assert [d["title"] for d in docs] == ["Vacation policy"]
    assert "25 vacation days" in docs[0]["snippet"]
    assert anna.get("/api/documents?q=%25").json() == []  # LIKE wildcards are escaped
    assert len(anna.get("/api/documents?category=it").json()) == 1


def test_document_sorting(anna, julia):
    by_title = anna.get("/api/documents").json()
    assert [d["title"] for d in by_title] == sorted(d["title"] for d in by_title)
    oldest = by_title[0]["id"]
    julia.post(f"/api/documents/{oldest}/file", files={"file": ("new.md", b"# New", "text/markdown")})
    recent = anna.get("/api/documents?sort=updated").json()
    assert recent[0]["id"] == oldest
    assert len(anna.get("/api/documents?sort=updated&category=it").json()) == 1
    assert anna.get("/api/documents?sort=size").json()["code"] == "invalid_sort"


def test_document_upload_permissions(anna, julia):
    files = {"file": ("guide.md", b"# Onboarding\nWelcome aboard", "text/markdown")}
    form = {"title": "Onboarding guide", "category": "onboarding"}
    assert anna.post("/api/documents", data=form, files=files).status_code == 403
    created = julia.post("/api/documents", data=form, files=files)
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]
    assert anna.get("/api/documents?q=aboard").json()[0]["id"] == doc_id
    content = anna.get(f"/api/documents/{doc_id}/content").json()
    assert content["format"] == "md"
    download = anna.get(f"/api/documents/{doc_id}/download")
    assert download.headers["content-type"].startswith("text/plain")
    assert "attachment" in download.headers["content-disposition"]


def test_archived_documents_hidden(anna, julia):
    doc_id = anna.get("/api/documents").json()[0]["id"]
    julia.patch(f"/api/documents/{doc_id}", json={"archived": True})
    assert anna.get(f"/api/documents/{doc_id}").status_code == 404


def test_stats_and_export(anna, tom):
    assert anna.get("/api/admin/stats").status_code == 403
    stats = tom.get("/api/admin/stats").json()
    assert stats["pending"] == 3  # vacation, laptop, appointment
    export = tom.get("/api/admin/requests/export.csv")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    lines = export.text.strip().splitlines()
    assert len(lines) == 2  # header + one approved demo request


def test_csv_injection_is_neutralised(anna, julia):
    body = {"type": "general", "title": "=HYPERLINK(\"x\")", "description": "test", "submit": True}
    created = anna.post("/api/requests", json=body).json()
    julia.post(f"/api/requests/{created['id']}/approve")
    assert "'=HYPERLINK" in julia.get("/api/admin/requests/export.csv").text


def test_user_management(tom, julia):
    body = {"email": "new.person@example.com", "first_name": "New", "last_name": "Person", "password": "welcome123"}
    assert tom.post("/api/admin/users", json=body).status_code == 403
    assert julia.post("/api/admin/users", json=body).status_code == 201
    assert julia.post("/api/admin/users", json=body).status_code == 409
    me = julia.get("/api/auth/me").json()
    assert julia.patch(f"/api/admin/users/{me['id']}", json={"role": "employee"}).status_code == 409


def test_health_and_config():
    from conftest import make_client

    client = make_client()
    assert client.get("/api/health").json() == {"status": "ok"}
    config = client.get("/api/config").json()
    assert config["demo_mode"] is True
    assert len(config["demo_accounts"]) == 6
    assert config["version"]
