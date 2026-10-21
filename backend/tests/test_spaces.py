import io

from conftest import make_client  # noqa: F401


def _new_space(client, **fields):
    response = client.post("/api/spaces", json={"name": "Testbereich", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def _people(client):
    return {p["full_name"]: p["id"] for p in client.get("/api/directory").json()}


def _upload(client, space_id, name="notiz.txt", data=b"Hallo Welt", folder_id=None):
    form = {"folder_id": str(folder_id)} if folder_id else {}
    return client.post(f"/api/spaces/{space_id}/files", files={"file": (name, io.BytesIO(data))}, data=form)


def test_spaces_are_private_to_members(anna, lukas, julia):
    space = _new_space(anna)
    assert space["my_role"] == "manager"
    assert lukas.get(f"/api/spaces/{space['id']}").status_code == 404
    assert space["id"] not in [s["id"] for s in lukas.get("/api/spaces").json()]
    # HR sees and manages every space
    assert julia.get(f"/api/spaces/{space['id']}").status_code == 200

    lukas_id = _people(anna)["Lukas Schmid"]
    detail = anna.post(f"/api/spaces/{space['id']}/members", json={"user_id": lukas_id}).json()
    assert {m["person"]["full_name"] for m in detail["members"]} == {"Anna Mayer", "Lukas Schmid"}
    assert lukas.get(f"/api/spaces/{space['id']}").json()["my_role"] == "member"
    assert "space_added" in [n["kind"] for n in lukas.get("/api/notifications").json()["items"]]
    # members cannot manage, the last manager cannot leave
    assert lukas.put(f"/api/spaces/{space['id']}", json={"name": "X"}).status_code == 403
    anna_id = _people(anna)["Anna Mayer"]
    assert anna.delete(f"/api/spaces/{space['id']}/members/{anna_id}").status_code == 409
    assert lukas.delete(f"/api/spaces/{space['id']}/members/{lukas_id}").status_code == 200


def test_new_space_has_board_channel_and_page(anna):
    space = _new_space(anna)
    detail = anna.get(f"/api/spaces/{space['id']}").json()
    assert detail["board_id"]
    overview = anna.get(f"/api/spaces/{space['id']}/overview").json()
    assert overview["pages"]


def test_files_folders_versions_and_trash(anna):
    space = _new_space(anna)
    sid = space["id"]
    folder = anna.post(f"/api/spaces/{sid}/folders", json={"name": "Verträge"}).json()
    first = _upload(anna, sid, folder_id=folder["id"]).json()
    assert first["version"] == 1
    # same name again = new version
    second = _upload(anna, sid, data=b"Hallo Welt 2", folder_id=folder["id"]).json()
    assert second["id"] == first["id"] and second["version"] == 2
    detail = anna.get(f"/api/spaces/files/{first['id']}").json()
    assert [v["number"] for v in detail["versions"]] == [2, 1]
    assert anna.get(f"/api/spaces/files/{first['id']}/download?version=1").content == b"Hallo Welt"
    restored = anna.post(f"/api/spaces/files/{first['id']}/restore-version?version=1").json()
    assert restored["version"] == 3
    assert anna.get(f"/api/spaces/files/{first['id']}/download").content == b"Hallo Welt"

    listing = anna.get(f"/api/spaces/{sid}/files?folder_id={folder['id']}").json()
    assert [f["name"] for f in listing["files"]] == ["notiz.txt"] and listing["path"][0]["name"] == "Verträge"

    # bad uploads
    assert _upload(anna, sid, name="bild.svg", data=b"<svg/>").json()["code"] == "file_type"
    assert _upload(anna, sid, name="fake.pdf", data=b"not a pdf").json()["code"] == "file_invalid"

    # trash: folder goes away with its file, comes back on restore
    assert anna.delete(f"/api/spaces/folders/{folder['id']}").status_code == 204
    assert anna.get(f"/api/spaces/{sid}/files").json()["folders"] == []
    trash = anna.get(f"/api/spaces/{sid}/trash").json()
    assert [f["name"] for f in trash["folders"]] == ["Verträge"]
    anna.post(f"/api/spaces/folders/{folder['id']}/restore")
    assert anna.get(f"/api/spaces/{sid}/files").json()["folders"][0]["name"] == "Verträge"

    anna.delete(f"/api/spaces/files/{first['id']}")
    assert anna.get(f"/api/spaces/files/{first['id']}").status_code == 404
    assert anna.delete(f"/api/spaces/files/{first['id']}/forever").status_code == 204


def test_new_office_files_from_templates(anna):
    sid = _new_space(anna)["id"]
    for kind in ("docx", "xlsx", "pptx", "md"):
        item = anna.post(f"/api/spaces/{sid}/files/new", json={"kind": kind, "name": "Neu"}).json()
        assert item["name"] == f"Neu.{kind}" and item["size"] > 0
    again = anna.post(f"/api/spaces/{sid}/files/new", json={"kind": "docx", "name": "Neu"}).json()
    assert again["name"] == "Neu (2).docx"
    data = anna.get(f"/api/spaces/files/{again['id']}/download").content
    assert data.startswith(b"PK")


def test_archived_space_is_read_only(anna):
    sid = _new_space(anna)["id"]
    anna.put(f"/api/spaces/{sid}", json={"name": "Testbereich", "archived": True})
    assert _upload(anna, sid).json()["code"] == "space_archived"
    assert anna.delete(f"/api/spaces/{sid}").status_code == 204
