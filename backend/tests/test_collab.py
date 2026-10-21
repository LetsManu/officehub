def _people(client):
    return {p["full_name"]: p["id"] for p in client.get("/api/directory").json()}


def _space_with(anna, *names):
    space = anna.post("/api/spaces", json={"name": "Team"}).json()
    ids = _people(anna)
    for name in names:
        anna.post(f"/api/spaces/{space['id']}/members", json={"user_id": ids[name]})
    return anna.get(f"/api/spaces/{space['id']}").json()


def test_board_cards_assign_move_and_comment(anna, lukas, sara):
    space = _space_with(anna, "Lukas Schmid")
    board = anna.get(f"/api/boards/{space['board_id']}").json()
    todo, doing, done = board["columns"]
    assert done["is_done"] is True
    card = anna.post(f"/api/boards/columns/{todo['id']}/cards", json={"title": "Flyer drucken"}).json()
    ids = _people(anna)
    updated = anna.put(f"/api/boards/cards/{card['id']}", json={
        "title": "Flyer drucken", "description": "500 Stück", "due_date": "2026-10-22", "label": "green",
        "assignee_ids": [ids["Lukas Schmid"]]}).json()
    assert [a["full_name"] for a in updated["assignees"]] == ["Lukas Schmid"]
    assert "card_assigned" in [n["kind"] for n in lukas.get("/api/notifications").json()["items"]]
    # people outside the space cannot be assigned or see the board
    bad = anna.put(f"/api/boards/cards/{card['id']}", json={"title": "x", "assignee_ids": [ids["Sara Novak"]]})
    assert bad.status_code == 422
    assert sara.get(f"/api/boards/{space['board_id']}").status_code == 404

    mine = [c["title"] for c in lukas.get("/api/boards/mine").json() if c["space_id"] == space["id"]]
    assert mine == ["Flyer drucken"]
    lukas.post(f"/api/boards/cards/{card['id']}/comments", json={"body": "Mache ich morgen"})
    assert lukas.get(f"/api/boards/cards/{card['id']}").json()["comments"][0]["body"] == "Mache ich morgen"

    second = anna.post(f"/api/boards/columns/{doing['id']}/cards", json={"title": "Zweite"}).json()
    moved = lukas.post(f"/api/boards/cards/{card['id']}/move", json={"column_id": doing["id"], "position": 0}).json()
    assert moved["column_id"] == doing["id"] and moved["position"] == 0
    board = anna.get(f"/api/boards/{space['board_id']}").json()
    assert [c["title"] for c in board["columns"][1]["cards"]] == ["Flyer drucken", "Zweite"]
    assert second["id"]
    lukas.post(f"/api/boards/cards/{card['id']}/move", json={"column_id": done["id"], "position": 0})
    assert [c for c in lukas.get("/api/boards/mine").json() if c["space_id"] == space["id"]] == []
    assert anna.delete(f"/api/boards/columns/{doing['id']}").json()["code"] == "column_not_empty"


