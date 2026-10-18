"""Database tables."""

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no time zone support)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLES = ("employee", "manager", "admin")
APPROVER_ROLES = ("manager", "admin")

REQUEST_TYPES = ("vacation", "home_office", "equipment", "expense", "it_access", "general")
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
