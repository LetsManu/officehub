"""The server's public address for meetings when the portal's name points at a proxy (Cloudflare and the like).

The videobridge and the relay must tell browsers outside the office an address that reaches this server. Normally
that is what the portal's name resolves to. Behind a proxy such as Cloudflare the name resolves to the proxy instead,
which forwards web pages but not audio and video, so people on other networks saw black video and heard nothing.

OfficeHub then asks its own portal address who it is: the request goes out through the company's internet line and
comes back through the proxy, which tells the address it came from (CF-Connecting-IP, X-Forwarded-For). That is the
office's public address. Nothing is sent to any other service.

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


def check(portal_url: str, tries: int = TRIES, wait: float = WAIT) -> str | None:
    """Ask the portal's own address who we are; the office's public address when the portal's name points elsewhere
    (a proxy). Marks the check as done for the meeting servers either way."""
    global _learned
    found = None
    resolved = _resolve(urlparse(portal_url).hostname)
    try:
        if public(resolved):
            for attempt in range(tries):
                found = _ask(f"{portal_url}/api/address")
                if found or attempt == tries - 1:
                    break
                time.sleep(wait)
        if found and found != resolved:
            logger.info("The portal's name points at a proxy (%s); meetings use %s", resolved, found)
            _learned = found
            share_public_address(found)
            try:
                (_shared() / TURN_HOST).write_text(found)
            except OSError:
                pass
        else:
            found = None
    finally:
        try:
            if _shared().is_dir():
                (_shared() / READY).write_text("1")
        except OSError:
            pass
    return found


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
    threading.Thread(target=check, args=(settings.portal_url,), daemon=True, name="public-address").start()
