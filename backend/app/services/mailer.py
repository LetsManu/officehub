"""Optional e-mail copies of important notifications, sent through the company's own mail server.

Nothing is sent unless SMTP_HOST and SMTP_FROM are configured. Mails are collected while a request
is handled and sent in a background thread after the database commit, so a slow mail server never
delays the portal and a rolled-back change never sends a mail.
"""

import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage

from sqlalchemy import event
from sqlalchemy.orm import Session

from ..config import settings

logger = logging.getLogger("officehub.mail")

TYPE_NAMES = {
    "de": {"vacation": "Urlaub", "home_office": "Homeoffice", "equipment": "Gerät / Ausstattung", "expense": "Spesen",
           "it_access": "IT-Zugang", "appointment": "Terminanfrage", "general": "Allgemeine Anfrage"},
    "en": {"vacation": "Vacation", "home_office": "Working from home", "equipment": "Equipment", "expense": "Expense",
           "it_access": "IT access", "appointment": "Appointment", "general": "General request"},
}

# Only these notification kinds are worth an e-mail; everything else stays in the bell.
TEXTS = {
    "de": {
        "request_submitted": "{name} hat einen Antrag gestellt: {title} ({type})",
        "request_approved": "{name} hat deinen Antrag „{title}“ genehmigt.",
        "request_rejected": "{name} hat deinen Antrag „{title}“ abgelehnt.",
        "visitor_arrived": "Dein Besuch ist da: {name}",
        "must_read_new": "Bitte lesen und bestätigen: {title}",
        "must_read_reminder": "Erinnerung: Bitte bestätige, dass du „{title}“ gelesen hast.",
        "personal_document": "Neues Dokument für dich: {title}",
        "training_due": "Schulung fällig: {title}",
        "survey_new": "Neue anonyme Umfrage: {title}",
        "test": "Test-E-Mail von OfficeHub – der Versand funktioniert.",
    },
    "en": {
        "request_submitted": "{name} sent a request: {title} ({type})",
        "request_approved": "{name} approved your request \"{title}\".",
        "request_rejected": "{name} declined your request \"{title}\".",
        "visitor_arrived": "Your visitor has arrived: {name}",
        "must_read_new": "Please read and confirm: {title}",
        "must_read_reminder": "Reminder: please confirm that you have read \"{title}\".",
        "personal_document": "New document for you: {title}",
        "training_due": "Training due: {title}",
        "survey_new": "New anonymous survey: {title}",
        "test": "Test e-mail from OfficeHub – sending works.",
    },
}
FOOTER = {
    "de": "Öffnen: {link}\n\nDu bekommst diese E-Mail, weil E-Mail-Benachrichtigungen in deinem OfficeHub-Profil eingeschaltet sind.",
    "en": "Open: {link}\n\nYou receive this e-mail because e-mail notifications are switched on in your OfficeHub profile.",
}
EMAIL_KINDS = frozenset(TEXTS["en"]) - {"test"}


class _Default(dict):
    def __missing__(self, key: str) -> str:
        return ""


def build_message(to: str, language: str, kind: str, params: dict, link: str) -> EmailMessage:
    lang = language if language in TEXTS else "de"
    values = _Default(params)
    if "type" in values:
        values["type"] = TYPE_NAMES[lang].get(str(values["type"]), values["type"])
    text = TEXTS[lang][kind].format_map(values)
    message = EmailMessage()
    message["Subject"] = f"OfficeHub: {text}"[:200]
    message["From"] = settings.smtp_from
    message["To"] = to
    message.set_content(f"{text}\n\n" + FOOTER[lang].format(link=f"{settings.portal_url}{link or '/'}"))
    return message


def send_now(messages: list[EmailMessage]) -> None:
    """Sends the messages over one connection. Raises on connection or login errors."""
    if not messages:
        return
    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=context)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
    with server:
        if settings.smtp_security == "starttls":
            server.starttls(context=context)
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password or "")
        for message in messages:
            server.send_message(message)


def _send_in_background(messages: list[EmailMessage]) -> None:
    def run() -> None:
        try:
            send_now(messages)
        except Exception:  # noqa: BLE001 - mail problems must never break the portal
            logger.exception("Sending %d notification e-mail(s) failed", len(messages))

    threading.Thread(target=run, name="officehub-mail", daemon=True).start()


def queue_mail(db: Session, to: str, language: str, kind: str, params: dict, link: str) -> None:
    if not settings.mail_enabled or kind not in EMAIL_KINDS or not to:
        return
    db.info.setdefault("mail_outbox", []).append(build_message(to, language, kind, params, link))


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    outbox = session.info.pop("mail_outbox", None)
    if outbox:
        _send_in_background(outbox)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop("mail_outbox", None)
