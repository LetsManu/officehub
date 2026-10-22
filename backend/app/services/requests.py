"""Business rules for requests: validation per type, permissions and serialization."""

import json
from collections.abc import Collection
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import IT_REQUEST_TYPES, PENDING_STATUSES, Request, RequestEvent, User
from ..schemas import (
    APPOINTMENT_TOPICS,
    EQUIPMENT_CATEGORIES,
    EXPENSE_CATEGORIES,
    RequestDetail,
    RequestFields,
    RequestOut,
    RequestPermissions,
)
from ..workdays import count_working_days

FIELD_NAMES = list(RequestFields.model_fields)

# Fields that are kept for each request type. Everything else is cleared.
TYPE_FIELDS: dict[str, set[str]] = {
    "vacation": {"title", "description", "start_date", "end_date"},
    "home_office": {"title", "description", "start_date", "end_date"},
    "equipment": {"title", "description", "category", "item", "needed_by"},
    "expense": {"title", "description", "start_date", "amount", "currency", "category"},
    "it_access": {"title", "description", "item", "access_level", "needed_by"},
    "appointment": {"title", "description", "category", "proposed_times"},
    "general": {"title", "description"},
}


def _field_error(field: str, code: str, message: str) -> ApiError:
    error = ApiError(422, code, message)
    error.field = field  # type: ignore[attr-defined]
    return error


def validate_fields(
    request_type: str, values: dict, today: date | None = None, holidays: Collection[date] = ()
) -> dict:
    """Check the type-specific rules and return the cleaned column values."""
    today = today or date.today()
    allowed = TYPE_FIELDS[request_type]
    data = {name: (values.get(name) if name in allowed else None) for name in FIELD_NAMES}

    if not data.get("title"):
        raise _field_error("title", "title_required", "Please enter a title.")

    if request_type in {"vacation", "home_office"}:
        start, end = data["start_date"], data["end_date"]
        if start is None:
            raise _field_error("start_date", "start_required", "Please select a start date.")
        if end is None:
            raise _field_error("end_date", "end_required", "Please select an end date.")
        if end < start:
            raise _field_error("end_date", "end_before_start", "End date must be after the start date.")
        if (end - start).days > 366:
            raise _field_error("end_date", "period_too_long", "The period can be at most one year.")
        if count_working_days(start, end, holidays) == 0:
            raise _field_error("start_date", "no_working_days", "The selected period contains no working days.")

    if request_type == "expense":
        if data["amount"] is None:
            raise _field_error("amount", "amount_required", "Please enter the amount.")
        if not data["currency"]:
            raise _field_error("currency", "currency_required", "Please select a currency.")
        if data["start_date"] is None:
            raise _field_error("start_date", "expense_date_required", "Please select the expense date.")
        if data["start_date"] > today:
            raise _field_error("start_date", "expense_date_future", "The expense date cannot be in the future.")
        if data["category"] not in EXPENSE_CATEGORIES:
            raise _field_error("category", "category_required", "Please select a category.")

    if request_type == "equipment":
        if not data["item"]:
            raise _field_error("item", "item_required", "Please describe what you need.")
        if data["category"] not in EQUIPMENT_CATEGORIES:
            raise _field_error("category", "category_required", "Please select a category.")

    if request_type == "it_access":
        if not data["item"]:
            raise _field_error("item", "system_required", "Please enter the system or application.")
        if not data["access_level"]:
            raise _field_error("access_level", "access_level_required", "Please select the access level.")

    if request_type == "appointment":
        if data["category"] not in APPOINTMENT_TOPICS:
            raise _field_error("category", "topic_required", "Please choose who the appointment is with.")
        times = list(dict.fromkeys(data.get("proposed_times") or []))
        if not times:
            raise _field_error("proposed_times", "times_required", "Please suggest at least one time.")
        now = datetime.now().strftime("%Y-%m-%dT%H:%M")
        for value in times:
            try:
                datetime.strptime(value, "%Y-%m-%dT%H:%M")
            except ValueError:
                raise _field_error("proposed_times", "time_invalid", "Please enter a valid date and time.") from None
            if value <= now:
                raise _field_error("proposed_times", "time_past", "Suggested times must be in the future.")
        data["proposed_times"] = json.dumps(sorted(times))
    else:
        data["proposed_times"] = None

    if request_type == "general" and not data.get("description"):
        raise _field_error("description", "description_required", "Please describe your request.")

    if data.get("needed_by") and data["needed_by"] < today:
        raise _field_error("needed_by", "needed_by_past", "The date cannot be in the past.")

    amount: Decimal | None = data.pop("amount")
    data["amount_cents"] = int((amount * 100).to_integral_value()) if amount is not None else None
    data["description"] = data.get("description") or ""
    if request_type in {"vacation", "home_office"}:
        data["working_days"] = count_working_days(data["start_date"], data["end_date"], holidays)
    else:
        data["working_days"] = None
    return data


