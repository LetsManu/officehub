"""Database tables."""

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
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
    # Celebrations: first working day (anniversaries, "new colleagues") and an opt-in birthday without year
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    birthday_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birthday_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    show_birthday: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # Vacation days per calendar year
    vacation_days: Mapped[int] = mapped_column(Integer, default=25, server_default=text("25"))
    # Contracted working time per week in minutes (40 h = 2400), Monday to Friday
    weekly_minutes: Mapped[int] = mapped_column(Integer, default=2400, server_default=text("2400"))
    # Profile photo (square JPEG/PNG in the upload folder)
    photo_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Managers: who decides for them while they are away
    deputy_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deputy_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Two-factor sign-in (authenticator app codes)
    # Subject ID at the company login server (Authentik, Keycloak …) once the person signed in with it
    sso_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    recovery_codes: Mapped[str] = mapped_column(Text, default="[]", server_default=text("'[]'"))
    # E-mail copies of important notifications
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    # Set by HR / Admin: this person's meetings and calls are always end-to-end encrypted
    e2ee_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # Presence like in Teams: "auto" follows calendar, meetings and activity; or a status chosen by the person
    presence: Mapped[str] = mapped_column(String(12), default="auto", server_default=text("'auto'"))
    status_text: Mapped[str] = mapped_column(String(120), default="", server_default=text("''"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # an open portal reports in
    idle: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # Rich presence: what the person is doing in OfficeHub right now ("file:12", "meeting:4"), refreshed by the heartbeat
    activity: Mapped[str] = mapped_column(String(40), default="", server_default=text("''"))
    # Last working day once offboarding has started
    last_day: Mapped[date | None] = mapped_column(Date, nullable=True)

    manager: Mapped["User | None"] = relationship(remote_side=[id], foreign_keys=[manager_id])
    deputy: Mapped["User | None"] = relationship(remote_side=[id], foreign_keys=[deputy_id])

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def photo_version(self) -> str | None:
        """Changes whenever a new photo is uploaded, so browsers fetch the new one."""
        return self.photo_path.rsplit("/", 1)[-1].split(".")[0][:12] if self.photo_path else None

    def active_deputy(self, today: date | None = None) -> "User | None":
        deputy = self.deputy
        if deputy is None or not deputy.is_active or self.deputy_until is None:
            return None
        return deputy if self.deputy_until >= (today or date.today()) else None

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
    # Everyone must confirm they have read it
    must_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # Optional poll: a question and 2–6 options (JSON list)
    poll_question: Mapped[str | None] = mapped_column(String(200), nullable=True)
    poll_options: Mapped[str | None] = mapped_column(Text, nullable=True)
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


RESOURCE_KINDS = ("room", "desk", "parking")


class Room(Base):
    """Something that can be booked: a meeting room, a desk or a parking space."""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="room", server_default=text("'room'"))
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
CHECKLIST_KINDS = ("onboarding", "offboarding")


class OnboardingTask(Base):
    __tablename__ = "onboarding_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Default tasks have a key (translated in the UI); custom tasks only a title
    key: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(150), default="")
    owner: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(12), default="onboarding", server_default=text("'onboarding'"))
    # Offboarding: "return this item" tasks point to the equipment
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
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


class AnnouncementRead(Base):
    """Confirmation that a person has read a must-read announcement."""

    __tablename__ = "announcement_reads"

    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()


class PollVote(Base):
    __tablename__ = "poll_votes"

    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    option: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- Personal documents ----------


class PersonalDocument(Base):
    """A file HR shares with exactly one person (payslip, contract, certificate …)."""

    __tablename__ = "personal_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    file_name: Mapped[str] = mapped_column(String(200))
    file_path: Mapped[str] = mapped_column(String(200))
    file_type: Mapped[str] = mapped_column(String(10))
    file_size: Mapped[int] = mapped_column(Integer)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)

    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_id])


# ---------- Help / FAQ ----------


class HelpArticle(Base):
    __tablename__ = "help_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    section: Mapped[str] = mapped_column(String(20), default="general")  # same keys as section contacts
    question: Mapped[str] = mapped_column(String(200))
    answer: Mapped[str] = mapped_column(Text)  # Markdown
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    helpful_yes: Mapped[int] = mapped_column(Integer, default=0)
    helpful_no: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# ---------- Holidays, audit log ----------


