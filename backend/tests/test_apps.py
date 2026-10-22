"""The feed the Windows and Android apps wait on: new notifications, chat messages and ringing calls."""

import time

from app.routers import apps


def _me(client):
    return client.get("/api/auth/me").json()["id"]


def test_feed_starts_quiet_then_brings_messages_notifications_and_calls(anna, lukas, monkeypatch):
    monkeypatch.setattr(apps, "WAIT_SECONDS", 4)
    monkeypatch.setattr(apps, "STEP_SECONDS", 0.2)
    first = lukas.get("/api/me/feed").json()
    # Where things stand, nothing old pops up
    assert first["notifications"] == [] and first["messages"] == []
    cursor = {"notification_after": first["notification_after"], "chat_after": first["chat_after"]}

    # Nothing new: the wait ends empty after the time is up
    started = time.monotonic()
    empty = lukas.get("/api/me/feed", params=cursor | {"wait": True}).json()
    assert empty["messages"] == [] and time.monotonic() - started >= 3

    # Anna writes to Lukas: it comes back with sender and text
    direct = anna.post("/api/chat/direct", json={"user_id": _me(lukas)}).json()
    assert anna.post(f"/api/chat/{direct['id']}/messages", json={"body": "Hast du kurz Zeit?"}).status_code == 201
    got = lukas.get("/api/me/feed", params=cursor | {"wait": True}).json()
    assert [(m["name"], m["body"]) for m in got["messages"]] == [("Anna Mayer", "Hast du kurz Zeit?")]
    assert got["chat_unread"] >= 1
    cursor["chat_after"] = got["chat_after"]
    again = lukas.get("/api/me/feed", params=cursor).json()
    assert again["messages"] == []  # the same message does not come twice

    # A call rings at once
    call = anna.post("/api/calls", json={"user_id": _me(lukas)}).json()
    ringing = lukas.get("/api/me/feed", params=cursor | {"wait": True}).json()
    assert [c["meeting_id"] for c in ringing["calls"]] == [call["meeting_id"]]
    assert ringing["calls"][0]["caller"]["full_name"] == "Anna Mayer"

    # Lukas declines: the missed-call note is not there yet, the call is gone
    lukas.post(f"/api/calls/{call['meeting_id']}/decline")
    assert lukas.get("/api/me/feed", params=cursor).json()["calls"] == []


def test_feed_needs_a_session():
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/api/me/feed").status_code == 401


def test_the_apps_stay_signed_in_like_teams():
    from datetime import timedelta

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.main import app
    from app.models import AuthSession, utcnow

    def sign_in(agent):
        c = TestClient(app, headers={"X-Requested-With": "OfficeHub", "User-Agent": agent})
        assert c.post("/api/auth/login", json={"email": "anna.mayer@example.com", "password": "demo1234"}).status_code == 200
        return c

    browser = sign_in("Mozilla/5.0 Chrome/141")
    phone = sign_in("Mozilla/5.0 (Linux; Android 15) Chrome/141 OfficeHubApp/1.0 (android)")
    with SessionLocal() as db:
        sessions = db.scalars(select(AuthSession).order_by(AuthSession.id.desc()).limit(2)).all()
        app_session, web_session = sessions
        assert app_session.app and not web_session.app
        assert app_session.expires_at - utcnow() > timedelta(days=80)
        assert web_session.expires_at - utcnow() < timedelta(days=1)
        # Using the app extends its session again
        app_session.expires_at = utcnow() + timedelta(days=10)
        db.commit()
    assert phone.get("/api/auth/me").status_code == 200
    assert browser.get("/api/auth/me").status_code == 200
    with SessionLocal() as db:
        assert db.get(AuthSession, app_session.id).expires_at - utcnow() > timedelta(days=80)
