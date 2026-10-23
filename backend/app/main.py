"""OfficeHub API."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import seed
from .config import settings
from .db import Base, SessionLocal, add_missing_columns, engine
from .errors import ApiError
from .services import sso as sso_service
from .services import backup
from .services import meetings as meetings_service
from .routers import (
    admin,
    apps,
    announcements,
    assets,
    auth,
    boards,
    branding,
    calendar,
    chat,
    backups,
    craft,
    sso,
    directory,
    documents,
    help,
    holidays,
    ideas,
    keys,
    meetings,
    notifications,
    office,
    onboarding,
    planning,
    presence,
    personal,
    portal,
    profile,
    reports,
    requests,
    reviews,
    rooms,
    rtc,
    spaces,
    surveys,
    team,
    time_tracking,
    trainings,
    visitors,
    sync,
    webdav,
    wiki,
)

logger = logging.getLogger("officehub")

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "OfficeHub"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    add_missing_columns()
    with SessionLocal() as db:
        seed.ensure_initial_data(db)
    nightly = asyncio.create_task(backup.nightly())
    yield
    nightly.cancel()


app = FastAPI(title="OfficeHub API", version=settings.app_version, lifespan=lifespan)


@app.middleware("http")
async def csrf_and_headers(request: Request, call_next):
    # Browsers cannot send this custom header cross-site without a CORS preflight,
    # which this API never allows. Together with SameSite cookies this blocks CSRF.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
        if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return JSONResponse({"detail": "Missing request header.", "code": "csrf"}, status_code=403)
    # The name people use for the portal (meetings: the relay is reached the same way)
    meetings_service.request_host.set(request.headers.get("host"))
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    body = {"detail": exc.detail, "code": exc.code}
    if field := getattr(exc, "field", None):
        body["field"] = field
    return JSONResponse(body, status_code=exc.status_code)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail, "code": "http_error"}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = [str(p) for p in first.get("loc", []) if p not in ("body", "query", "path")]
    return JSONResponse(
        {
            "detail": "Some information is missing or not valid. Please check the highlighted fields.",
            "code": "validation",
            "field": location[0] if location else None,
            "errors": [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")} for e in errors],
        },
        status_code=422,
    )


@app.get("/health", include_in_schema=False)
@app.get("/api/health", tags=["system"])
def health() -> dict:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/config", tags=["system"])
def public_config() -> dict:
    """Public settings the sign-in page needs. Demo accounts are only listed in demo mode."""
    config: dict = {
        "demo_mode": settings.demo_mode,
        "max_upload_mb": settings.max_upload_mb,
        "version": settings.app_version,
        "mail_enabled": settings.mail_enabled,
        "meetings_enabled": True,
        # The Windows and Android apps (apps/): installer and APK attached to every release
        "apps": {"windows": f"{settings.app_download_url}OfficeHub-Setup.exe",
                 "android": f"{settings.app_download_url}OfficeHub.apk"},
    }
    with SessionLocal() as db:
        if sso_service.enabled(db):
            config["sso"] = {"label": sso_service.options(db)["label"], "origins": sso_service.sign_in_origins(db)}
    if settings.demo_mode:
        config["demo_accounts"] = seed.demo_accounts()
        config["demo_password"] = seed.DEMO_PASSWORD
    return config


for router in (
    auth.router,
    requests.router,
    announcements.router,
    documents.router,
    profile.router,
    admin.router,
    directory.router,
    rooms.router,
    visitors.router,
    reviews.router,
    onboarding.router,
    portal.router,
    reports.router,
    notifications.router,
    team.router,
    personal.router,
    help.router,
    branding.router,
    calendar.router,
    holidays.router,
    time_tracking.router,
    surveys.router,
    ideas.router,
    trainings.router,
    assets.router,
    planning.router,
    presence.router,
    spaces.router,
    boards.router,
    chat.router,
    wiki.router,
    meetings.router,
    rtc.router,
    office.router,
    office.hooks,
    webdav.router,
    craft.router,
    sso.router,
    backups.router,
    keys.router,
    apps.router,
    sync.router,
):
    app.include_router(router)