def test_chat_channels_direct_mentions_and_unread(anna, lukas, julia):
    space = _space_with(anna, "Lukas Schmid")
    conversations = lukas.get("/api/chat").json()
    general = next(c for c in conversations if c["space_id"] == space["id"])
    ids = _people(anna)
    before = lukas.get("/api/me/summary").json()["chat_unread"]
    sent = anna.post(f"/api/chat/{general['id']}/messages", json={"body": "Hallo @Lukas Schmid", "mentions": [ids["Lukas Schmid"], ids["Julia Weber"]]})
    assert sent.status_code == 201
    assert lukas.get("/api/me/summary").json()["chat_unread"] == before + 1
    assert "chat_mention" in [n["kind"] for n in lukas.get("/api/notifications").json()["items"]]
    # Julia is not in the space: no notification, no access (HR does not read team chats)
    assert "chat_mention" not in [n["kind"] for n in julia.get("/api/notifications").json()["items"]]
    assert julia.get(f"/api/chat/{general['id']}/messages").status_code == 404

    page = lukas.get(f"/api/chat/{general['id']}/messages").json()
    assert page["messages"][-1]["body"] == "Hallo @Lukas Schmid"
    lukas.post(f"/api/chat/{general['id']}/read", json={"last_id": page["messages"][-1]["id"]})
    assert lukas.get("/api/me/summary").json()["chat_unread"] == before
    newer = lukas.get(f"/api/chat/{general['id']}/messages?after={page['messages'][-1]['id']}").json()
    assert newer["messages"] == []

    # only the author edits; deleted messages keep their place without text
    mid = sent.json()["id"]
    assert lukas.put(f"/api/chat/messages/{mid}", json={"body": "x"}).status_code == 403
    assert anna.put(f"/api/chat/messages/{mid}", json={"body": "Hallo zusammen"}).json()["edited"] is True
    assert anna.delete(f"/api/chat/messages/{mid}").status_code == 204
    assert lukas.get(f"/api/chat/{general['id']}/messages").json()["messages"][-1]["deleted"] is True

    dm = anna.post("/api/chat/direct", json={"user_id": ids["Julia Weber"]}).json()
    assert dm["kind"] == "direct" and dm["name"] == "Julia Weber"
    assert anna.post("/api/chat/direct", json={"user_id": ids["Julia Weber"]}).json()["id"] == dm["id"]
    anna.post(f"/api/chat/{dm['id']}/messages", json={"body": "Kurze Frage"})
    assert julia.get("/api/me/summary").json()["chat_unread"] == 1
    assert lukas.get(f"/api/chat/{dm['id']}/messages").status_code == 404


def test_wiki_conflicts_history_and_presence(anna, lukas):
    space = _space_with(anna, "Lukas Schmid")
    page = anna.post(f"/api/spaces/{space['id']}/pages", json={"title": "Abläufe", "body": "Version 1"}).json()
    assert page["version"] == 1
    # both open the page
    assert lukas.post(f"/api/wiki/{page['id']}/presence").json()["editors"] == []
    seen = anna.post(f"/api/wiki/{page['id']}/presence").json()
    assert [e["full_name"] for e in seen["editors"]] == ["Lukas Schmid"]
    saved = lukas.put(f"/api/wiki/{page['id']}", json={"title": "Abläufe", "body": "Lukas", "base_version": 1}).json()
    assert saved["version"] == 2
    conflict = anna.put(f"/api/wiki/{page['id']}", json={"title": "Abläufe", "body": "Anna", "base_version": 1})
    assert conflict.status_code == 409 and conflict.json()["code"] == "page_conflict"
    history = anna.get(f"/api/wiki/{page['id']}/revisions").json()
    assert [r["version"] for r in history] == [2, 1]
    assert anna.get(f"/api/wiki/{page['id']}/revisions/1").json()["body"] == "Version 1"

    child = anna.post(f"/api/spaces/{space['id']}/pages", json={"title": "Urlaub", "parent_id": page["id"]}).json()
    loop = anna.put(f"/api/wiki/{page['id']}", json={"title": "Abläufe", "body": "x", "base_version": 2, "parent_id": child["id"]})
    assert loop.json()["code"] == "page_cycle"
    anna.delete(f"/api/wiki/{page['id']}")
    pages = {p["title"]: p for p in anna.get(f"/api/spaces/{space['id']}/pages").json()}
    assert "Abläufe" not in pages and pages["Urlaub"]["parent_id"] is None


def test_search_finds_workspace_content_for_members_only(anna, sara):
    space = _space_with(anna)
    anna.post(f"/api/spaces/{space['id']}/pages", json={"title": "Kaffeemaschine entkalken", "body": "Jeden Freitag"})
    hits = anna.get("/api/search?q=Kaffeemaschine").json()["workspace"]
    assert [h["title"] for h in hits] == ["Kaffeemaschine entkalken"]
    assert sara.get("/api/search?q=Kaffeemaschine").json()["workspace"] == []
