"""Company login: the sign-in button's two steps and the settings under Administration → Company login."""

import re
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..deps import DB, Admin
from ..errors import ApiError
from ..services import sso
from ..services.audit import audit
from ..services.settings import set_setting
from .auth import open_session

router = APIRouter(tags=["auth"])

STATE_COOKIE = "oh_sso"
ORIGIN = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+$")


def _to_login(code: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?sso={quote(code)}", status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/api/auth/sso")
    return response


@router.get("/api/auth/sso/start")
def sso_start(request: Request, db: DB, origin: str = Query(...)) -> RedirectResponse:
    """The browser's own address decides where the server sends it back (it must be registered there)."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if not ORIGIN.match(origin) or (urlsplit(origin).hostname or "").lower() != host:
        return _to_login("failed")
    try:
        url, state = sso.start(db, f"{origin}/api/auth/sso/callback")
    except sso.SsoError as e:
        return _to_login(e.code)
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(STATE_COOKIE, state, max_age=sso.STATE_SECONDS, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", path="/api/auth/sso")
    return response


@router.get("/api/auth/sso/callback")
def sso_callback(request: Request, db: DB, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    if error:
        return _to_login("denied")
    if not state or not code or request.cookies.get(STATE_COOKIE) != state:
        return _to_login("expired")
    try:
        user = sso.finish(db, state, code)
    except sso.SsoError as e:
        db.rollback()
        return _to_login(e.code)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/api/auth/sso")
    open_session(db, user, response)
    return response


class SsoSettings(BaseModel):
    enabled: bool = False
    issuer: str = Field("", max_length=500)
    client_id: str = Field("", max_length=255)
    # Empty when saving = keep the stored secret
    client_secret: str = Field("", max_length=500)
    label: str = Field("", max_length=60)
    create_users: bool = True
    trust_email: bool = False
    admin_group: str = Field("", max_length=120)
    manager_group: str = Field("", max_length=120)


class SsoSettingsOut(SsoSettings):
    has_secret: bool


def _out(db: DB) -> SsoSettingsOut:
    o = sso.options(db)
    return SsoSettingsOut(**{**o, "client_secret": ""}, has_secret=bool(o["client_secret"]))


@router.get("/api/admin/sso", response_model=SsoSettingsOut)
def get_sso(user: Admin, db: DB) -> SsoSettingsOut:
    return _out(db)


@router.put("/api/admin/sso", response_model=SsoSettingsOut)
def save_sso(body: SsoSettings, user: Admin, db: DB) -> SsoSettingsOut:
    data = body.model_dump()
    data["issuer"] = data["issuer"].strip().rstrip("/")
    data = {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}
    if not data["client_secret"]:
        data["client_secret"] = sso.options(db)["client_secret"]
    if data["enabled"]:
        if not data["issuer"].startswith(("https://", "http://")):
            raise ApiError(422, "sso_issuer", "Please enter the address of the company login server.")
        if not data["client_id"]:
            raise ApiError(422, "sso_client", "Please enter the client ID.")
        sso.discovery(data["issuer"])  # reachable and really an OpenID Connect server
    set_setting(db, "sso", data)
    audit(db, user, "settings_updated", "sso", enabled=data["enabled"], issuer=data["issuer"], create_users=data["create_users"])
    db.commit()
    return _out(db)