class CompanyHoliday(Base):
    """Extra days off for the whole company (e.g. 24 December), added by HR."""

    __tablename__ = "company_holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True)
    name: Mapped[str] = mapped_column(String(80))


class AuditEvent(Base):
    """Who changed what. Written by the server only; nobody can edit it."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str] = mapped_column(String(150), default="")
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    actor: Mapped[User | None] = relationship()


# ---------- Time tracking ----------


class TimeEntry(Base):
    """One block of work. A running entry has no end yet (clocked in)."""

    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)  # local date of the start
    start_at: Mapped[datetime] = mapped_column(DateTime)  # UTC
    end_at: Mapped[datetime | None] = mapped_column(DateTime)  # UTC, empty while running
    note: Mapped[str] = mapped_column(String(200), default="")
    edited: Mapped[bool] = mapped_column(Boolean, default=False)  # entered or changed by hand
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped["Project | None"] = relationship()


TIME_MONTH_STATUSES = ("submitted", "approved", "returned")


class TimeMonth(Base):
    """A person's timesheet for one month: handed in by the person, approved or sent back by the manager."""

    __tablename__ = "time_months"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    status: Mapped[str] = mapped_column(String(20), default="submitted")
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)  # totals when handed in
    target_minutes: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    comment: Mapped[str] = mapped_column(String(300), default="")

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    decided_by: Mapped["User | None"] = relationship(foreign_keys=[decided_by_id])

    __table_args__ = (UniqueConstraint("user_id", "month"),)


# ---------- Resource planning ----------

PROJECT_COLORS = ("blue", "teal", "green", "amber", "orange", "purple", "pink", "slate")


