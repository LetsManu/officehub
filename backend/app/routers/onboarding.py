"""Onboarding checklists for new colleagues.

HR sees and ticks every task. Managers tick the manager tasks of their own team.
The new person sees their own checklist (read-only).
"""

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select

from ..deps import DB, Admin, CurrentUser
from ..errors import forbidden, not_found
from ..models import OnboardingTask, User, utcnow
from ..schemas import UserBrief, UtcDateTime
from ..services.people import start_onboarding

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


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
    manager_name: str | None
    total: int
    done: int
    tasks: list[TaskOut]


class Summary(BaseModel):
    person: UserBrief
    total: int
    done: int


class TaskIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    owner: Literal["hr", "it", "manager"]


class ToggleIn(BaseModel):
    done: bool


def _can_view(user: User, person: User) -> bool:
    return user.is_admin or user.id == person.id or person.manager_id == user.id


def _can_toggle(user: User, task: OnboardingTask) -> bool:
    return user.is_admin or (task.owner == "manager" and task.user.manager_id == user.id)


def _checklist(db, person: User, user: User) -> ChecklistOut:
    tasks = db.scalars(
        select(OnboardingTask).where(OnboardingTask.user_id == person.id).order_by(OnboardingTask.sort_order, OnboardingTask.id)
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
        manager_name=person.manager.full_name if person.manager else None,
        total=len(items),
        done=sum(1 for i in items if i.done),
        tasks=items,
    )


@router.get("", response_model=list[Summary])
def overview(user: CurrentUser, db: DB) -> list[Summary]:
    """People with an onboarding checklist that the viewer may see, open checklists first."""
    query = (
        select(User, func.count(OnboardingTask.id), func.count(OnboardingTask.done_at))
        .join(OnboardingTask, OnboardingTask.user_id == User.id)
        .group_by(User.id)
    )
    if not user.is_admin:
        query = query.where((User.manager_id == user.id) | (User.id == user.id))
    rows = db.execute(query).all()
    result = [Summary(person=p, total=total, done=done) for p, total, done in rows]
    return sorted(result, key=lambda s: (s.done == s.total, s.person.full_name))


@router.get("/{user_id}", response_model=ChecklistOut)
def checklist(user_id: int, user: CurrentUser, db: DB) -> ChecklistOut:
    person = db.get(User, user_id)
    if person is None or not _can_view(user, person):
        raise not_found("Checklist")
    return _checklist(db, person, user)


@router.post("/{user_id}/start", response_model=ChecklistOut)
def start(user_id: int, user: Admin, db: DB) -> ChecklistOut:
    person = db.get(User, user_id)
    if person is None:
        raise not_found("Person")
    start_onboarding(db, person)
    db.commit()
    return _checklist(db, person, user)


@router.post("/{user_id}/tasks", response_model=ChecklistOut, status_code=201)
def add_task(user_id: int, body: TaskIn, user: Admin, db: DB) -> ChecklistOut:
    person = db.get(User, user_id)
    if person is None:
        raise not_found("Person")
    last = db.scalar(select(func.max(OnboardingTask.sort_order)).where(OnboardingTask.user_id == person.id)) or 0
    db.add(OnboardingTask(user_id=person.id, title=body.title, owner=body.owner, sort_order=last + 1))
    db.commit()
    return _checklist(db, person, user)


@router.patch("/tasks/{task_id}", response_model=ChecklistOut)
def toggle(task_id: int, body: ToggleIn, user: CurrentUser, db: DB) -> ChecklistOut:
    task = db.get(OnboardingTask, task_id)
    if task is None or not _can_view(user, task.user):
        raise not_found("Task")
    if not _can_toggle(user, task):
        raise forbidden("You cannot change this task.")
    task.done_at, task.done_by_id = (utcnow(), user.id) if body.done else (None, None)
    db.commit()
    return _checklist(db, task.user, user)
