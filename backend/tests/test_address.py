"""Meetings behind a proxy (Cloudflare): the portal's name resolves to the proxy, which does not pass audio and video.
OfficeHub asks its own address who it is and gives the meeting servers the office's real public address."""

import dataclasses

from app import config
from app.services import address, meetings


def test_the_address_a_request_came_from(anna):
    # Through Cloudflare: the header it adds wins
    seen = anna.get("/api/address", headers={"CF-Connecting-IP": "81.10.20.30", "X-Forwarded-For": "62.40.9.9"})
    assert seen.json() == {"address": "81.10.20.30"}
    # Through a proxy chain: the first public address, office networks skipped
    seen = anna.get("/api/address", headers={"X-Forwarded-For": "192.168.1.20, 62.40.1.2, 10.0.0.2"})
    assert seen.json() == {"address": "62.40.1.2"}
    # Directly from inside the network: nothing to learn
    assert anna.get("/api/address", headers={"X-Forwarded-For": "172.18.0.5"}).json() == {"address": None}


def test_behind_a_proxy_meetings_use_the_offices_address(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_DIR", str(tmp_path))
    monkeypatch.setattr(address, "_learned", None)
    monkeypatch.setattr(address, "_resolve", lambda host: "104.21.88.146")  # the proxy
    asked = []
    monkeypatch.setattr(address, "_ask", lambda url: asked.append(url) or "81.10.20.30")
    assert address.check("https://office.example.com", wait=0) == "81.10.20.30"
    assert asked == ["https://office.example.com/api/address"]
    assert (tmp_path / "public_ip").read_text() == "81.10.20.30"
    assert (tmp_path / "turn_host").read_text() == "81.10.20.30"
    assert (tmp_path / "address_ready").exists()

    # The browsers' relay is reached by that address, not by the proxied name
    monkeypatch.setattr(meetings, "settings", dataclasses.replace(config.settings, turn_secret="s3cret", ice_servers=()))
    urls = meetings.ice_servers("anna")[0]["urls"]
    assert urls[1] == "turn:81.10.20.30:3478?transport=udp"


def test_without_a_proxy_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_DIR", str(tmp_path))
    monkeypatch.setattr(address, "_learned", None)
    monkeypatch.setattr(address, "_resolve", lambda host: "81.10.20.30")
    monkeypatch.setattr(address, "_ask", lambda url: "81.10.20.30")  # the name already reaches the office
    assert address.check("https://office.example.com", wait=0) is None
    assert not (tmp_path / "turn_host").exists()
    assert (tmp_path / "address_ready").exists()

    # The proxy cannot be reached (yet): the meeting servers do not wait forever
    monkeypatch.setattr(address, "_resolve", lambda host: "104.21.88.146")
    tries = []
    monkeypatch.setattr(address, "_ask", lambda url: tries.append(url) and None)
    assert address.check("https://office.example.com", tries=3, wait=0) is None
    assert len(tries) == 3 and address.learned() is None
