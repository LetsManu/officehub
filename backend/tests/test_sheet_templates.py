"""New spreadsheets from a template: a budget, a to-do list and a weekly plan, in the person's language."""

import io
import zipfile


def _space(client):
    return client.post("/api/spaces", json={"name": "Vorlagen", "description": ""}).json()


def test_new_spreadsheet_from_a_template(anna):
    space = _space(anna)
    made = anna.post(f"/api/spaces/{space['id']}/files/new",
                     json={"kind": "xlsx", "name": "Budget 2027", "template": "budget"})
    assert made.status_code == 201 and made.json()["name"] == "Budget 2027.xlsx"
    data = anna.get(f"/api/spaces/files/{made.json()['id']}/download").content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        book = z.read("xl/workbook.xml").decode()
    assert "Actual" in sheet and "<f>SUM(B2:B7)</f>" in sheet and "<f>C2-B2</f>" in sheet  # in Anna's language
    assert 'name="Budget"' in book

    for kind, word in (("todo", "Task"), ("week", "Monday")):
        made = anna.post(f"/api/spaces/{space['id']}/files/new", json={"kind": "xlsx", "name": kind, "template": kind})
        with zipfile.ZipFile(io.BytesIO(anna.get(f"/api/spaces/files/{made.json()['id']}/download").content)) as z:
            assert word in z.read("xl/worksheets/sheet1.xml").decode()

    # Only for spreadsheets, only known templates
    assert anna.post(f"/api/spaces/{space['id']}/files/new",
                     json={"kind": "docx", "name": "x", "template": "budget"}).json()["code"] == "invalid_choice"
    assert anna.post(f"/api/spaces/{space['id']}/files/new",
                     json={"kind": "xlsx", "name": "x", "template": "../etc"}).json()["code"] == "invalid_choice"
