"""Company branding: name, logo and accent colour. Readable without sign-in for the login page."""

import re
from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, StringConstraints, field_validator

from ..deps import DB, Admin
from ..errors import ApiError, not_found
from ..files import MIME_TYPES, delete_quietly, resolve, save_upload
from ..services.audit import audit
from ..services.settings import get_setting, set_setting

router = APIRouter(prefix="/api/branding", tags=["branding"])

DEFAULT_ACCENT = "#1D4ED8"
LOGO_TYPES = {"png", "jpg", "jpeg"}
MAX_LOGO_BYTES = 1024 * 1024


def _luminance(hex_color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_with_white(hex_color: str) -> float:
    return 1.05 / (_luminance(hex_color) + 0.05)


class Branding(BaseModel):
    company_name: str
    accent_color: str
    logo_version: str | None


class BrandingIn(BaseModel):
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] = ""
    accent_color: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^#[0-9a-fA-F]{6}$")] = DEFAULT_ACCENT

    @field_validator("accent_color")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


def current_branding(db) -> Branding:
    data = get_setting(db, "branding", {})
    logo = data.get("logo_path")
    return Branding(
        company_name=data.get("company_name", ""),
        accent_color=data.get("accent_color", DEFAULT_ACCENT),
        logo_version=re.sub(r"\W", "", logo.rsplit("/", 1)[-1].split(".")[0])[:12] if logo else None,
    )


@router.get("", response_model=Branding)
def get_branding(db: DB) -> Branding:
    return current_branding(db)


@router.put("", response_model=Branding)
def update_branding(body: BrandingIn, user: Admin, db: DB) -> Branding:
    # Buttons use white text on the accent colour, so it must stay readable.
    if contrast_with_white(body.accent_color) < 4.5:
        error = ApiError(422, "accent_contrast", "This colour is too light for white text. Please choose a darker one.")
        error.field = "accent_color"  # type: ignore[attr-defined]
        raise error
    data = get_setting(db, "branding", {})
    data.update(company_name=body.company_name, accent_color=body.accent_color)
    set_setting(db, "branding", data)
    audit(db, user, "branding_updated", body.company_name or "-", accent_color=body.accent_color)
    db.commit()
    return current_branding(db)


@router.post("/logo", response_model=Branding)
async def upload_logo(user: Admin, db: DB, file: UploadFile = File(...)) -> Branding:
    stored = await save_upload(file, LOGO_TYPES, "branding")
    if stored.size > MAX_LOGO_BYTES:
        delete_quietly(stored.relative_path)
        raise ApiError(422, "file_too_large", "The logo can be at most 1 MB.")
    data = get_setting(db, "branding", {})
    old = data.get("logo_path")
    data["logo_path"] = stored.relative_path
    set_setting(db, "branding", data)
    audit(db, user, "branding_updated", "logo")
    db.commit()
    delete_quietly(old)
    return current_branding(db)


@router.delete("/logo", response_model=Branding)
def delete_logo(user: Admin, db: DB) -> Branding:
    data = get_setting(db, "branding", {})
    old = data.pop("logo_path", None)
    set_setting(db, "branding", data)
    audit(db, user, "branding_updated", "logo removed")
    db.commit()
    delete_quietly(old)
    return current_branding(db)


@router.get("/logo")
def logo(db: DB) -> FileResponse:
    path = get_setting(db, "branding", {}).get("logo_path")
    if not path:
        raise not_found("Logo")
    file_type = path.rsplit(".", 1)[-1]
    return FileResponse(
        resolve(path), media_type=MIME_TYPES.get(file_type, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# Shortcuts in the installed app's menu (long-press or right-click on its icon), in the reader's language.
SHORTCUTS = {
    "de": [("Chat", "/chat"), ("Kalender", "/calendar"), ("Dateien", "/files"), ("Neuer Antrag", "/requests/new")],
    "en": [("Chat", "/chat"), ("Calendar", "/calendar"), ("Files", "/files"), ("New request", "/requests/new")],
}
DESCRIPTION = {
    "de": "Mitarbeiterportal: Anträge, Dokumente, Chat, Besprechungen und mehr.",
    "en": "Employee portal: requests, documents, chat, meetings and more.",
}


@router.get("/manifest.webmanifest")
def manifest(request: Request, db: DB) -> JSONResponse:
    """The web app manifest: the installed app carries the company's name and colour, offers shortcuts and takes
    files and text shared from other apps (they open on /share)."""
    branding = current_branding(db)
    lang = "de" if request.headers.get("accept-language", "de").lower().startswith("de") else "en"
    name = branding.company_name or "OfficeHub"
    icons = [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ]
    body = {
        "id": "/",
        "name": name,
        "short_name": name[:12],
        "description": DESCRIPTION[lang],
        "lang": lang,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f6fa",
        "theme_color": branding.accent_color,
        "icons": icons,
        "shortcuts": [
            {"name": label, "url": url, "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"}]}
            for label, url in SHORTCUTS[lang]
        ],
        "share_target": {
            "action": "/share",
            "method": "POST",
            "enctype": "multipart/form-data",
            "params": {"title": "title", "text": "text", "url": "url", "files": [{"name": "files", "accept": ["*/*"]}]},
        },
    }
    return JSONResponse(body, media_type="application/manifest+json", headers={"Cache-Control": "no-cache", "Vary": "Accept-Language"})
