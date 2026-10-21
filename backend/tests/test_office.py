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

SECRET = "test-secret"
DISCOVERY = b"""<wopi-discovery><net-zone name="external-http">
<app name="writer"><action ext="docx" name="edit" urlsrc="http://collabora:9980/collabora/browser/abc/cool.html?"/></app>
</net-zone></wopi-discovery>"""


@pytest.fixture
def office(monkeypatch):
    patched = dataclasses.replace(config.settings, collabora_url="http://collabora:9980", onlyoffice_url="http://onlyoffice",
                                  onlyoffice_jwt_secret=SECRET, backend_internal_url="http://backend:8000")
    monkeypatch.setattr(office_service, "settings", patched)
    monkeypatch.setattr(office_router, "settings", patched)
    office_service._discovery.cache_clear()

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    calls = []

    def fake_urlopen(url, timeout=0):
        calls.append(url)
        if url.endswith("/hosting/discovery"):
            return FakeResponse(DISCOVERY)
        return FakeResponse(b"PK edited by onlyoffice")

    monkeypatch.setattr(office_service.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(office_router.urllib.request, "urlopen", fake_urlopen)
    return calls


def _docx(client):
    sid = client.post("/api/spaces", json={"name": "Office"}).json()["id"]
    return client.post(f"/api/spaces/{sid}/files/new", json={"kind": "docx", "name": "Brief"}).json()


def test_config_lists_engines(anna, julia, office):
    data = anna.get("/api/office/config").json()
    assert data["engines"] == ["collabora", "onlyoffice"] and data["default"] == "collabora"
    assert anna.put("/api/office/config", json={"engine": "onlyoffice"}).status_code == 403
    assert julia.put("/api/office/config", json={"engine": "onlyoffice"}).json()["default"] == "onlyoffice"


def test_office_disabled_without_servers(anna):
    item = _docx(anna)
    assert anna.get("/api/office/config").json()["engines"] == []
    response = anna.post(f"/api/office/open/{item['id']}", json={"origin": "http://localhost:8080"})
    assert response.json()["code"] == "office_unavailable"


def test_collabora_wopi_round_trip(anna, lukas, office):
    item = _docx(anna)
    opened = anna.post(f"/api/office/open/{item['id']}", json={"engine": "collabora", "origin": "http://localhost:8080"}).json()
    assert opened["action_url"].startswith("/collabora/browser/abc/cool.html?WOPISrc=http%3A%2F%2Fbackend%3A8000%2Fwopi%2Ffiles%2F")
    token = opened["access_token"]
    wopi = TestClient(app)  # the office server: no cookie, no CSRF header
    info = wopi.get(f"/wopi/files/{item['id']}?access_token={token}").json()
    assert info["UserCanWrite"] is True and info["BaseFileName"] == "Brief.docx" and info["UserFriendlyName"] == "Anna Mayer"
    assert wopi.get(f"/wopi/files/{item['id']}/contents?access_token={token}").content.startswith(b"PK")
    # tokens are bound to one file and cannot be forged
    assert wopi.get(f"/wopi/files/{item['id'] + 1}?access_token={token}").status_code == 401
    assert wopi.get(f"/wopi/files/{item['id']}?access_token=x{token}").status_code == 401

    lock = {"X-WOPI-Override": "LOCK", "X-WOPI-Lock": "L1"}
    assert wopi.post(f"/wopi/files/{item['id']}?access_token={token}", headers=lock).status_code == 200
    other = wopi.post(f"/wopi/files/{item['id']}?access_token={token}", headers={**lock, "X-WOPI-Lock": "L2"})
    assert other.status_code == 409 and other.headers["X-WOPI-Lock"] == "L1"
    # while locked by the editor, nobody can upload over it
    upload = anna.post(f"/api/spaces/{item['space_id']}/files", files={"file": ("Brief.docx", io.BytesIO(b"PK new"))})
    assert upload.json()["code"] == "file_locked"
    saved = wopi.post(f"/wopi/files/{item['id']}/contents?access_token={token}", content=b"PK saved", headers={"X-WOPI-Lock": "L1"})
    assert saved.status_code == 200 and saved.headers["X-WOPI-ItemVersion"] == "2"
    assert wopi.post(f"/wopi/files/{item['id']}/contents?access_token={token}", content=b"PK", headers={"X-WOPI-Lock": "bad"}).status_code == 409
    assert wopi.post(f"/wopi/files/{item['id']}?access_token={token}", headers={"X-WOPI-Override": "UNLOCK", "X-WOPI-Lock": "L1"}).status_code == 200
    detail = anna.get(f"/api/spaces/files/{item['id']}").json()
    assert detail["versions"][0]["source"] == "editor" and detail["versions"][0]["created_by"] == "Anna Mayer"

    # people outside the space cannot open it
    assert lukas.post(f"/api/office/open/{item['id']}", json={"origin": "http://localhost:8080"}).status_code == 404


def test_read_only_token_cannot_save(anna, julia, office):
    item = _docx(anna)
    sid = item["space_id"]
    anna.put(f"/api/spaces/{sid}", json={"name": "Office", "archived": True})
    opened = anna.post(f"/api/office/open/{item['id']}", json={"engine": "collabora", "origin": "http://localhost:8080"}).json()
    assert opened["can_write"] is False
    wopi = TestClient(app)
    assert wopi.post(f"/wopi/files/{item['id']}/contents?access_token={opened['access_token']}", content=b"PK").status_code == 401


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
