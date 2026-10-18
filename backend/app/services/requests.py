"""Business rules for requests: validation per type, permissions and serialization."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import PENDING_STATUSES, Request, RequestEvent, User
from ..schemas import (
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
    "general": {"title", "description"},
}


def _field_error(field: str, code: str, message: str) -> ApiError:
    error = ApiError(422, code, message)
    error.field = field  # type: ignore[attr-defined]
    return error


def validate_fields(request_type: str, values: dict, today: date | None = None) -> dict:
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
        if count_working_days(start, end) == 0:
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

    if request_type == "general" and not data.get("description"):
        raise _field_error("description", "description_required", "Please describe your request.")

    if data.get("needed_by") and data["needed_by"] < today:
        raise _field_error("needed_by", "needed_by_past", "The date cannot be in the past.")

    amount: Decimal | None = data.pop("amount")
    data["amount_cents"] = int((amount * 100).to_integral_value()) if amount is not None else None
    data["description"] = data.get("description") or ""
    if request_type in {"vacation", "home_office"}:
        data["working_days"] = count_working_days(data["start_date"], data["end_date"])
    else:
        data["working_days"] = None
    return data


def current_values(req: Request) -> dict:
    values = {name: getattr(req, name, None) for name in FIELD_NAMES if name != "amount"}
    values["amount"] = Decimal(req.amount_cents) / 100 if req.amount_cents is not None else None
    return values


def add_event(db: Session, req: Request, actor: User, action: str) -> None:
    db.add(RequestEvent(request=req, actor_id=actor.id, action=action))


def can_view(user: User, req: Request) -> bool:
    if req.requester_id == user.id:
        return True
    # Approvers see everything except other people's unsent drafts.
    return user.is_approver and req.status != "draft"


def permissions(user: User, req: Request) -> RequestPermissions:
    is_owner = req.requester_id == user.id
    approver = user.is_approver and not is_owner and req.status != "draft"
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
