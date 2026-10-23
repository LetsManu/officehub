from datetime import date, timedelta

from app import totp
from app.holidays import easter_sunday, public_holidays
from app.workdays import count_working_days
from conftest import make_client, working_day

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _me(client):
    return client.get("/api/profile").json()


# ---------- Holidays ----------


def test_easter_and_country_lists():
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert easter_sunday(2027) == date(2027, 3, 28)
    at = {d for d, *_ in public_holidays(2026, "AT")}
    assert date(2026, 10, 26) in at and date(2026, 4, 6) in at  # national day, Easter Monday
    de_by = {d for d, *_ in public_holidays(2026, "DE", "BY")}
    de_be = {d for d, *_ in public_holidays(2026, "DE", "BE")}
    assert date(2026, 8, 15) in de_by and date(2026, 8, 15) not in de_be
    assert date(2026, 3, 8) in de_be


def test_working_days_skip_holidays():
    week = (date(2026, 10, 26), date(2026, 10, 30))
    assert count_working_days(*week) == 5
    assert count_working_days(*week, holidays={date(2026, 10, 26)}) == 4


def test_vacation_request_excludes_configured_holidays(anna, julia):
    assert julia.put("/api/holidays/config", json={"country": "AT", "region": ""}).status_code == 200
    year = date.today().year + 1
    body = {"type": "vacation", "title": "Herbst", "start_date": f"{year}-10-26", "end_date": f"{year}-10-30", "submit": False}
    created = anna.post("/api/requests", json=body).json()
    expected = count_working_days(date(year, 10, 26), date(year, 10, 30), {date(year, 10, 26)})
    assert created["working_days"] == expected
    listed = anna.get(f"/api/holidays?year={year}").json()
    assert any(h["date"] == f"{year}-10-26" for h in listed)


def test_company_holidays(julia, anna):
    year = date.today().year + 1
    response = julia.post("/api/holidays/company", json={"day": f"{year}-12-24", "name": "Heiliger Abend"})
    assert response.status_code == 201
    assert julia.post("/api/holidays/company", json={"day": f"{year}-12-24", "name": "x"}).status_code == 409
    assert any(h["company"] for h in anna.get(f"/api/holidays?year={year}").json())
    assert anna.post("/api/holidays/company", json={"day": f"{year}-12-31", "name": "x"}).status_code == 403


# ---------- Branding ----------


def test_branding_public_and_contrast(julia):
    public = make_client()
    assert public.get("/api/branding").json()["accent_color"] == "#1D4ED8"
    too_light = julia.put("/api/branding", json={"company_name": "Muster GmbH", "accent_color": "#FFE066"})
    assert too_light.status_code == 422 and too_light.json()["code"] == "accent_contrast"
    ok = julia.put("/api/branding", json={"company_name": "Muster GmbH", "accent_color": "#0f766e"}).json()
    assert ok["accent_color"] == "#0F766E"
    logo = julia.post("/api/branding/logo", files={"file": ("logo.png", PNG, "image/png")}).json()
    assert logo["logo_version"]
    assert public.get("/api/branding/logo").status_code == 200
    assert julia.delete("/api/branding/logo").json()["logo_version"] is None


def test_branding_admin_only(anna):
    assert anna.put("/api/branding", json={"company_name": "X", "accent_color": "#000000"}).status_code == 403


def test_manifest_carries_branding_language_and_share_target(julia):
    public = make_client()
    plain = public.get("/api/branding/manifest.webmanifest", headers={"Accept-Language": "de-DE,de;q=0.9"})
    assert plain.status_code == 200 and plain.headers["content-type"].startswith("application/manifest+json")
    body = plain.json()
    assert body["name"] == (public.get("/api/branding").json()["company_name"] or "OfficeHub") and body["lang"] == "de"
    assert [s["url"] for s in body["shortcuts"]] == ["/chat", "/calendar", "/files", "/requests/new"]
    assert body["shortcuts"][1]["name"] == "Kalender"
    assert body["share_target"]["action"] == "/share" and body["share_target"]["method"] == "POST"
    julia.put("/api/branding", json={"company_name": "Muster GmbH", "accent_color": "#0f766e"})
    english = public.get("/api/branding/manifest.webmanifest", headers={"Accept-Language": "en-GB"}).json()
    assert english["name"] == "Muster GmbH" and english["theme_color"] == "#0F766E"
    assert english["lang"] == "en" and english["shortcuts"][1]["name"] == "Calendar"


def test_summary_tells_the_running_version(anna):
    assert anna.get("/api/me/summary").json()["version"]


# ---------- Photos ----------


def test_profile_photo(anna, lukas):
    me = anna.post("/api/profile/photo", files={"file": ("photo.png", PNG, "image/png")}).json()
    assert me["photo_version"]
    assert lukas.get(f"/api/directory/{me['id']}/photo").status_code == 200
    entry = next(p for p in lukas.get("/api/directory").json() if p["id"] == me["id"])
    assert entry["photo_version"] == me["photo_version"]
    assert anna.post("/api/profile/photo", files={"file": ("photo.png", b"not an image", "image/png")}).status_code == 422
    assert anna.delete("/api/profile/photo").json()["photo_version"] is None
    assert make_client().get(f"/api/directory/{me['id']}/photo").status_code == 401


# ---------- Deputies ----------


