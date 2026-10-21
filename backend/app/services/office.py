"""Editing office files in the browser with your own Collabora Online or ONLYOFFICE Docs server.

Both servers run next to OfficeHub (same Docker network) and are reached in the browser through the
frontend's web server under /collabora/ and /onlyoffice/, so the portal never talks to an outside service.

- Collabora uses WOPI: it fetches and saves the file through /wopi/files/<id> on the backend.
- ONLYOFFICE downloads the file from /office-hooks/onlyoffice/file/<id> and reports changes to
  /office-hooks/onlyoffice/callback/<id>. Requests in both directions are signed with JWT.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.request
from functools import lru_cache
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from ..config import settings
from ..errors import ApiError
from .settings import get_setting, set_setting

ENGINES = ("collabora", "onlyoffice")
TOKEN_HOURS = 10

# File types each editor can change (others open read-only or not at all)
EDITABLE = {
    "collabora": {"docx", "xlsx", "pptx", "odt", "ods", "odp", "doc", "xls", "ppt", "rtf", "csv"},
    "onlyoffice": {"docx", "xlsx", "pptx", "odt", "ods", "odp", "csv", "rtf", "doc", "xls", "ppt"},
}
ONLYOFFICE_KIND = {
    "docx": "word", "doc": "word", "odt": "word", "rtf": "word", "txt": "word",
    "xlsx": "cell", "xls": "cell", "ods": "cell", "csv": "cell",
    "pptx": "slide", "ppt": "slide", "odp": "slide",
}


def available() -> list[str]:
    return [e for e, url in (("collabora", settings.collabora_url), ("onlyoffice", settings.onlyoffice_url)) if url]


def default_engine(db: Session) -> str | None:
    engines = available()
    if not engines:
        return None
    chosen = get_setting(db, "office", {}).get("engine")
    return chosen if chosen in engines else engines[0]


# ---------- signed access tokens for the office servers ----------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key(db: Session) -> bytes:
    key = get_setting(db, "office_key", None)
    if not key:
        key = secrets.token_urlsafe(48)
        set_setting(db, "office_key", key)
        db.commit()
    return key.encode()


def make_token(db: Session, file_id: int, user_id: int, can_write: bool, origin: str = "") -> tuple[str, int]:
    """Token the office server sends back on every request; (token, expiry in ms since 1970)."""
    expires = int(time.time()) + TOKEN_HOURS * 3600
    payload = _b64(json.dumps({"f": file_id, "u": user_id, "w": can_write, "o": origin, "e": expires}).encode())
    signature = _b64(hmac.new(_key(db), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}", expires * 1000


def read_token(db: Session, token: str, file_id: int) -> dict:
    try:
        payload, signature = token.split(".", 1)
        expected = _b64(hmac.new(_key(db), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        raise ApiError(401, "invalid_token", "Invalid access token.") from None
    if data.get("f") != file_id or data.get("e", 0) < time.time():
        raise ApiError(401, "invalid_token", "Invalid access token.")
    return data


# ---------- JWT (HS256) for ONLYOFFICE ----------


def jwt_encode(payload: dict, secret: str) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def jwt_decode(token: str, secret: str) -> dict:
    try:
        header, body, signature = token.split(".")
        expected = _b64(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected) or json.loads(_unb64(header)).get("alg") != "HS256":
            raise ValueError
        data = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        raise ApiError(401, "invalid_token", "Invalid token.") from None
    if "exp" in data and data["exp"] < time.time():
        raise ApiError(401, "invalid_token", "Token expired.")
    return data


# ---------- Collabora discovery ----------


@lru_cache(maxsize=4)
def _discovery(url: str, _bucket: int) -> dict[str, dict[str, str]]:
    """{extension: {action: urlsrc}} from Collabora's discovery file (cached for an hour)."""
    with urllib.request.urlopen(f"{url}/hosting/discovery", timeout=10) as response:  # noqa: S310 - own server
        root = ElementTree.fromstring(response.read())
    actions: dict[str, dict[str, str]] = {}
    for action in root.iter("action"):
        ext, name, urlsrc = action.get("ext"), action.get("name"), action.get("urlsrc")
        if ext and name and urlsrc:
            actions.setdefault(ext, {})[name] = urlsrc
    return actions


def collabora_action(file_type: str, can_write: bool) -> str:
    """Path (with query) of the editor page for this file type, as seen from the browser."""
    if not settings.collabora_url:
        raise ApiError(409, "office_unavailable", "Office editing is not set up.")
    try:
        actions = _discovery(settings.collabora_url, int(time.time() // 3600)).get(file_type, {})
    except OSError:
        raise ApiError(503, "office_unreachable", "The office server cannot be reached right now.") from None
    urlsrc = actions.get("edit" if can_write else "view") or actions.get("view") or actions.get("edit")
    if not urlsrc:
        raise ApiError(409, "office_type", "This file type cannot be opened in the office editor.")
    # Keep only path and query: the browser reaches Collabora through the portal (/collabora/...).
    path = re.sub(r"^[a-z]+://[^/]+", "", urlsrc)
    if not path.startswith("/collabora/"):
        path = "/collabora" + path
    return path


def onlyoffice_download_url(url: str) -> str:
    """ONLYOFFICE reports links as the browser sees them (…/onlyoffice/…); fetch them inside the network."""
    if not settings.onlyoffice_url:
        raise ApiError(409, "office_unavailable", "Office editing is not set up.")
    path = re.sub(r"^[a-z]+://[^/]+", "", url)
    path = re.sub(r"^/onlyoffice(?=/)", "", path)
    return settings.onlyoffice_url + path
