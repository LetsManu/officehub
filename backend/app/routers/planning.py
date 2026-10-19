"""Resource planning: projects, who is planned for what, workload and planned vs. booked hours.

Managers plan their team, HR/admins everyone. Everybody sees their own plan and books time on projects
in time tracking.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select

from ..deps import DB, Approver, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import PROJECT_COLORS, Allocation, Project, TimeEntry, User
from ..schemas import UserBrief
from ..services.audit import audit
from ..services.notifications import notify
from ..services.planning import Calendar, booked_minutes, plannable_ids, planned_minutes, project_span

router = APIRouter(prefix="/api/planning", tags=["planning"])

MAX_DAYS = 92  # longest range the planning board shows at once
MAX_ALLOCATION_DAYS = 366

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Optional100 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class ProjectIn(BaseModel):
    name: Name
    client: Optional100 = ""
    color: str = "blue"
    budget_hours: Annotated[float, Field(ge=0, le=100000)] | None = None
    start_date: date | None = None
    end_date: date | None = None
    active: bool = True


class ProjectOut(BaseModel):
    id: int
    name: str
    client: str
    color: str
    budget_minutes: int | None
    start_date: date | None
    end_date: date | None
    active: bool
    planned_minutes: int | None = None  # only for planners
    booked_minutes: int | None = None


class AllocationIn(BaseModel):
    project_id: int
    user_id: int
    start_date: date
    end_date: date
    minutes_per_day: Annotated[int, Field(ge=15, le=720)]
    note: Note = ""


class AllocationOut(BaseModel):
    id: int
    project_id: int
    user_id: int
    start_date: date
    end_date: date
    minutes_per_day: int
    note: str


class BoardDay(BaseModel):
    date: date
    off: str | None  # "weekend", "holiday" or None


class BoardRow(BaseModel):
    person: UserBrief
    editable: bool
    away: list[date]  # approved vacation
    capacity: int  # minutes in the range
    planned: int
    booked: int  # booked on any project


class Board(BaseModel):
    start: date
    end: date
    days: list[BoardDay]
    rows: list[BoardRow]
    allocations: list[AllocationOut]
    projects: list[ProjectOut]
    can_plan: bool


class ReportRow(BaseModel):
    person: UserBrief
    planned: int
    booked: int


class ProjectReport(BaseModel):
    project: ProjectOut
    rows: list[ReportRow]
    weeks: list[dict]  # {"start": date, "planned": int, "booked": int}


class MyAllocation(BaseModel):
    id: int
    project: ProjectOut
    start_date: date
    end_date: date
    minutes_per_day: int
    note: str


# ---------- helpers ----------


def _field_error(field: str, code: str, message: str) -> ApiError:
    error = ApiError(422, code, message)
    error.field = field  # type: ignore[attr-defined]
    return error


def _project_out(project: Project, stats: tuple[int, int] | None = None) -> ProjectOut:
    out = ProjectOut(
        id=project.id, name=project.name, client=project.client, color=project.color,
        budget_minutes=project.budget_minutes, start_date=project.start_date, end_date=project.end_date,
        active=project.active,
    )
    if stats is not None:
        out.planned_minutes, out.booked_minutes = stats
    return out


def _alloc_out(a: Allocation) -> AllocationOut:
    return AllocationOut(id=a.id, project_id=a.project_id, user_id=a.user_id, start_date=a.start_date,
                         end_date=a.end_date, minutes_per_day=a.minutes_per_day, note=a.note)


def _project_stats(db: DB, project: Project) -> tuple[int, int]:
    span = project_span(db, project.id)
    if span is None:
        return 0, 0
    allocations = db.scalars(select(Allocation).where(Allocation.project_id == project.id)).all()
    people = list(db.scalars(select(User).where(User.id.in_({a.user_id for a in allocations})))) if allocations else []
    cal = Calendar(db, people, *span)
    planned = sum(planned_minutes(cal, a) for a in allocations)
    booked = sum(booked_minutes(db, *span, project_id=project.id).values())
    return planned, booked


def _check_project(body: ProjectIn) -> None:
    if body.color not in PROJECT_COLORS:
        raise _field_error("color", "invalid_choice", "Please choose one of the colours.")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise _field_error("end_date", "end_before_start", "The end date must not be before the start date.")


def _apply_project(project: Project, body: ProjectIn) -> None:
    project.name, project.client, project.color = body.name, body.client, body.color
    project.budget_minutes = round(body.budget_hours * 60) if body.budget_hours is not None else None
    project.start_date, project.end_date, project.active = body.start_date, body.end_date, body.active


def _get_project(db: DB, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("Project")
    return project


def _check_allocation(db: DB, user: User, body: AllocationIn, current: Allocation | None = None) -> Project:
    allowed = plannable_ids(db, user)
    if body.user_id not in allowed or (current is not None and current.user_id not in allowed):
        raise forbidden("You can only plan people in your team.")
    project = db.get(Project, body.project_id)
    if project is None:
        raise _field_error("project_id", "project_required", "Please choose a project.")
    if not project.active and (current is None or current.project_id != project.id):
        raise _field_error("project_id", "project_inactive", "This project is finished.")
    if body.end_date < body.start_date:
        raise _field_error("end_date", "end_before_start", "The end date must not be before the start date.")
    if (body.end_date - body.start_date).days >= MAX_ALLOCATION_DAYS:
        raise _field_error("end_date", "range_too_long", "Please plan at most one year at a time.")
    return project


# ---------- projects ----------


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(user: CurrentUser, db: DB, include_inactive: bool = False) -> list[ProjectOut]:
    query = select(Project).order_by(Project.name)
    if not include_inactive:
        query = query.where(Project.active.is_(True))
    projects = db.scalars(query).all()
    planner = bool(plannable_ids(db, user))
    return [_project_out(p, _project_stats(db, p) if planner else None) for p in projects]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, user: Approver, db: DB) -> ProjectOut:
    _check_project(body)
    project = Project()
    _apply_project(project, body)
    db.add(project)
    db.flush()
    audit(db, user, "project_created", project.name)
    db.commit()
    return _project_out(project, (0, 0))


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectIn, user: Approver, db: DB) -> ProjectOut:
    project = _get_project(db, project_id)
    _check_project(body)
    _apply_project(project, body)
    audit(db, user, "project_updated", project.name)
    db.commit()
    return _project_out(project, _project_stats(db, project))


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, user: Approver, db: DB) -> None:
    project = _get_project(db, project_id)
    used = db.scalar(select(TimeEntry.id).where(TimeEntry.project_id == project.id).limit(1))
    if used is not None:
        raise ApiError(409, "project_in_use", "Time has been booked on this project. Mark it as finished instead.")
    audit(db, user, "project_deleted", project.name)
    db.delete(project)
    db.commit()


@router.get("/projects/{project_id}", response_model=ProjectReport)
def project_report(project_id: int, user: Approver, db: DB) -> ProjectReport:
    project = _get_project(db, project_id)
    span = project_span(db, project.id)
    if span is None:
        return ProjectReport(project=_project_out(project, (0, 0)), rows=[], weeks=[])
    start = span[0] - timedelta(days=span[0].weekday())
    end = span[1] + timedelta(days=6 - span[1].weekday())
    allocations = db.scalars(select(Allocation).where(Allocation.project_id == project.id)).all()
    booked = booked_minutes(db, start, end, project_id=project.id)
    person_ids = {a.user_id for a in allocations} | {pid for pid, _ in booked}
    people = list(db.scalars(select(User).where(User.id.in_(person_ids)).order_by(User.last_name, User.first_name)))
    cal = Calendar(db, people, start, end)

    planned_by_person: dict[int, int] = {}
    planned_by_week: dict[date, int] = {}
    for a in allocations:
        for day in cal.days():
            if a.start_date <= day <= a.end_date and cal.capacity(a.user_id, day):
                planned_by_person[a.user_id] = planned_by_person.get(a.user_id, 0) + a.minutes_per_day
                monday = day - timedelta(days=day.weekday())
                planned_by_week[monday] = planned_by_week.get(monday, 0) + a.minutes_per_day
    booked_by_week: dict[date, int] = {}
    for entry_day, start_at, end_at in db.execute(
        select(TimeEntry.day, TimeEntry.start_at, TimeEntry.end_at).where(
            TimeEntry.project_id == project.id, TimeEntry.end_at.is_not(None))
    ):
        monday = entry_day - timedelta(days=entry_day.weekday())
        booked_by_week[monday] = booked_by_week.get(monday, 0) + max(0, int((end_at - start_at).total_seconds() // 60))

    rows = [ReportRow(person=UserBrief.model_validate(p), planned=planned_by_person.get(p.id, 0),
                      booked=booked.get((p.id, project.id), 0)) for p in people]
    weeks = []
    monday = start
    while monday <= end:
        weeks.append({"start": monday, "planned": planned_by_week.get(monday, 0), "booked": booked_by_week.get(monday, 0)})
        monday += timedelta(days=7)
    stats = (sum(planned_by_person.values()), sum(booked_by_week.values()))
    return ProjectReport(project=_project_out(project, stats), rows=rows, weeks=weeks)


# ---------- planning board ----------


@router.get("/board", response_model=Board)
def board(user: CurrentUser, db: DB, start: date, days: int = Query(28, ge=7, le=MAX_DAYS),
          department: str = "") -> Board:
    end = start + timedelta(days=days - 1)
    editable = plannable_ids(db, user)
    visible = editable | {user.id}
    query = select(User).where(User.id.in_(visible), User.is_active.is_(True))
    if department:
        query = query.where(User.department == department)
    people = list(db.scalars(query.order_by(User.last_name, User.first_name)))
    ids = [p.id for p in people]
    cal = Calendar(db, people, start, end)
    allocations = db.scalars(
        select(Allocation).where(Allocation.user_id.in_(ids), Allocation.start_date <= end, Allocation.end_date >= start)
        .order_by(Allocation.start_date, Allocation.id)
    ).all()
    booked = booked_minutes(db, start, end, person_ids=ids)

    rows = []
    for p in people:
        rows.append(BoardRow(
            person=UserBrief.model_validate(p), editable=p.id in editable,
            away=sorted(cal.away[p.id]),
            capacity=sum(cal.capacity(p.id, d) for d in cal.days()),
            planned=sum(planned_minutes(cal, a) for a in allocations if a.user_id == p.id),
            booked=sum(m for (pid, project), m in booked.items() if pid == p.id and project is not None),
        ))
    board_days = [
        BoardDay(date=d, off="weekend" if d.weekday() >= 5 else ("holiday" if d in cal.holidays else None))
        for d in cal.days()
    ]
    used = {a.project_id for a in allocations}
    projects = db.scalars(select(Project).where(Project.active.is_(True) | Project.id.in_(used)).order_by(Project.name))
    return Board(start=start, end=end, days=board_days, rows=rows, allocations=[_alloc_out(a) for a in allocations],
                 projects=[_project_out(p) for p in projects], can_plan=bool(editable))


@router.get("/mine", response_model=list[MyAllocation])
def mine(user: CurrentUser, db: DB, start: date | None = None, end: date | None = None) -> list[MyAllocation]:
    start = start or date.today()
    end = end or start
    rows = db.scalars(
        select(Allocation).where(Allocation.user_id == user.id, Allocation.start_date <= end, Allocation.end_date >= start)
        .order_by(Allocation.start_date)
    ).all()
    return [MyAllocation(id=a.id, project=_project_out(a.project), start_date=a.start_date, end_date=a.end_date,
                         minutes_per_day=a.minutes_per_day, note=a.note) for a in rows]


@router.post("/allocations", response_model=AllocationOut, status_code=201)
def create_allocation(body: AllocationIn, user: CurrentUser, db: DB) -> AllocationOut:
    project = _check_allocation(db, user, body)
    allocation = Allocation(**body.model_dump(), created_by_id=user.id)
    db.add(allocation)
    if body.user_id != user.id:
        notify(db, body.user_id, "planned", {"name": user.full_name, "project": project.name,
                                             "start": body.start_date.isoformat(), "end": body.end_date.isoformat()},
               link="/planning")
    db.commit()
    return _alloc_out(allocation)


@router.put("/allocations/{allocation_id}", response_model=AllocationOut)
def update_allocation(allocation_id: int, body: AllocationIn, user: CurrentUser, db: DB) -> AllocationOut:
    allocation = db.get(Allocation, allocation_id)
    if allocation is None:
        raise not_found("Plan entry")
    _check_allocation(db, user, body, allocation)
    for key, value in body.model_dump().items():
        setattr(allocation, key, value)
    db.commit()
    return _alloc_out(allocation)


@router.delete("/allocations/{allocation_id}", status_code=204)
def delete_allocation(allocation_id: int, user: CurrentUser, db: DB) -> None:
    allocation = db.get(Allocation, allocation_id)
    if allocation is None:
        raise not_found("Plan entry")
    if allocation.user_id not in plannable_ids(db, user):
        raise forbidden("You can only plan people in your team.")
    db.delete(allocation)
    db.commit()
