"""Onboarding checklists for new colleagues and offboarding checklists for people who leave.

HR sees and ticks every task. Managers tick the manager tasks of their own team.
The new person sees their own checklist (read-only).
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select

from ..deps import DB, HR, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import Asset, OnboardingTask, User, utcnow
from ..schemas import UserBrief, UtcDateTime
from ..services.audit import audit
from ..services.people import start_offboarding, start_onboarding
from .assets import return_asset

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

Kind = Literal["onboarding", "offboarding"]


class TaskOut(BaseModel):
    id: int
    key: str | None
    title: str
    owner: str
    done: bool
    done_at: UtcDateTime | None
    done_by: str | None
    can_toggle: bool


class ChecklistOut(BaseModel):
    person: UserBrief
    kind: str
    last_day: date | None
    manager_name: str | None
    total: int
    done: int
    tasks: list[TaskOut]


class Summary(BaseModel):
    person: UserBrief
    kind: str
    last_day: date | None
    total: int
    done: int


class TaskIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    owner: Literal["hr", "it", "manager"]
    kind: Kind = "onboarding"


class OffboardingIn(BaseModel):
    last_day: date


class ToggleIn(BaseModel):
    done: bool


def _can_view(user: User, person: User) -> bool:
    return user.is_hr or user.id == person.id or person.manager_id == user.id


def _can_toggle(user: User, task: OnboardingTask) -> bool:
    return user.is_hr or (task.owner == "manager" and task.user.manager_id == user.id)


def _checklist(db, person: User, user: User, kind: str = "onboarding") -> ChecklistOut:
    tasks = db.scalars(
        select(OnboardingTask)
        .where(OnboardingTask.user_id == person.id, OnboardingTask.kind == kind)
        .order_by(OnboardingTask.sort_order, OnboardingTask.id)
    ).all()
    items = [
        TaskOut(
            id=t.id,
            key=t.key,
            title=t.title,
            owner=t.owner,
            done=t.done_at is not None,
            done_at=t.done_at,
            done_by=t.done_by.full_name if t.done_by else None,
            can_toggle=_can_toggle(user, t),
        )
        for t in tasks
    ]
    return ChecklistOut(
        person=person,
        kind=kind,
        last_day=person.last_day,
        manager_name=person.manager.full_name if person.manager else None,
        total=len(items),
        done=sum(1 for i in items if i.done),
        tasks=items,
    )


@router.get("", response_model=list[Summary])
def overview(user: CurrentUser, db: DB, kind: Kind = "onboarding") -> list[Summary]:
    """People with a checklist of this kind that the viewer may see, open checklists first."""
    query = (
        select(User, func.count(OnboardingTask.id), func.count(OnboardingTask.done_at))
        .join(OnboardingTask, OnboardingTask.user_id == User.id)
        .where(OnboardingTask.kind == kind)
        .group_by(User.id)
    )
    if not user.is_hr:
        query = query.where((User.manager_id == user.id) | (User.id == user.id))
    rows = db.execute(query).all()
    result = [Summary(person=p, kind=kind, last_day=p.last_day, total=total, done=done) for p, total, done in rows]
    return sorted(result, key=lambda s: (s.done == s.total, s.person.full_name))


@router.get("/{user_id}", response_model=ChecklistOut)
def checklist(user_id: int, user: CurrentUser, db: DB, kind: Kind = "onboarding") -> ChecklistOut:
    person = db.get(User, user_id)
    if person is None or not _can_view(user, person):
        raise not_found("Checklist")
    return _checklist(db, person, user, kind)


@router.post("/{user_id}/offboarding", response_model=ChecklistOut)
def offboarding(user_id: int, body: OffboardingIn, user: HR, db: DB) -> ChecklistOut:
    person = db.get(User, user_id)
    if person is None:
        raise not_found("Person")
    if person.id == user.id:
        raise ApiError(409, "self_offboarding", "Please ask another administrator to start your offboarding.")
    start_offboarding(db, person, body.last_day)
    audit(db, user, "offboarding_started", person.full_name, last_day=str(body.last_day))
    db.commit()
    return _checklist(db, person, user, "offboarding")


@router.post("/{user_id}/start", response_model=ChecklistOut)
def start(user_id: int, user: HR, db: DB) -> ChecklistOut:
    person = db.get(User, user_id)
    if person is None:
        raise not_found("Person")
    start_onboarding(db, person)
    db.commit()
    return _checklist(db, person, user, "onboarding")


@router.post("/{user_id}/tasks", response_model=ChecklistOut, status_code=201)
def add_task(user_id: int, body: TaskIn, user: HR, db: DB) -> ChecklistOut:
    person = db.get(User, user_id)
    if person is None:
        raise not_found("Person")
    last = db.scalar(
        select(func.max(OnboardingTask.sort_order)).where(OnboardingTask.user_id == person.id, OnboardingTask.kind == body.kind)
    ) or 0
    db.add(OnboardingTask(user_id=person.id, title=body.title, owner=body.owner, kind=body.kind, sort_order=last + 1))
    db.commit()
    return _checklist(db, person, user, body.kind)


@router.patch("/tasks/{task_id}", response_model=ChecklistOut)
def toggle(task_id: int, body: ToggleIn, user: CurrentUser, db: DB) -> ChecklistOut:
    task = db.get(OnboardingTask, task_id)
    if task is None or not _can_view(user, task.user):
        raise not_found("Task")
    if not _can_toggle(user, task):
        raise forbidden("You cannot change this task.")
    task.done_at, task.done_by_id = (utcnow(), user.id) if body.done else (None, None)
    if body.done and task.asset_id:
        asset = db.get(Asset, task.asset_id)
        if asset is not None and asset.assigned_to_id == task.user_id:
            return_asset(db, asset, user, "offboarding")
    db.commit()
    return _checklist(db, task.user, user, task.kind)
