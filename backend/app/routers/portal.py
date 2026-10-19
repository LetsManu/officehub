"""Portal-wide settings managed by HR: quick links, dashboard tiles and section contacts."""

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select

from ..deps import DB, Admin, CurrentUser
from ..errors import not_found
from ..models import QuickLink, User
from ..schemas import DEFAULT_TILES, TileKey
from ..services.audit import audit
from ..services.security import required_2fa_roles
from ..services.settings import get_setting, set_setting

router = APIRouter(prefix="/api/portal", tags=["portal"])

SECTIONS = ("dashboard", "requests", "documents", "announcements", "directory", "rooms", "visitors", "time")
LINK_ICONS = ("link", "book", "graduation", "clock", "lifebuoy", "workflow", "tasks", "chart", "mail")

Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^https?://[^\s<>\"']+$")]


class LinkIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    url: Url
    icon: Annotated[str, StringConstraints(max_length=20)] = "link"
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    sort_order: Annotated[int, Field(ge=0, le=1000)] = 0
    active: bool = True


class LinkOut(LinkIn):
    id: int


class Contact(BaseModel):
    id: int
    full_name: str
    email: str
    phone: str


class PortalSettings(BaseModel):
    dashboard_tiles: list[str]
    section_contacts: dict[str, Contact]
    require_2fa_roles: list[str] = []


class PortalSettingsIn(BaseModel):
    dashboard_tiles: Annotated[list[TileKey], Field(min_length=1, max_length=8)] | None = None
    # section -> person id (None removes the contact)
    section_contacts: dict[str, int | None] | None = None
    require_2fa_roles: list[Literal["employee", "manager", "admin"]] | None = None


_get = get_setting
_set = set_setting


def _settings(db) -> PortalSettings:
    contacts: dict[str, Contact] = {}
    for section, person_id in _get(db, "section_contacts", {}).items():
        person = db.get(User, person_id)
        if section in SECTIONS and person is not None and person.is_active:
            contacts[section] = Contact(id=person.id, full_name=person.full_name, email=person.email, phone=person.phone)
    return PortalSettings(
        dashboard_tiles=_get(db, "dashboard_tiles", DEFAULT_TILES),
        section_contacts=contacts,
        require_2fa_roles=required_2fa_roles(db),
    )


@router.get("/settings", response_model=PortalSettings)
def get_settings(user: CurrentUser, db: DB) -> PortalSettings:
    return _settings(db)


@router.put("/settings", response_model=PortalSettings)
def update_settings(body: PortalSettingsIn, user: Admin, db: DB) -> PortalSettings:
    if body.dashboard_tiles is not None:
        _set(db, "dashboard_tiles", list(dict.fromkeys(body.dashboard_tiles)))
    if body.section_contacts is not None:
        contacts = _get(db, "section_contacts", {})
        for section, person_id in body.section_contacts.items():
            if section not in SECTIONS:
                continue
            if person_id is None:
                contacts.pop(section, None)
            elif db.get(User, person_id) is not None:
                contacts[section] = person_id
        _set(db, "section_contacts", contacts)
    if body.require_2fa_roles is not None:
        _set(db, "security", {"require_2fa_roles": sorted(set(body.require_2fa_roles))})
    audit(db, user, "settings_updated", ", ".join(body.model_dump(exclude_unset=True)))
    db.commit()
    return _settings(db)


@router.get("/links", response_model=list[LinkOut])
def list_links(user: CurrentUser, db: DB, include_inactive: bool = False) -> list[QuickLink]:
    query = select(QuickLink)
    if not (include_inactive and user.is_admin):
        query = query.where(QuickLink.active.is_(True))
    return list(db.scalars(query.order_by(QuickLink.sort_order, QuickLink.title)))


def _clean_icon(icon: str) -> str:
    return icon if icon in LINK_ICONS else "link"


@router.post("/links", response_model=LinkOut, status_code=201)
def create_link(body: LinkIn, user: Admin, db: DB) -> QuickLink:
    link = QuickLink(**body.model_dump() | {"icon": _clean_icon(body.icon)})
    db.add(link)
    db.commit()
    return link


@router.patch("/links/{link_id}", response_model=LinkOut)
def update_link(link_id: int, body: LinkIn, user: Admin, db: DB) -> QuickLink:
    link = db.get(QuickLink, link_id)
    if link is None:
        raise not_found("Link")
    for field, value in (body.model_dump() | {"icon": _clean_icon(body.icon)}).items():
        setattr(link, field, value)
    db.commit()
    return link


@router.delete("/links/{link_id}", status_code=204)
def delete_link(link_id: int, user: Admin, db: DB) -> None:
    link = db.get(QuickLink, link_id)
    if link is None:
        raise not_found("Link")
    db.delete(link)
    db.commit()
