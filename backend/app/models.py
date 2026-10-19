"""Database tables."""

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no time zone support)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLES = ("employee", "manager", "admin")
APPROVER_ROLES = ("manager", "admin")

REQUEST_TYPES = ("vacation", "home_office", "equipment", "expense", "it_access", "appointment", "general")
REQUEST_STATUSES = ("draft", "submitted", "in_review", "approved", "rejected", "cancelled")
PENDING_STATUSES = ("submitted", "in_review")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    department: Mapped[str] = mapped_column(String(80), default="")
    job_title: Mapped[str] = mapped_column(String(80), default="")
    office_location: Mapped[str] = mapped_column(String(80), default="")
    language: Mapped[str] = mapped_column(String(2), default="de")
    role: Mapped[str] = mapped_column(String(20), default="employee")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Directory and organisation
    phone: Mapped[str] = mapped_column(String(40), default="", server_default=text("''"))
    mobile: Mapped[str] = mapped_column(String(40), default="", server_default=text("''"))
    show_phone: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    show_mobile: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Up to two dashboard tiles the person pinned, comma-separated keys
    pinned_tiles: Mapped[str] = mapped_column(String(100), default="", server_default=text("''"))

    manager: Mapped["User | None"] = relationship(remote_side=[id])

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_approver(self) -> bool:
        return self.role in APPROVER_ROLES

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User] = relationship()


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), index=True, default="draft")
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # Type-specific fields. Only the ones relevant to the request type are filled.
    start_date: Mapped[date | None] = mapped_column(Date)  # vacation, home office, expense date
    end_date: Mapped[date | None] = mapped_column(Date)
    working_days: Mapped[int | None] = mapped_column(Integer)
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    category: Mapped[str | None] = mapped_column(String(30))
    item: Mapped[str | None] = mapped_column(String(120))  # equipment item or IT system
    access_level: Mapped[str | None] = mapped_column(String(10))
    needed_by: Mapped[date | None] = mapped_column(Date)
    # Appointment requests: up to three proposed local times ("YYYY-MM-DDTHH:MM", JSON list)
    # and the one the approver confirmed
    proposed_times: Mapped[str | None] = mapped_column(Text)
    confirmed_time: Mapped[str | None] = mapped_column(String(16))

    attachment_name: Mapped[str | None] = mapped_column(String(200))
    attachment_path: Mapped[str | None] = mapped_column(String(200))
    attachment_mime: Mapped[str | None] = mapped_column(String(100))

    decision_comment: Mapped[str | None] = mapped_column(Text)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])
    comments: Mapped[list["RequestComment"]] = relationship(
        back_populates="request", order_by="RequestComment.created_at", cascade="all, delete-orphan"
    )
    events: Mapped[list["RequestEvent"]] = relationship(
        back_populates="request", order_by="RequestEvent.created_at", cascade="all, delete-orphan"
    )


class RequestComment(Base):
    __tablename__ = "request_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    request: Mapped[Request] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class RequestEvent(Base):
    """History entry: who changed what and when."""

    __tablename__ = "request_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    request: Mapped[Request] = relationship(back_populates="events")
    actor: Mapped[User] = relationship()


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20), default="general")
    publish_date: Mapped[date] = mapped_column(Date, index=True)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    event_date: Mapped[date | None] = mapped_column(Date)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    author: Mapped[User] = relationship()


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(20), default="other")
    file_name: Mapped[str] = mapped_column(String(200))
    file_path: Mapped[str] = mapped_column(String(200))
    file_type: Mapped[str] = mapped_column(String(10))  # pdf, md, txt, docx
    file_size: Mapped[int] = mapped_column(Integer)
    content_text: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    uploaded_by: Mapped[User] = relationship()


# ---------- Meeting rooms ----------


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    seats: Mapped[int] = mapped_column(Integer, default=4)
    equipment: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RoomBooking(Base):
    __tablename__ = "room_bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(120))
    day: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    end_time: Mapped[str] = mapped_column(String(5))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    room: Mapped[Room] = relationship()
    user: Mapped[User] = relationship()


# ---------- Visitors ----------

VISITOR_STATUSES = ("expected", "checked_in", "checked_out", "cancelled")


class Visitor(Base):
    __tablename__ = "visitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    company: Mapped[str] = mapped_column(String(120), default="")
    visit_date: Mapped[date] = mapped_column(Date, index=True)
    expected_time: Mapped[str] = mapped_column(String(5), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="expected")
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    host: Mapped[User] = relationship(foreign_keys=[host_id])


# ---------- Employee reviews ----------

REVIEW_STATUSES = ("preparation", "completed")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="preparation")
    meeting_date: Mapped[date | None] = mapped_column(Date)
    # Preparation answers (JSON objects) – each person edits only their own
    employee_prep: Mapped[str] = mapped_column(Text, default="{}")
    reviewer_prep: Mapped[str] = mapped_column(Text, default="{}")
    employee_prep_done: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_prep_done: Mapped[bool] = mapped_column(Boolean, default=False)
    goals: Mapped[str] = mapped_column(Text, default="")
    employee_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewer_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    employee: Mapped[User] = relationship(foreign_keys=[employee_id])
    reviewer: Mapped[User] = relationship(foreign_keys=[reviewer_id])


# ---------- Onboarding ----------

ONBOARDING_OWNERS = ("hr", "it", "manager")


class OnboardingTask(Base):
    __tablename__ = "onboarding_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Default tasks have a key (translated in the UI); custom tasks only a title
    key: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(150), default="")
    owner: Mapped[str] = mapped_column(String(10))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    done_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    done_by: Mapped[User | None] = relationship(foreign_keys=[done_by_id])


# ---------- Quick links and settings ----------


class QuickLink(Base):
    __tablename__ = "quick_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(60))
    url: Mapped[str] = mapped_column(String(500))
    icon: Mapped[str] = mapped_column(String(20), default="link")
    description: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Setting(Base):
    """Small key/value store for portal-wide settings (JSON values)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


# ---------- Notifications ----------


class Notification(Base):
    """Something a person should know about. The text is built in the UI from kind + params."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    params: Mapped[str] = mapped_column(Text, default="{}")  # JSON object with names, titles …
    link: Mapped[str] = mapped_column(String(200), default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
