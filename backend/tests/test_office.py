import dataclasses
import io
import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.routers import office as office_router
from app.services import office as office_service
from app.services.office import jwt_decode, jwt_encode
from app.services.settings import set_setting

SECRET = "test-secret"


@pytest.fixture
def office(monkeypatch):
    patched = dataclasses.replace(config.settings, onlyoffice_url="http://onlyoffice",
                                  onlyoffice_jwt_secret=SECRET, backend_internal_url="http://backend:8000")
    monkeypatch.setattr(office_service, "settings", patched)
    monkeypatch.setattr(office_router, "settings", patched)

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    calls = []

    def fake_urlopen(url, timeout=0):
        calls.append(url)
        return FakeResponse(b"PK edited by onlyoffice")

    monkeypatch.setattr(office_router.urllib.request, "urlopen", fake_urlopen)
    return calls


def _docx(client):
    sid = client.post("/api/spaces", json={"name": "Office"}).json()["id"]
    return client.post(f"/api/spaces/{sid}/files/new", json={"kind": "docx", "name": "Brief"}).json()


def test_config_lists_engines(anna, julia, office):
    data = anna.get("/api/office/config").json()
    assert data["engines"] == ["onlyoffice"] and data["default"] == "onlyoffice"
    assert anna.put("/api/office/config", json={"engine": "onlyoffice"}).status_code == 403
    assert julia.put("/api/office/config", json={"engine": "onlyoffice"}).json()["default"] == "onlyoffice"
    assert julia.put("/api/office/config", json={"engine": "collabora"}).json()["code"] == "invalid_choice"


def test_removed_collabora_setting_falls_back(anna, office):
    """Older installations may still have Collabora stored as their office server."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        set_setting(db, "office", {"engine": "collabora"})
        db.commit()
    assert anna.get("/api/office/config").json()["default"] == "onlyoffice"
    item = _docx(anna)
    opened = anna.post(f"/api/office/open/{item['id']}", json={"origin": "http://localhost:8080"}).json()
    assert opened["engine"] == "onlyoffice"
    response = anna.post(f"/api/office/open/{item['id']}", json={"engine": "collabora", "origin": "http://localhost:8080"})
    assert response.json()["code"] == "office_unavailable"
    assert TestClient(app).get(f"/wopi/files/{item['id']}?access_token=x").status_code == 404


def test_office_disabled_without_servers(anna):
    item = _docx(anna)
    assert anna.get("/api/office/config").json()["engines"] == []
    response = anna.post(f"/api/office/open/{item['id']}", json={"origin": "http://localhost:8080"})
    assert response.json()["code"] == "office_unavailable"


def test_people_outside_the_space_cannot_open(anna, lukas, office):
    item = _docx(anna)
    assert lukas.post(f"/api/office/open/{item['id']}", json={"origin": "http://localhost:8080"}).status_code == 404


def test_read_only_token_cannot_save(anna, julia, office):
    item = _docx(anna)
    sid = item["space_id"]
    anna.put(f"/api/spaces/{sid}", json={"name": "Office", "archived": True})
    opened = anna.post(f"/api/office/open/{item['id']}", json={"engine": "onlyoffice", "origin": "http://localhost:8080"}).json()
    assert opened["can_write"] is False and opened["config"]["editorConfig"]["mode"] == "view"
    callback = opened["config"]["editorConfig"]["callbackUrl"].replace("http://backend:8000", "")
    payload = {"key": opened["config"]["document"]["key"], "status": 2, "url": "http://localhost:8080/onlyoffice/x.docx"}
    assert TestClient(app).post(callback, json={"token": jwt_encode(payload, SECRET)}).json() == {"error": 1}


def test_onlyoffice_config_and_callback(anna, office):
    item = _docx(anna)
    opened = anna.post(f"/api/office/open/{item['id']}", json={"engine": "onlyoffice", "origin": "http://localhost:8080"}).json()
    config_ = opened["config"]
    assert opened["script"] == "/onlyoffice/web-apps/apps/api/documents/api.js"
    assert config_["documentType"] == "word" and config_["editorConfig"]["mode"] == "edit"
    signed = jwt_decode(config_["token"], SECRET)
    assert signed["document"]["key"] == config_["document"]["key"]

    server = TestClient(app)
    url = config_["document"]["url"].replace("http://backend:8000", "")
    assert server.get(url).status_code == 401  # needs the document server's JWT
    header = {"Authorization": "Bearer " + jwt_encode({"url": config_["document"]["url"]}, SECRET)}
    assert server.get(url, headers=header).content.startswith(b"PK")

    callback = config_["editorConfig"]["callbackUrl"].replace("http://backend:8000", "")
    payload = {"key": config_["document"]["key"], "status": 2, "url": "http://localhost:8080/onlyoffice/cache/files/x/output.docx",
               "users": [str(signed["editorConfig"]["user"]["id"])]}
    assert server.post(callback, json={"token": jwt_encode(payload, "wrong")}).status_code == 401
    assert server.post(callback, json={"token": jwt_encode(payload, SECRET)}).json() == {"error": 0}
    assert office[-1] == "http://onlyoffice/cache/files/x/output.docx"
    assert anna.get(f"/api/spaces/files/{item['id']}/download").content == b"PK edited by onlyoffice"
    assert json.loads(json.dumps(signed))  # plain JSON
