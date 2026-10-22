"""Company login (single sign-on) with the company's own OpenID Connect server, e.g. Authentik or Keycloak.

HR enters the server's address, client ID and secret under Administration → Company login; the sign-in page then
shows "Sign in with company account". The flow is the authorization code flow with PKCE. The ID token comes straight
from the token endpoint over TLS, so it is checked by issuer, audience, nonce and expiry (OpenID Connect Core 3.1.3.7)
without a crypto library.

People are found by the server's subject ID, else by e-mail address (only when the server confirms the address, or
HR chose to trust it), and created as employees when they are new (unless HR switched that off). Optional group names
make people managers or HR / admins and are checked at every sign-in.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import User
from ..security import hash_password
from .settings import get_setting

DEFAULTS = {
    "enabled": False, "issuer": "", "client_id": "", "client_secret": "", "label": "",
    "create_users": True, "trust_email": False, "admin_group": "", "manager_group": "",
}
STATE_SECONDS = 600
TIMEOUT = 8
# state -> (nonce, PKCE verifier, redirect URI, expires); one backend process, and only for a few minutes
_pending: dict[str, tuple[str, str, str, float]] = {}


class SsoError(Exception):
    """Ends the sign-in with a message on the sign-in page (`code` is translated there as errors.sso_<code>)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sign_in_origins(db: Session) -> list[str]:
    """Where the company login page lives: the Windows and Android apps open it in their own window (apps/), everything
    else from other addresses goes to the browser."""
    from urllib.parse import urlsplit

    def origin(url: str) -> str | None:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") and parts.netloc else None

    o = options(db)
    found = [origin(o["issuer"])]
    try:
        found.append(origin(discovery(o["issuer"])["authorization_endpoint"]))
    except Exception:  # noqa: BLE001 - the login server is unreachable right now: the issuer is enough
        pass
    return sorted({f for f in found if f})


def options(db: Session) -> dict:
    stored = get_setting(db, "sso", {}) or {}
    return {**DEFAULTS, **{k: stored[k] for k in DEFAULTS if k in stored}}


def enabled(db: Session) -> bool:
    o = options(db)
    return bool(o["enabled"] and o["issuer"] and o["client_id"])


def _get_json(url: str, data: dict | None = None, headers: dict | None = None) -> dict:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - the company's own server
        return json.loads(response.read().decode())


@lru_cache(maxsize=4)
def _discovery(issuer: str, _hour: int) -> dict:
    return _get_json(f"{issuer.rstrip('/')}/.well-known/openid-configuration")


def discovery(issuer: str) -> dict:
    """The server's endpoints; raises ApiError when it cannot be reached or is not an OpenID Connect server."""
    try:
        data = _discovery(issuer.strip(), int(time.time() // 3600))
    except (OSError, ValueError):
        _discovery.cache_clear()
        raise ApiError(502, "sso_server", "The company login server cannot be reached at this address.") from None
    if not all(k in data for k in ("issuer", "authorization_endpoint", "token_endpoint")):
        _discovery.cache_clear()
        raise ApiError(502, "sso_server", "This address is not an OpenID Connect server.")
    return data


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def start(db: Session, redirect_uri: str) -> tuple[str, str]:
    """(URL to send the browser to, state that binds the answer to this browser)."""
    if not enabled(db):
        raise SsoError("not_configured")
    o = options(db)
    try:
        endpoints = discovery(o["issuer"])
    except ApiError:
        raise SsoError("unreachable") from None
    now = time.time()
    for key in [k for k, v in _pending.items() if v[3] < now]:
        _pending.pop(key, None)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    _pending[state] = (nonce, verifier, redirect_uri, now + STATE_SECONDS)
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": o["client_id"], "redirect_uri": redirect_uri,
        "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
    })
    return f"{endpoints['authorization_endpoint']}?{query}", state


def _claims(id_token: str) -> dict:
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise SsoError("failed") from None


def finish(db: Session, state: str, code: str) -> User:
    """Exchange the code, check the ID token and find (or create) the person."""
    pending = _pending.pop(state, None)
    if pending is None or pending[3] < time.time():
        raise SsoError("expired")
    nonce, verifier, redirect_uri, _ = pending
    o = options(db)
    try:
        endpoints = discovery(o["issuer"])
        tokens = _get_json(endpoints["token_endpoint"], {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": o["client_id"], "client_secret": o["client_secret"], "code_verifier": verifier,
        })
    except (ApiError, OSError, ValueError):
        raise SsoError("failed") from None
    claims = _claims(tokens.get("id_token", ""))
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if (claims.get("iss", "").rstrip("/") != endpoints["issuer"].rstrip("/") or o["client_id"] not in audiences
            or claims.get("nonce") != nonce or float(claims.get("exp", 0)) < time.time() - 60 or not claims.get("sub")):
        raise SsoError("failed")
    if "email" not in claims and tokens.get("access_token") and endpoints.get("userinfo_endpoint"):
        try:
            info = _get_json(endpoints["userinfo_endpoint"], headers={"Authorization": f"Bearer {tokens['access_token']}"})
            if info.get("sub") == claims["sub"]:
                claims = {**info, **claims}
        except (OSError, ValueError):
            pass
    return _person(db, o, claims)


def _other_admins(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active, User.id != user.id)) or 0


def _person(db: Session, o: dict, claims: dict) -> User:
    sub = str(claims["sub"])[:255]
    email = str(claims.get("email") or "").strip().lower()
    user = db.scalar(select(User).where(User.sso_subject == sub))
    if user is None and email:
        if not (claims.get("email_verified") is True or o["trust_email"]):
            raise SsoError("email_unverified")
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is not None:
            user.sso_subject = sub
    if user is None:
        if not o["create_users"]:
            raise SsoError("no_account")
        if not email:
            raise SsoError("no_email")
        first = str(claims.get("given_name") or "").strip()
        last = str(claims.get("family_name") or "").strip()
        if not first and not last:
            parts = str(claims.get("name") or email.split("@")[0]).strip().split(" ", 1)
            first, last = parts[0], parts[1] if len(parts) > 1 else ""
        # No password of their own: they sign in with the company account (HR can set one if ever needed)
        user = User(email=email[:254], first_name=first[:60] or email[:60], last_name=last[:60],
                    password_hash=hash_password(secrets.token_urlsafe(32)), role="employee", is_active=True, sso_subject=sub)
        db.add(user)
    if not user.is_active:
        raise SsoError("inactive")
    groups = claims.get("groups")
    if isinstance(groups, list) and (o["admin_group"] or o["manager_group"]):
        names = {str(g) for g in groups}
        if o["admin_group"] and o["admin_group"] in names:
            user.role = "admin"
        elif o["manager_group"] and o["manager_group"] in names:
            user.role = "manager"
        elif user.role == "manager" or (user.role == "admin" and _other_admins(db, user)):
            user.role = "employee"  # never the last admin, so nobody is locked out
    db.flush()
    return user
