"""Required trainings (e.g. fire safety, data protection) with due dates, repeats and certificates."""

import csv
import io
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, not_found
from ..files import MIME_TYPES, RECEIPT_TYPES, resolve, save_upload
from ..models import Training, TrainingRecord, User
from ..schemas import UserBrief
from ..services import notifications
from ..services.audit import audit

router = APIRouter(prefix="/api/trainings", tags=["trainings"])

SOON_DAYS = 30
StatusName = Literal["open", "due_soon", "overdue", "valid", "expiring"]
Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^(https?://[^\s<>\"']+)?$")]


class TrainingIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ""
    interval_months: Annotated[int, Field(ge=1, le=120)] | None = None
    due_within_days: Annotated[int, Field(ge=1, le=365)] = 30
    department: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    link: Url = ""
    active: bool = True


class TrainingOut(TrainingIn):
    id: int


class PersonStatus(BaseModel):
    training: TrainingOut
    person: UserBrief
    status: StatusName
    due_on: date | None
    completed_on: date | None
    valid_until: date | None
    record_id: int | None
    has_certificate: bool


def _out(t: Training) -> TrainingOut:
    return TrainingOut(
        id=t.id, title=t.title, description=t.description, interval_months=t.interval_months,
        due_within_days=t.due_within_days, department=t.department, link=t.link, active=t.active,
    )


def _applies(t: Training, person: User) -> bool:
    return t.active and person.is_active and (not t.department or t.department == person.department)


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    return date(year, month, 28)


def _status(db: Session, t: Training, person: User, today: date | None = None) -> PersonStatus:
    today = today or date.today()
    record = db.scalar(
        select(TrainingRecord)
        .where(TrainingRecord.training_id == t.id, TrainingRecord.user_id == person.id)
        .order_by(TrainingRecord.completed_on.desc(), TrainingRecord.id.desc())
    )
    if record is not None and (record.valid_until is None or record.valid_until >= today):
        expiring = record.valid_until is not None and record.valid_until <= today + timedelta(days=SOON_DAYS)
        status: StatusName = "expiring" if expiring else "valid"
        due = record.valid_until
    else:
        if record is not None:
            due = record.valid_until
        else:
            begin = max(t.created_at.date(), person.start_date or t.created_at.date())
            due = begin + timedelta(days=t.due_within_days)
        status = "overdue" if due and due < today else ("due_soon" if due and due <= today + timedelta(days=SOON_DAYS) else "open")
    return PersonStatus(
        training=_out(t), person=UserBrief.model_validate(person), status=status, due_on=due,
        completed_on=record.completed_on if record else None, valid_until=record.valid_until if record else None,
        record_id=record.id if record else None, has_certificate=bool(record and record.certificate_path),
    )


def open_trainings(db: Session, person: User) -> int:
    """Trainings the person still has to do (overdue or due within 30 days)."""
    trainings = db.scalars(select(Training).where(Training.active.is_(True)))
    return sum(1 for t in trainings if _applies(t, person) and _status(db, t, person).status in ("overdue", "due_soon"))


async def _record(db: Session, t: Training, person: User, actor: User, completed_on: date, file: UploadFile | None) -> TrainingRecord:
    if completed_on > date.today():
        error = ApiError(422, "day_future", "The date cannot be in the future.")
        error.field = "completed_on"  # type: ignore[attr-defined]
        raise error
    stored = await save_upload(file, RECEIPT_TYPES, "certificates") if file and file.filename else None
    record = TrainingRecord(
        training_id=t.id, user_id=person.id, completed_on=completed_on,
        valid_until=_add_months(completed_on, t.interval_months) if t.interval_months else None,
        certificate_name=stored.original_name if stored else None, certificate_path=stored.relative_path if stored else None,
        recorded_by_id=actor.id,
    )
    db.add(record)
    return record


def _get(db: Session, training_id: int) -> Training:
    t = db.get(Training, training_id)
    if t is None:
        raise not_found("Training")
    return t


@router.get("/mine", response_model=list[PersonStatus])
def mine(user: CurrentUser, db: DB) -> list[PersonStatus]:
    order = {"overdue": 0, "due_soon": 1, "open": 2, "expiring": 3, "valid": 4}
    rows = [_status(db, t, user) for t in db.scalars(select(Training).order_by(Training.title)) if _applies(t, user)]
    return sorted(rows, key=lambda r: (order[r.status], r.due_on or date.max))


@router.post("/{training_id}/complete", response_model=PersonStatus)
async def complete(
    training_id: int, user: CurrentUser, db: DB, completed_on: date = Form(...), file: UploadFile | None = File(None)
) -> PersonStatus:
    """The person confirms they took part (optionally with a certificate)."""
    t = _get(db, training_id)
    if not _applies(t, user):
        raise not_found("Training")
    await _record(db, t, user, user, completed_on, file)
    db.commit()
    return _status(db, t, user)


@router.get("", response_model=list[TrainingOut])
def list_trainings(user: Admin, db: DB) -> list[TrainingOut]:
    return [_out(t) for t in db.scalars(select(Training).order_by(Training.active.desc(), Training.title))]


@router.post("", response_model=TrainingOut, status_code=201)
def create_training(body: TrainingIn, user: Admin, db: DB) -> TrainingOut:
    t = Training(**body.model_dump())
    db.add(t)
    audit(db, user, "training_created", body.title)
    db.commit()
    return _out(t)


@router.put("/{training_id}", response_model=TrainingOut)
def update_training(training_id: int, body: TrainingIn, user: Admin, db: DB) -> TrainingOut:
    t = _get(db, training_id)
    for field, value in body.model_dump().items():
        setattr(t, field, value)
    audit(db, user, "training_updated", t.title)
    db.commit()
    return _out(t)


@router.get("/{training_id}/people", response_model=list[PersonStatus])
def people(training_id: int, user: Admin, db: DB) -> list[PersonStatus]:
    t = _get(db, training_id)
    persons = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.last_name, User.first_name))
    return [_status(db, t, p) for p in persons if _applies(t, p)]