class Project(Base):
    """Something people are planned for and book their time on."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    client: Mapped[str] = mapped_column(String(100), default="")
    color: Mapped[str] = mapped_column(String(20), default="blue")
    budget_minutes: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Allocation(Base):
    """A person planned for a project: from/to and hours per working day."""

    __tablename__ = "allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    minutes_per_day: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship()


# ---------- Pulse surveys ----------

SURVEY_STATUSES = ("draft", "open", "closed")


class Survey(Base):
    """Anonymous survey. Answers are stored without any link to the person."""

    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    intro: Mapped[str] = mapped_column(Text, default="")
    # JSON list of {"text": str, "kind": "scale" | "choice" | "text", "options": [str]}
    questions: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(10), default="draft")
    closes_on: Mapped[date | None] = mapped_column(Date)
    results_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SurveyParticipation(Base):
    """Only remembers THAT someone answered, so nobody answers twice. Not WHAT they answered."""

    __tablename__ = "survey_participation"

    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class SurveyResponse(Base):
    """The answers, deliberately without user and without timestamp."""

    __tablename__ = "survey_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), index=True)
    answers: Mapped[str] = mapped_column(Text)


# ---------- Ideas box ----------

IDEA_STATUSES = ("new", "review", "planned", "done", "declined")


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10), default="new", index=True)
    response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    author: Mapped[User] = relationship()


class IdeaVote(Base):
    __tablename__ = "idea_votes"

    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


# ---------- Trainings ----------


class Training(Base):
    """A required training, e.g. fire safety or data protection, optionally repeated."""

    __tablename__ = "trainings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text, default="")
    # Repeat every N months (None = once)
    interval_months: Mapped[int | None] = mapped_column(Integer)
    # Time to complete it for new people / after it is created
    due_within_days: Mapped[int] = mapped_column(Integer, default=30)
    # "" = everyone, otherwise one department
    department: Mapped[str] = mapped_column(String(80), default="")
    link: Mapped[str] = mapped_column(String(500), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TrainingRecord(Base):
    __tablename__ = "training_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    completed_on: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    certificate_name: Mapped[str | None] = mapped_column(String(200))
    certificate_path: Mapped[str | None] = mapped_column(String(200))
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- Equipment ----------

ASSET_KINDS = ("laptop", "phone", "monitor", "headset", "key", "card", "vehicle", "other")
ASSET_STATUSES = ("in_stock", "assigned", "repair", "retired")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10), default="other")
    serial: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(10), default="in_stock", index=True)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    assigned_to: Mapped[User | None] = relationship()


class AssetEvent(Base):
    """History of an item: handed out, returned, sent to repair …"""

    __tablename__ = "asset_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    person_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    person: Mapped[User | None] = relationship(foreign_keys=[person_id])
    actor: Mapped[User] = relationship(foreign_keys=[actor_id])


# ---------- Team spaces: files, boards, chat and wiki ----------

SPACE_ROLES = ("manager", "member")


class Space(Base):
    """A shared area for a team or project with files, a task board, chat channels and wiki pages."""

    __tablename__ = "spaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="")
    color: Mapped[str] = mapped_column(String(20), default="blue")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    members: Mapped[list["SpaceMember"]] = relationship(back_populates="space", cascade="all, delete-orphan")


class SpaceMember(Base):
    __tablename__ = "space_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="member")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    space: Mapped[Space] = relationship(back_populates="members")
    user: Mapped[User] = relationship()

    __table_args__ = (UniqueConstraint("space_id", "user_id"),)


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class SpaceFile(Base):
    """A file in a space. The content lives in FileVersion rows; the newest one is current."""

    __tablename__ = "space_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    file_type: Mapped[str] = mapped_column(String(10))
    size: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_text: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Lock held by an office editor (WOPI) while someone edits the file
    lock_id: Mapped[str | None] = mapped_column(String(1024))
    lock_expires: Mapped[datetime | None] = mapped_column(DateTime)
    # Checked out like in SharePoint: only this person can save new versions until they check it in again
    checked_out_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])
    checked_out_by: Mapped[User | None] = relationship(foreign_keys=[checked_out_by_id])
    versions: Mapped[list["FileVersion"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="FileVersion.number.desc()"
    )


class FileVersion(Base):
    __tablename__ = "file_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("space_files.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="upload")  # upload, editor, restore, new
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    file: Mapped[SpaceFile] = relationship(back_populates="versions")
    created_by: Mapped[User | None] = relationship()


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BoardColumn(Base):
    __tablename__ = "board_columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)  # cards here count as finished


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    column_id: Mapped[int] = mapped_column(ForeignKey("board_columns.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[date | None] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(20), default="")  # one of the project colours or empty
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    column: Mapped[BoardColumn] = relationship()
    assignees: Mapped[list["CardAssignee"]] = relationship(cascade="all, delete-orphan")


class CardAssignee(Base):
    __tablename__ = "card_assignees"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    user: Mapped[User] = relationship()

    __table_args__ = (UniqueConstraint("card_id", "user_id"),)


class CardComment(Base):
    __tablename__ = "card_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    author: Mapped[User | None] = relationship()


class Channel(Base):
    """A chat channel in a space, or a direct conversation between two people (no space)."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60), default="")
    direct_key: Mapped[str | None] = mapped_column(String(40), unique=True)  # "<low id>:<high id>" for direct messages
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChannelMember(Base):
    """Members of direct conversations, and everyone's read position in any channel."""

    __tablename__ = "channel_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    last_read_id: Mapped[int] = mapped_column(Integer, default=0)
    # Like Discord: be notified for "all" messages, only "mentions", or "none"; or mute for a while
    notify: Mapped[str] = mapped_column(String(10), default="all", server_default=text("'all'"))
    muted_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("channel_id", "user_id"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, default="")
    file_id: Mapped[int | None] = mapped_column(ForeignKey("space_files.id", ondelete="SET NULL"))
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"))  # "join the call"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    # Replies in a thread point to the first message of the thread
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(10), default="text", server_default=text("'text'"))  # text, poll, voice
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    mention_ids: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))  # ",3,17," for quick lookups
    poll_multi: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    poll_closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    audio_path: Mapped[str | None] = mapped_column(String(200), nullable=True)  # voice message, under uploads/voice
    audio_type: Mapped[str] = mapped_column(String(40), default="", server_default=text("''"))
    audio_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Last change to reactions, votes, replies, pin or text – the open chat fetches changed messages again
    changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    author: Mapped[User | None] = relationship()
    file: Mapped[SpaceFile | None] = relationship()
    meeting: Mapped["Meeting | None"] = relationship()
    reactions: Mapped[list["Reaction"]] = relationship(cascade="all, delete-orphan")
    options: Mapped[list["ChatPollOption"]] = relationship(cascade="all, delete-orphan", order_by="ChatPollOption.position")


