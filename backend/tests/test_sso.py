"""Company login with the company's own OpenID Connect server (e.g. Authentik), with a stand-in server."""

import base64
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import sso

ISSUER = "https://auth.muster.example/application/o/officehub"


def _token(claims: dict) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2ln"


@pytest.fixture
def idp(monkeypatch):
    """Stand-in for Authentik: discovery and token endpoint; `claims` is what the next ID token says."""
    server = {"claims": {}, "token_requests": []}

    def fake(url, data=None, headers=None):
        if url.endswith("/.well-known/openid-configuration"):
            return {"issuer": ISSUER + "/", "authorization_endpoint": "https://auth.muster.example/authorize",
                    "token_endpoint": "https://auth.muster.example/token", "userinfo_endpoint": "https://auth.muster.example/userinfo"}
        if url.endswith("/token"):
            server["token_requests"].append(data)
            return {"access_token": "a", "id_token": _token(server["claims"])}
        raise OSError("unexpected " + url)

    monkeypatch.setattr(sso, "_get_json", fake)
    sso._discovery.cache_clear()
    return server


def _configure(julia, **extra):
    body = {"enabled": True, "issuer": ISSUER, "client_id": "officehub", "client_secret": "s3cret", "label": "Authentik", **extra}
    response = julia.put("/api/admin/sso", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _sign_in(idp, **claims):
    browser = TestClient(app, headers={"X-Requested-With": "OfficeHub"}, follow_redirects=False)
    start = browser.get("/api/auth/sso/start?origin=http://testserver")
    assert start.status_code == 303
    query = parse_qs(urlsplit(start.headers["location"]).query)
    if "state" not in query:
        return browser, start
    state = query["state"][0]
    assert query["redirect_uri"] == ["http://testserver/api/auth/sso/callback"] and query["code_challenge_method"] == ["S256"]
    idp["claims"] = {"iss": ISSUER, "aud": "officehub", "nonce": sso._pending[state][0], "exp": time.time() + 300,
                     "sub": "u-1", **claims}
    return browser, browser.get(f"/api/auth/sso/callback?state={state}&code=abc")


def test_settings_only_for_admins_and_secret_stays_hidden(anna, julia, idp):
    assert anna.get("/api/admin/sso").status_code == 403
    assert "sso" not in anna.get("/api/config").json()
    saved = _configure(julia)
    assert saved["client_secret"] == "" and saved["has_secret"] is True
    again = julia.put("/api/admin/sso", json={**saved, "label": "Firmenkonto"}).json()  # empty secret = keep it
    assert again["has_secret"] is True
    assert anna.get("/api/config").json()["sso"] == {"label": "Firmenkonto"}
    assert julia.put("/api/admin/sso", json={**saved, "issuer": ""}).json()["code"] == "sso_issuer"


def test_new_person_signs_in_with_company_account(julia, idp):
    _configure(julia)
    browser, done = _sign_in(idp, email="neu.kollegin@example.com", email_verified=True, given_name="Nora", family_name="Neu")
    assert done.status_code == 303 and done.headers["location"] == "/"
    me = browser.get("/api/auth/me").json()
    assert me["email"] == "neu.kollegin@example.com" and me["first_name"] == "Nora" and me["role"] == "employee"
    assert idp["token_requests"][0]["client_secret"] == "s3cret" and idp["token_requests"][0]["code_verifier"]


def test_existing_person_is_linked_and_groups_set_the_role(julia, idp):
    _configure(julia, admin_group="officehub-admins", manager_group="officehub-managers")
    browser, done = _sign_in(idp, email="Anna.Mayer@example.com", email_verified=True, groups=["officehub-managers"])
    assert done.headers["location"] == "/"
    me = browser.get("/api/auth/me").json()
    assert me["email"] == "anna.mayer@example.com" and me["role"] == "manager"
    # later sign-ins find her by the server's ID, even with another address there
    browser, _ = _sign_in(idp, email="anna@neu.example", email_verified=False, groups=[])
    assert browser.get("/api/auth/me").json()["email"] == "anna.mayer@example.com"
    assert browser.get("/api/auth/me").json()["role"] == "employee"


def test_refusals_end_on_the_sign_in_page(julia, idp):
    _configure(julia, create_users=False)
    _, done = _sign_in(idp, email="anna.mayer@example.com")  # address not confirmed by the server
    assert done.headers["location"] == "/login?sso=email_unverified"
    _, done = _sign_in(idp, email="fremd@example.com", email_verified=True)
    assert done.headers["location"] == "/login?sso=no_account"
    _, done = _sign_in(idp, email="anna.mayer@example.com", email_verified=True, nonce="other")
    assert done.headers["location"] == "/login?sso=failed"
    _, done = _sign_in(idp, email="anna.mayer@example.com", email_verified=True, aud="someone-else")
    assert done.headers["location"] == "/login?sso=failed"

    browser = TestClient(app, follow_redirects=False)
    assert browser.get("/api/auth/sso/start?origin=https://evil.example").headers["location"] == "/login?sso=failed"
    assert browser.get("/api/auth/sso/callback?state=x&code=y").headers["location"] == "/login?sso=expired"
    assert browser.get("/api/auth/sso/callback?error=access_denied").headers["location"] == "/login?sso=denied"

    julia.put("/api/admin/sso", json={**julia.get("/api/admin/sso").json(), "enabled": False})
    _, done = _sign_in(idp)
    assert done.headers["location"] == "/login?sso=not_configured"
