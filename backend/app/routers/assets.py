"""Equipment register: which laptop, phone, key or card each person has, with history."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, not_found
from ..models import Asset, AssetEvent, User
from ..schemas import UserBrief, UtcDateTime
from ..services.audit import audit

router = APIRouter(prefix="/api/assets", tags=["equipment"])

Kind = Literal["laptop", "phone", "monitor", "headset", "key", "card", "vehicle", "other"]
Status = Literal["in_stock", "assigned", "repair", "retired"]


class AssetIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    kind: Kind = "other"
    serial: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""


class AssetUpdate(AssetIn):
    status: Literal["in_stock", "repair", "retired"] | None = None


class AssignIn(BaseModel):
    person_id: int
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class ReturnIn(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class EventOut(BaseModel):
    action: str
    person_name: str | None
    actor_name: str
    note: str
    created_at: UtcDateTime


class AssetOut(BaseModel):
    id: int
    name: str
    kind: str
    serial: str
    notes: str
    status: str
    assigned_to: UserBrief | None
    assigned_at: date | None
    history: list[EventOut] = []


def _out(db: Session, asset: Asset, with_history: bool = False) -> AssetOut:
    history = []
    if with_history:
        events = db.scalars(select(AssetEvent).where(AssetEvent.asset_id == asset.id).order_by(AssetEvent.created_at.desc()))
        history = [
            EventOut(action=e.action, person_name=e.person.full_name if e.person else None, actor_name=e.actor.full_name,
                     note=e.note, created_at=e.created_at)
            for e in events
        ]
    return AssetOut(
        id=asset.id, name=asset.name, kind=asset.kind, serial=asset.serial, notes=asset.notes, status=asset.status,
        assigned_to=UserBrief.model_validate(asset.assigned_to) if asset.assigned_to else None,
        assigned_at=asset.assigned_at, history=history,
    )


def _get(db: Session, asset_id: int) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise not_found("Item")
    return asset


def return_asset(db: Session, asset: Asset, actor: User, note: str = "") -> None:
    """Back into stock (also used when an offboarding 'return' task is ticked)."""
    if asset.status != "assigned":
        return
    db.add(AssetEvent(asset_id=asset.id, action="returned", person_id=asset.assigned_to_id, actor_id=actor.id, note=note))
    audit(db, actor, "asset_returned", asset.name, person=asset.assigned_to.full_name if asset.assigned_to else "")
    asset.status, asset.assigned_to_id, asset.assigned_at = "in_stock", None, None


@router.get("/mine", response_model=list[AssetOut])
def mine(user: CurrentUser, db: DB) -> list[AssetOut]:
    rows = db.scalars(select(Asset).where(Asset.assigned_to_id == user.id).order_by(Asset.kind, Asset.name))
    return [_out(db, a) for a in rows]


@router.get("", response_model=list[AssetOut])
def list_assets(
    user: Admin, db: DB, q: str | None = Query(None, max_length=100), status: Status | None = None, person_id: int | None = None
) -> list[AssetOut]:
    query = select(Asset)
    if status:
        query = query.where(Asset.status == status)
    if person_id:
        query = query.where(Asset.assigned_to_id == person_id)
    if term := (q or "").strip():
        pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(Asset.name.ilike(pattern, escape="\\"), Asset.serial.ilike(pattern, escape="\\")))
    return [_out(db, a) for a in db.scalars(query.order_by(Asset.status, Asset.kind, Asset.name))]


@router.post("", response_model=AssetOut, status_code=201)
def create_asset(body: AssetIn, user: Admin, db: DB) -> AssetOut:
    asset = Asset(**body.model_dump())
    db.add(asset)
    db.flush()
    db.add(AssetEvent(asset_id=asset.id, action="created", actor_id=user.id))
    audit(db, user, "asset_created", asset.name, serial=asset.serial)
    db.commit()
    return _out(db, asset, True)


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: int, user: Admin, db: DB) -> AssetOut:
    return _out(db, _get(db, asset_id), True)


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: int, body: AssetUpdate, user: Admin, db: DB) -> AssetOut:
    asset = _get(db, asset_id)
    changes = body.model_dump(exclude_none=True)
    new_status = changes.pop("status", None)
    for field, value in changes.items():
        setattr(asset, field, value)
    if new_status and new_status != asset.status:
        if asset.status == "assigned":
            return_asset(db, asset, user)
        asset.status = new_status
        db.add(AssetEvent(asset_id=asset.id, action=new_status, actor_id=user.id))
    audit(db, user, "asset_updated", asset.name)
    db.commit()
    return _out(db, asset, True)


@router.post("/{asset_id}/assign", response_model=AssetOut)
def assign(asset_id: int, body: AssignIn, user: Admin, db: DB) -> AssetOut:
    asset = _get(db, asset_id)
    if asset.status not in ("in_stock", "assigned"):
        raise ApiError(409, "asset_unavailable", "This item is in repair or retired.")
    person = db.get(User, body.person_id)
    if person is None or not person.is_active:
        raise ApiError(422, "person_invalid", "Please choose active people.")
    if asset.status == "assigned":
        return_asset(db, asset, user)
    asset.status, asset.assigned_to_id, asset.assigned_at = "assigned", person.id, date.today()
    db.add(AssetEvent(asset_id=asset.id, action="assigned", person_id=person.id, actor_id=user.id, note=body.note))
    audit(db, user, "asset_assigned", asset.name, person=person.full_name)
    db.commit()
    db.refresh(asset)
    return _out(db, asset, True)


@router.post("/{asset_id}/return", response_model=AssetOut)
def give_back(asset_id: int, body: ReturnIn, user: Admin, db: DB) -> AssetOut:
    asset = _get(db, asset_id)
    if asset.status != "assigned":
        raise ApiError(409, "asset_not_assigned", "This item is not handed out.")
    return_asset(db, asset, user, body.note)
    db.commit()
    return _out(db, asset, True)
