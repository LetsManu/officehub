"""Application settings, read once from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return int(value) if value else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    upload_dir: Path
    demo_mode: bool
    demo_language: str
    session_hours: int
    cookie_secure: bool
    max_upload_mb: int
    admin_email: str | None
    admin_password: str | None
    app_version: str
    # E-mail (optional): notifications are sent through your own mail server
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_from: str | None
    smtp_security: str  # "starttls", "ssl" or "none"
    portal_url: str  # used for links in e-mails
    timezone: str  # local time zone for time tracking
    # Office editing (optional): your own Collabora Online and/or ONLYOFFICE Docs server in the same stack
    collabora_url: str | None  # how the backend reaches Collabora, e.g. http://collabora:9980
    onlyoffice_url: str | None  # how the backend reaches ONLYOFFICE, e.g. http://onlyoffice
    onlyoffice_jwt_secret: str | None
    backend_internal_url: str  # how the office servers reach the backend, e.g. http://backend:8000

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    language = os.getenv("DEMO_LANGUAGE", "de").strip().lower()
    return Settings(
        data_dir=data_dir,
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{data_dir / 'officehub.db'}"),
        upload_dir=Path(os.getenv("UPLOAD_DIR", str(data_dir / "uploads"))).resolve(),
        demo_mode=_bool("DEMO_MODE", False),
        demo_language=language if language in {"de", "en"} else "de",
        session_hours=max(1, _int("SESSION_HOURS", 12)),
        cookie_secure=_bool("COOKIE_SECURE", False),
        max_upload_mb=max(1, _int("MAX_UPLOAD_MB", 15)),
        admin_email=os.getenv("ADMIN_EMAIL") or None,
        admin_password=os.getenv("ADMIN_PASSWORD") or None,
        app_version=os.getenv("APP_VERSION", "dev"),
        smtp_host=os.getenv("SMTP_HOST") or None,
        smtp_port=_int("SMTP_PORT", 587),
        smtp_user=os.getenv("SMTP_USER") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        smtp_from=os.getenv("SMTP_FROM") or None,
        smtp_security=(os.getenv("SMTP_SECURITY", "starttls").strip().lower()),
        portal_url=os.getenv("PORTAL_URL", "http://localhost:8080").rstrip("/"),
        timezone=os.getenv("TIMEZONE", "Europe/Vienna"),
        collabora_url=(os.getenv("COLLABORA_URL") or "").rstrip("/") or None,
        onlyoffice_url=(os.getenv("ONLYOFFICE_URL") or "").rstrip("/") or None,
        onlyoffice_jwt_secret=os.getenv("ONLYOFFICE_JWT_SECRET") or None,
        backend_internal_url=os.getenv("BACKEND_INTERNAL_URL", "http://backend:8000").rstrip("/"),
    )


settings = load_settings()
