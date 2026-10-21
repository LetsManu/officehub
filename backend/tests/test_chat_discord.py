"""Chat like Discord: threads, reactions, pins, polls, voice messages, notification levels, rich presence."""

from datetime import datetime, timedelta, timezone
from urllib.parse import quote


def _ids(client):
    return {p["full_name"]: p["id"] for p in client.get("/api/directory").json()}


def _dm(a, b_name):
    return a.post("/api/chat/direct", json={"user_id": _ids(a)[b_name]}).json()


def test_threads_reactions_pins_and_changes(anna, lukas):
    dm = _dm(anna, "Lukas Schmid")
    first = anna.post(f"/api/chat/{dm['id']}/messages", json={"body": "**Agenda** für morgen?"}).json()
    since = datetime.now(timezone.utc) - timedelta(seconds=1)
    reply = lukas.post(f"/api/chat/{dm['id']}/messages", json={"body": "Ich schick sie gleich", "parent_id": first["id"]})
    assert reply.status_code == 201 and reply.json()["parent_id"] == first["id"]
    # replies stay in the thread, not in the conversation
    page = anna.get(f"/api/chat/{dm['id']}/messages").json()
    assert [m["id"] for m in page["messages"]] == [first["id"]] and page["messages"][0]["reply_count"] == 1
    thread = anna.get(f"/api/chat/messages/{first['id']}/thread").json()
    assert [r["body"] for r in thread["replies"]] == ["Ich schick sie gleich"]
    assert "chat_reply" in [n["kind"] for n in anna.get("/api/notifications").json()["items"]]

    reacted = lukas.post(f"/api/chat/messages/{first['id']}/reactions", json={"emoji": "👍"}).json()
    assert reacted["reactions"] == [{"emoji": "👍", "count": 1, "mine": True, "names": ["Lukas Schmid"]}]
    assert lukas.post(f"/api/chat/messages/{first['id']}/reactions", json={"emoji": "abc"}).status_code == 422
    assert anna.post(f"/api/chat/messages/{first['id']}/pin").json()["pinned"] is True
    assert [p["id"] for p in lukas.get(f"/api/chat/{dm['id']}/pins").json()] == [first["id"]]

    # an open chat gets changed messages (reaction, reply count, pin) without loading everything again
    poll = anna.get(f"/api/chat/{dm['id']}/messages?after={first['id']}&since={quote(since.isoformat())}").json()
    assert [m["id"] for m in poll["changed"]] == [first["id"]]
    # toggling removes my reaction again
    assert lukas.post(f"/api/chat/messages/{first['id']}/reactions", json={"emoji": "👍"}).json()["reactions"] == []


def test_polls(anna, lukas):
    dm = _dm(anna, "Lukas Schmid")
    poll = anna.post(f"/api/chat/{dm['id']}/polls", json={"question": "Pizza oder Sushi?", "options": ["Pizza", "Sushi"]}).json()
    assert poll["kind"] == "poll" and [o["text"] for o in poll["poll"]["options"]] == ["Pizza", "Sushi"]
    pizza, sushi = (o["id"] for o in poll["poll"]["options"])
    assert lukas.post(f"/api/chat/messages/{poll['id']}/vote", json={"option_ids": [pizza, sushi]}).status_code == 422
    voted = lukas.post(f"/api/chat/messages/{poll['id']}/vote", json={"option_ids": [sushi]}).json()["poll"]
    assert voted["total"] == 1 and voted["options"][1]["mine"] and voted["options"][1]["voters"] == ["Lukas Schmid"]
    changed = lukas.post(f"/api/chat/messages/{poll['id']}/vote", json={"option_ids": [pizza]}).json()["poll"]
    assert [o["votes"] for o in changed["options"]] == [1, 0]
    assert lukas.post(f"/api/chat/messages/{poll['id']}/close-poll").status_code == 403
    anna.post(f"/api/chat/messages/{poll['id']}/close-poll")
    assert lukas.post(f"/api/chat/messages/{poll['id']}/vote", json={"option_ids": [sushi]}).json()["code"] == "poll_closed"


def test_voice_message(anna, lukas):
    dm = _dm(anna, "Lukas Schmid")
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 200
    sent = anna.post(f"/api/chat/{dm['id']}/voice", data={"seconds": "4"}, files={"file": ("voice.webm", webm, "audio/webm")})
    assert sent.status_code == 201 and sent.json()["kind"] == "voice" and sent.json()["audio_seconds"] == 4
    heard = lukas.get(f"/api/chat/messages/{sent.json()['id']}/audio")
    assert heard.status_code == 200 and heard.content == webm
    fake = anna.post(f"/api/chat/{dm['id']}/voice", data={"seconds": "4"}, files={"file": ("x.webm", b"<html>", "audio/webm")})
    assert fake.status_code == 422


def test_notification_levels_and_mute(anna, lukas):
    dm = _dm(anna, "Lukas Schmid")
    lukas_id = _ids(anna)["Lukas Schmid"]
    before = lukas.get("/api/me/summary").json()["chat_unread"]
    anna.post(f"/api/chat/{dm['id']}/messages", json={"body": "Hallo"})
    assert lukas.get("/api/me/summary").json()["chat_unread"] == before + 1
    settings = lukas.put(f"/api/chat/{dm['id']}/settings", json={"notify": "mentions"}).json()
    assert settings["notify"] == "mentions"
    assert lukas.get("/api/me/summary").json()["chat_unread"] == before  # plain messages no longer count
    anna.post(f"/api/chat/{dm['id']}/messages", json={"body": "@Lukas Schmid schau mal", "mentions": [lukas_id]})
    assert lukas.get("/api/me/summary").json()["chat_unread"] == before + 1
    muted = lukas.put(f"/api/chat/{dm['id']}/settings", json={"notify": "all", "mute_minutes": 60}).json()
    assert muted["muted"] is True
    assert lukas.get("/api/me/summary").json()["chat_unread"] == before
    mentions = [n for n in lukas.get("/api/notifications").json()["items"] if n["kind"] == "chat_mention"]
    anna.post(f"/api/chat/{dm['id']}/messages", json={"body": "@Lukas Schmid noch was", "mentions": [lukas_id]})
    assert len([n for n in lukas.get("/api/notifications").json()["items"] if n["kind"] == "chat_mention"]) == len(mentions)


def test_rich_presence_shows_details_only_to_who_may_see(anna, lukas, sara):
    space = anna.post("/api/spaces", json={"name": "Präsenz"}).json()
    anna.post(f"/api/spaces/{space['id']}/members", json={"user_id": _ids(anna)["Lukas Schmid"]})
    doc = anna.post(f"/api/spaces/{space['id']}/files/new", json={"kind": "docx", "name": "Budget"}).json()
    anna.get(f"/api/me/summary?activity=file:{doc['id']}")
    anna_id = _ids(lukas)["Anna Mayer"]
    seen = lukas.get(f"/api/presence?ids={anna_id}").json()[str(anna_id)]["activity"]
    assert seen["kind"] == "editing" and seen["label"].startswith("Budget") and seen["link"] == f"/office/{doc['id']}"
    hidden = sara.get(f"/api/presence?ids={anna_id}").json()[str(anna_id)]["activity"]
    assert hidden == {"kind": "editing", "label": "", "link": ""}
    assert anna.get("/api/me/summary?activity=evil").status_code == 422
