"""Request and response models. All API input is validated here."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints

def _utc_iso(value: datetime) -> str:
    """Stored datetimes are naive UTC; send them as ISO strings with a trailing "Z"."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="seconds") + "Z"


UtcDateTime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]

Text60 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Optional80 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]
Language = Literal["de", "en"]
Role = Literal["employee", "manager", "admin"]

RequestType = Literal["vacation", "home_office", "equipment", "expense", "it_access", "general"]
RequestStatus = Literal["draft", "submitted", "in_review", "approved", "rejected", "cancelled"]
Currency = Literal["EUR", "USD", "GBP", "CHF"]
AccessLevel = Literal["view", "edit", "admin"]

EXPENSE_CATEGORIES = ("travel", "meals", "office_supplies", "training", "software", "other")
EQUIPMENT_CATEGORIES = ("laptop", "monitor", "phone", "furniture", "accessories", "parking", "other")
ANNOUNCEMENT_CATEGORIES = ("general", "event", "it", "hr", "office")
DOCUMENT_CATEGORIES = ("handbook", "policy", "it", "onboarding", "template", "other")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth & users ----------


class LoginIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class UserOut(ORM):
    id: int
    email: str
    first_name: str
    last_name: str
    full_name: str
    department: str
    job_title: str
    office_location: str
    language: str
    role: str
    is_active: bool


class UserBrief(ORM):
    id: int
    full_name: str
    department: str


class ProfileUpdate(BaseModel):
    first_name: Text60 | None = None
    last_name: Text60 | None = None
    department: Optional80 | None = None
    job_title: Optional80 | None = None
    office_location: Optional80 | None = None
    language: Language | None = None


class PasswordChange(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: Annotated[str, StringConstraints(min_length=8, max_length=200)]


class UserCreate(BaseModel):
    email: Email
    first_name: Text60
    last_name: Text60
    department: Optional80 = ""
    job_title: Optional80 = ""
    office_location: Optional80 = ""
    language: Language = "de"
    role: Role = "employee"
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)]


class UserAdminUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    department: Optional80 | None = None
    job_title: Optional80 | None = None


# ---------- Requests ----------


class RequestFields(BaseModel):
    """Fields shared by create and update. Type-specific rules live in services.requests."""

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    start_date: date | None = None
    end_date: date | None = None
    amount: Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=2)] | None = None
    currency: Currency | None = None
    category: Annotated[str, StringConstraints(max_length=30)] | None = None
    item: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    access_level: AccessLevel | None = None
    needed_by: date | None = None


class RequestCreate(RequestFields):
    type: RequestType
    submit: bool = False


class RequestUpdate(RequestFields):
    status: Literal["submitted", "in_review", "cancelled"] | None = None


class CommentIn(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class DecisionIn(BaseModel):
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class CommentOut(ORM):
    id: int
    body: str
    author: UserBrief
    created_at: UtcDateTime


class EventOut(ORM):
    id: int
    action: str
    actor: UserBrief
    created_at: UtcDateTime


class RequestPermissions(BaseModel):
    can_edit: bool
    can_submit: bool
    can_cancel: bool
    can_comment: bool
    can_decide: bool
    can_start_review: bool
    can_attach: bool


class RequestOut(ORM):
    id: int
    type: str
    title: str
    description: str
    status: str
    requester: UserBrief
    start_date: date | None
    end_date: date | None
    working_days: int | None
    amount: str | None = None
    currency: str | None
    category: str | None
    item: str | None
    access_level: str | None
    needed_by: date | None
    attachment_name: str | None
    decision_comment: str | None
    decided_by: UserBrief | None
    decided_at: UtcDateTime | None
    submitted_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    comment_count: int = 0


class RequestDetail(RequestOut):
    comments: list[CommentOut]
    events: list[EventOut]
    permissions: RequestPermissions


class RequestList(BaseModel):
    items: list[RequestOut]
    total: int


# ---------- Announcements ----------


class AnnouncementIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    category: Literal[ANNOUNCEMENT_CATEGORIES] = "general"  # type: ignore[valid-type]
    publish_date: date | None = None
    expiry_date: date | None = None
    event_date: date | None = None
    pinned: bool = False


class AnnouncementUpdate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)] | None = None
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)] | None = None
    category: Literal[ANNOUNCEMENT_CATEGORIES] | None = None  # type: ignore[valid-type]
    publish_date: date | None = None
    expiry_date: date | None = None
    event_date: date | None = None
    pinned: bool | None = None
    archived: bool | None = None


class AnnouncementOut(ORM):
    id: int
    title: str
    body: str
    category: str
    publish_date: date
    expiry_date: date | None
    event_date: date | None
    pinned: bool
    archived: bool
    author: UserBrief
    created_at: UtcDateTime
    updated_at: UtcDateTime


# ---------- Documents ----------


class DocumentUpdate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    category: Literal[DOCUMENT_CATEGORIES] | None = None  # type: ignore[valid-type]
    archived: bool | None = None


class DocumentOut(ORM):
    id: int
    title: str
    description: str
    category: str
    file_name: str
    file_type: str
    file_size: int
    archived: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime
    snippet: str | None = None


class DocumentContent(BaseModel):
    format: Literal["md", "txt"]
    text: str