def current_values(req: Request) -> dict:
    values = {name: getattr(req, name, None) for name in FIELD_NAMES if name != "amount"}
    values["amount"] = Decimal(req.amount_cents) / 100 if req.amount_cents is not None else None
    values["proposed_times"] = json.loads(req.proposed_times) if req.proposed_times else None
    return values


def add_event(db: Session, req: Request, actor: User, action: str) -> None:
    db.add(RequestEvent(request=req, actor_id=actor.id, action=action))


def is_acting_deputy(user: User, req: Request) -> bool:
    """True while the user stands in for the requester's manager."""
    manager = req.requester.manager
    deputy = manager.active_deputy() if manager is not None else None
    return deputy is not None and deputy.id == user.id


def deputy_for(db: Session, user: User) -> list[int]:
    """Ids of managers the user currently stands in for."""
    return list(
        db.scalars(
            select(User.id).where(User.deputy_id == user.id, User.deputy_until >= date.today(), User.is_active.is_(True))
        )
    )


def decides(user: User, req: Request) -> bool:
    """Managers, HR and admins decide every request; a team lead those of their own team; the service desk IT access
    and equipment requests; a deputy those of the manager they stand in for."""
    if user.approves_everyone or is_acting_deputy(user, req):
        return True
    if user.is_approver and req.requester.manager_id == user.id:
        return True
    return req.type in IT_REQUEST_TYPES and user.is_servicedesk


def decided_requests(db: Session, user: User):
    """SQL condition for other people's requests the user decides (see decides()); None when there are none."""
    if user.approves_everyone:
        return Request.requester_id != user.id
    managers = deputy_for(db, user) + ([user.id] if user.is_approver else [])
    shown = []
    if managers:
        shown.append(Request.requester_id.in_(select(User.id).where(User.manager_id.in_(managers))))
    if user.is_servicedesk:
        shown.append(Request.type.in_(IT_REQUEST_TYPES))
    return (Request.requester_id != user.id) & or_(*shown) if shown else None


def can_view(user: User, req: Request) -> bool:
    if req.requester_id == user.id:
        return True
    # Those who decide it see it, except other people's unsent drafts.
    return decides(user, req) and req.status != "draft"


def permissions(user: User, req: Request) -> RequestPermissions:
    is_owner = req.requester_id == user.id
    approver = decides(user, req) and not is_owner and req.status != "draft"
    pending = req.status in PENDING_STATUSES
    return RequestPermissions(
        can_edit=is_owner and req.status == "draft",
        can_submit=is_owner and req.status == "draft",
        can_cancel=is_owner and (req.status == "draft" or pending),
        can_comment=(is_owner or approver) and req.status != "cancelled",
        can_decide=approver and pending,
        can_start_review=approver and req.status == "submitted",
        can_attach=is_owner and req.type == "expense" and (req.status == "draft" or req.status == "submitted"),
    )


def to_out(req: Request) -> RequestOut:
    out = RequestOut.model_validate(req, from_attributes=True)
    out.amount = f"{Decimal(req.amount_cents) / 100:.2f}" if req.amount_cents is not None else None
    out.comment_count = len(req.comments)
    return out


def to_detail(req: Request, user: User) -> RequestDetail:
    base = to_out(req).model_dump()
    return RequestDetail(
        **base,
        comments=req.comments,
        events=req.events,
        permissions=permissions(user, req),
    )