def test_deputy_receives_and_decides(tom, anna, lukas):
    lukas_id = _me(lukas)["id"]
    assert anna.put("/api/profile/deputy", json={"deputy_id": lukas_id, "until": str(date.today())}).status_code == 403
    tomorrow = str(date.today() + timedelta(days=1))
    assert tom.put("/api/profile/deputy", json={"deputy_id": lukas_id, "until": tomorrow}).json()["deputy_id"] == lukas_id

    start = working_day(60)
    body = {"type": "vacation", "title": "Kurz", "start_date": str(start), "end_date": str(start), "submit": True}
    req = anna.post("/api/requests", json=body).json()
    assert lukas.get("/api/notifications").json()["items"][0]["kind"] == "request_submitted"
    assert lukas.get("/api/me/summary").json()["acting_deputy"] is True
    team = lukas.get("/api/requests?scope=all").json()["items"]
    assert any(r["id"] == req["id"] for r in team)
    assert all(r["requester"]["id"] != lukas_id for r in team)
    assert lukas.post(f"/api/requests/{req['id']}/approve", json={}).status_code == 200

    # After removing the deputy Lukas has no access any more
    tom.put("/api/profile/deputy", json={"deputy_id": None})
    assert lukas.get("/api/requests?scope=all").status_code == 403


# ---------- Two-factor sign-in ----------


def test_two_factor_flow(anna):
    setup = anna.post("/api/profile/2fa/setup").json()
    assert setup["qr_image"].startswith("data:image/svg+xml") and setup["otpauth_url"].startswith("otpauth://totp/")
    assert anna.post("/api/profile/2fa/enable", json={"code": "000000"}).status_code in (422,)
    codes = anna.post("/api/profile/2fa/enable", json={"code": totp.current_code(setup["secret"])}).json()["recovery_codes"]
    assert len(codes) == 8

    client = make_client()
    login = {"email": "anna.mayer@example.com", "password": "demo1234"}
    assert client.post("/api/auth/login", json=login).json()["code"] == "two_factor_required"
    assert client.post("/api/auth/login", json=login | {"code": "123456"}).json()["code"] == "two_factor_invalid"
    assert client.post("/api/auth/login", json=login | {"code": totp.current_code(setup["secret"])}).status_code == 200
    # A recovery code works once
    other = make_client()
    assert other.post("/api/auth/login", json=login | {"code": codes[0]}).status_code == 200
    assert make_client().post("/api/auth/login", json=login | {"code": codes[0]}).status_code == 401

    assert anna.post("/api/profile/2fa/disable", json={"password": "wrong"}).status_code == 422
    assert anna.post("/api/profile/2fa/disable", json={"password": "demo1234"}).json()["totp_enabled"] is False


def test_admin_can_reset_two_factor_and_require_it(anna, julia):
    setup = anna.post("/api/profile/2fa/setup").json()
    anna.post("/api/profile/2fa/enable", json={"code": totp.current_code(setup["secret"])})
    anna_id = next(u["id"] for u in julia.get("/api/admin/users").json() if u["email"].startswith("anna"))
    assert julia.post(f"/api/admin/users/{anna_id}/2fa/reset").status_code == 204
    assert make_client("anna.mayer@example.com").get("/api/profile").json()["totp_enabled"] is False
    settings = julia.put("/api/portal/settings", json={"require_2fa_roles": ["admin", "manager"]}).json()
    assert settings["require_2fa_roles"] == ["admin", "manager"]


# ---------- Audit log and e-mail ----------


def test_audit_log(julia, anna):
    anna_id = next(u["id"] for u in julia.get("/api/admin/users").json() if u["email"].startswith("anna"))
    julia.patch(f"/api/admin/users/{anna_id}", json={"department": "Sales"})
    log = julia.get("/api/admin/audit").json()
    assert log["items"][0]["action"] == "user_updated" and log["items"][0]["actor_name"] == "Julia Weber"
    assert julia.get("/api/admin/audit?action=nope").status_code == 422
    csv_text = julia.get("/api/admin/audit/export.csv").text
    assert "user_updated" in csv_text
    assert anna.get("/api/admin/audit").status_code == 403


def test_mail_messages_and_test_endpoint(julia, anna, monkeypatch):
    from app.services import mailer

    message = mailer.build_message("a@example.com", "de", "request_approved", {"name": "Tom", "title": "Urlaub"}, "/requests/1")
    assert "Tom hat deinen Antrag „Urlaub“ genehmigt." in message["Subject"]
    assert "/requests/1" in message.get_content()
    assert julia.post("/api/admin/mail-test").json()["code"] == "mail_not_configured"
    assert anna.post("/api/admin/mail-test").status_code == 403


def test_mail_is_queued_only_when_enabled(anna, tom, monkeypatch):
    from app.config import settings
    from app.services import mailer

    sent: list = []
    monkeypatch.setattr(type(settings), "mail_enabled", property(lambda self: True))
    monkeypatch.setattr(mailer, "_send_in_background", lambda messages: sent.extend(messages))
    start = working_day(70)
    anna.post("/api/requests", json={"type": "vacation", "title": "Mail", "start_date": str(start), "end_date": str(start), "submit": True})
    assert any(m["To"] == "tom.huber@example.com" for m in sent)
    # People can switch it off
    tom.patch("/api/profile", json={"email_notifications": False})
    sent.clear()
    anna.post("/api/requests", json={"type": "vacation", "title": "Mail 2", "start_date": str(start), "end_date": str(start), "submit": True})
    assert not any(m["To"] == "tom.huber@example.com" for m in sent)