@router.post("/{training_id}/people/{person_id}", response_model=PersonStatus)
async def record_for(
    training_id: int, person_id: int, user: Admin, db: DB, completed_on: date = Form(...), file: UploadFile | None = File(None)
) -> PersonStatus:
    t = _get(db, training_id)
    person = db.get(User, person_id)
    if person is None:
        raise not_found("Person")
    await _record(db, t, person, user, completed_on, file)
    audit(db, user, "training_confirmed", f"{t.title} – {person.full_name}", completed_on=str(completed_on))
    db.commit()
    return _status(db, t, person)


@router.post("/{training_id}/remind")
def remind(training_id: int, user: Admin, db: DB) -> dict:
    t = _get(db, training_id)
    due = [s.person.id for s in people(training_id, user, db) if s.status in ("overdue", "due_soon", "open", "expiring")]
    notifications.notify_many(db, due, user, "training_due", {"title": t.title}, "/trainings")
    db.commit()
    return {"reminded": len([d for d in due if d != user.id])}


@router.get("/{training_id}/export.csv")
def export(training_id: int, user: Admin, db: DB) -> Response:
    t = _get(db, training_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["name", "department", "status", "due_on", "completed_on", "valid_until"])
    for s in people(training_id, user, db):
        writer.writerow([s.person.full_name, s.person.department, s.status, s.due_on or "", s.completed_on or "", s.valid_until or ""])
    return Response(
        "﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="training-{t.id}.csv"'},
    )


@router.get("/records/{record_id}/certificate")
def certificate(record_id: int, user: CurrentUser, db: DB) -> FileResponse:
    record = db.get(TrainingRecord, record_id)
    if record is None or not record.certificate_path or not (record.user_id == user.id or user.is_admin):
        raise not_found("Certificate")
    file_type = record.certificate_path.rsplit(".", 1)[-1]
    return FileResponse(
        resolve(record.certificate_path), media_type=MIME_TYPES.get(file_type, "application/octet-stream"),
        filename=record.certificate_name or f"certificate.{file_type}",
    )
