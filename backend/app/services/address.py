"""The server's public address for meetings when the portal's name points at a proxy (Cloudflare and the like).

The videobridge and the relay must tell browsers outside the office an address that reaches this server. Normally
that is what the portal's name resolves to. Behind a proxy such as Cloudflare the name resolves to the proxy instead,
which forwards web pages but not audio and video, so people on other networks saw black video and heard nothing.

OfficeHub then asks its own portal address who it is: the request goes out through the company's internet line and
comes back through the proxy, which tells the address it came from (CF-Connecting-IP, X-Forwarded-For). That is the
office's public address. Nothing is sent to any other service.

The address is checked again every ten minutes (a dynamic IP from the internet provider changes now and then); the
meeting servers restart by themselves when `/shared/public_ip` or `/shared/turn_host` change.

The meeting servers of the stack wait for this check on start (`/shared/address_ready`, at most about three
minutes) and then read `/shared/public_ip`; Jitsi tells browsers the relay by `/shared/turn_host` (the address,
since the name only reaches the proxy).
"""

import ipaddress
import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request

from ..config import _resolve, settings, share_public_address

logger = logging.getLogger("officehub")

READY = "address_ready"
TURN_HOST = "turn_host"  # the relay's address for Jitsi when the portal's name points at a proxy
TRIES = 18  # every 10 s: the frontend and the company's proxy may still be starting
WAIT = 10
RECHECK = 10 * 60  # the office's address can change (dynamic IP); the meeting servers restart when it does

_learned: str | None = None


def public(address: str | None) -> str | None:
    """`address` when it is a public IPv4 address (not an office network, loopback or similar)."""
    try:
        ip = ipaddress.ip_address((address or "").strip())
    except ValueError:
        return None
    return str(ip) if ip.version == 4 and ip.is_global else None


def seen(request: Request) -> str | None:
    """The public address a request came from, as the proxies in front of the portal report it."""
    for header in ("cf-connecting-ip", "true-client-ip"):
        if found := public(request.headers.get(header)):
            return found
    for hop in (request.headers.get("x-forwarded-for") or "").split(","):
        if found := public(hop):
            return found
    return public(request.client.host if request.client else None)


def client(request: Request) -> str:
    """Who is asking: the visitor's own address, also behind the company's reverse proxy and Cloudflare (the request
    reaches OfficeHub from the proxy, so its own address is the same for everyone). For limits and records only."""
    return seen(request) or (request.client.host if request.client else "unknown")


def learned() -> str | None:
    """The office's public address found through the proxy, if the portal is behind one."""
    return _learned


def _shared() -> Path:
    return Path(os.getenv("SHARED_DIR", "/shared"))


def _ask(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "OfficeHub"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310 - the portal's own address
            return public(json.loads(response.read(256)).get("address"))
    except (OSError, ValueError, AttributeError):
        return None


def _apply(found: str | None) -> None:
    """Remember the address found through the proxy and hand it to the meeting servers (`None`: no proxy)."""
    global _learned
    _learned = found
    if found:
        share_public_address(found)
    try:
        if not _shared().is_dir():
            return
        if found:
            (_shared() / TURN_HOST).write_text(found)
        else:
            (_shared() / TURN_HOST).unlink(missing_ok=True)
    except OSError:
        pass


def _detect(portal_url: str, tries: int, wait: float) -> tuple[str | None, str | None]:
    """(what the portal's name resolves to, the office's address seen through a proxy or `None`)."""
    resolved = _resolve(urlparse(portal_url).hostname)
    found = None
    if public(resolved):
        for attempt in range(tries):
            found = _ask(f"{portal_url}/api/address")
            if found or attempt == tries - 1:
                break
            time.sleep(wait)
    return resolved, (found if found and found != resolved else None)


def check(portal_url: str, tries: int = TRIES, wait: float = WAIT) -> str | None:
    """Ask the portal's own address who we are; the office's public address when the portal's name points elsewhere
    (a proxy). Marks the check as done for the meeting servers either way."""
    found = None
    try:
        _resolved, found = _detect(portal_url, tries, wait)
        if found:
            logger.info("The portal's name points at a proxy (%s); meetings use %s", _resolved, found)
        _apply(found)
    finally:
        try:
            if _shared().is_dir():
                (_shared() / READY).write_text("1")
        except OSError:
            pass
    return found


def recheck(portal_url: str) -> bool:
    """Look again (the office's address can change, e.g. a new address from the internet provider overnight). Hands a
    changed address to the meeting servers, which restart by themselves when it changes. True when it changed."""
    resolved, found = _detect(portal_url, 1, 0)
    if found is None and _learned and resolved:
        # The proxy did not answer this time: keep what we know rather than fall back to the proxy's address.
        return False
    before = (_learned, _current())
    if found:
        _apply(found)
    else:
        _apply(None)
        if public(resolved):
            share_public_address(resolved)
    changed = (_learned, _current()) != before
    if changed:
        logger.info("The office's public address changed; meetings now use %s", _current())
    return changed


def _current() -> str | None:
    try:
        return (_shared() / "public_ip").read_text().strip() or None
    except OSError:
        return None


def watch(portal_url: str, every: float = RECHECK) -> None:
    """First check on start, then look again every few minutes."""
    check(portal_url)
    while True:
        time.sleep(every)
        try:
            recheck(portal_url)
        except Exception:  # noqa: BLE001 - never stop watching
            logger.exception("Checking the public address failed")


def start() -> None:
    """Run the check in the background on start (the meeting servers wait for it)."""
    for name in (READY, TURN_HOST):
        try:
            (_shared() / name).unlink(missing_ok=True)
        except OSError:
            pass
    if os.getenv("PUBLIC_IP") or os.getenv("JITSI_PUBLIC_IP"):
        check("")  # set by hand: nothing to find out
        return
    threading.Thread(target=watch, args=(settings.portal_url,), daemon=True, name="public-address").start()