class Reaction(Base):
    __tablename__ = "message_reactions"
    __table_args__ = (UniqueConstraint("message_id", "user_id", "emoji"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    emoji: Mapped[str] = mapped_column(String(16))

    user: Mapped[User] = relationship()


class ChatPollOption(Base):
    __tablename__ = "chat_poll_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer, default=0)
    votes: Mapped[list["ChatPollVote"]] = relationship(cascade="all, delete-orphan")


class ChatPollVote(Base):
    __tablename__ = "chat_poll_votes"
    __table_args__ = (UniqueConstraint("option_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("chat_poll_options.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    user: Mapped[User] = relationship()


class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("wiki_pages.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    updated_by: Mapped[User | None] = relationship()


class WikiRevision(Base):
    __tablename__ = "wiki_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    author: Mapped[User | None] = relationship()


class WikiEditor(Base):
    """Who has a page open for editing right now (refreshed every few seconds)."""

    __tablename__ = "wiki_editors"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()

    __table_args__ = (UniqueConstraint("page_id", "user_id"),)


# ---------- Meetings and calls (video through the company's own Jitsi server) ----------

MEETING_KINDS = ("scheduled", "space", "call")


class Meeting(Base):
    """A video meeting: planned with a time, the standing room of a space, or a call started from the chat."""

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="scheduled")
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text, default="")
    room: Mapped[str] = mapped_column(String(64), unique=True)  # name of the Jitsi conference
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # UTC
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    organizer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    guest_token: Mapped[str | None] = mapped_column(String(64), unique=True)  # set = guests may ask to join
    notes: Mapped[str] = mapped_column(Text, default="")
    notes_version: Mapped[int] = mapped_column(Integer, default=0)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)  # calls only
    # Series: "", daily, weekdays, weekly, biweekly, monthly – until a last day (local date), without skipped days
    recurrence: Mapped[str] = mapped_column(String(10), default="", server_default=text("''"))
    recurrence_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    skipped: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))  # comma-separated YYYY-MM-DD
    # Town hall: only the organizer and the people they bring on stage speak; everyone else watches
    town_hall: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # End-to-end encrypted (MLS + SFrame): only the people in the meeting hold the keys
    e2ee: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    organizer: Mapped[User | None] = relationship()
    invitees: Mapped[list["MeetingInvitee"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")


class MeetingInvitee(Base):
    __tablename__ = "meeting_invitees"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # pending, accepted, declined – for calls: ringing, accepted, declined, missed
    response: Mapped[str] = mapped_column(String(10), default="pending")

    meeting: Mapped[Meeting] = relationship(back_populates="invitees")
    user: Mapped[User] = relationship()

    __table_args__ = (UniqueConstraint("meeting_id", "user_id"),)


class MeetingPresence(Base):
    """Who is in a meeting right now (the meeting page reports every few seconds)."""

    __tablename__ = "meeting_presence"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("meeting_guests.id", ondelete="CASCADE"))
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User | None] = relationship()


class MeetingReminder(Base):
    """A reminder was sent for one occurrence of a meeting to one person (so it is sent once)."""

    __tablename__ = "meeting_reminders"
    __table_args__ = (UniqueConstraint("meeting_id", "user_id", "occurrence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    occurrence: Mapped[datetime] = mapped_column(DateTime)


class MeetingGuest(Base):
    """Someone without an account who asked to join through the guest link and waits to be let in."""

    __tablename__ = "meeting_guests"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    secret: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="waiting")  # waiting, admitted, denied
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppPassword(Base):
    """A password for one program (network drive, WordCraft/DeckCraft …), so the real password and the second
    factor stay in the browser. Only a hash is stored; it can be removed at any time."""

    __tablename__ = "app_passwords"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of a long random secret
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
