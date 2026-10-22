"""For the Windows and Android apps (apps/): one call that waits until something new is there.

The Android app keeps it open in the background (like Teams, but without a cloud push service): new
notifications, chat messages and ringing calls come back within a second or two. The texts of notifications are
built in the app from kind + params, with the wording the open portal handed it (frontend lib/native.ts)."""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from ..db import SessionLocal
from ..deps import CurrentUser
from ..models import Notification, User
from ..schemas import UtcDateTime
from .chat import conversations, unread_total
from .meetings import Ringing, incoming
from ..services.meetings import due_reminders
from .notifications import Reminder, _unread

router = APIRouter(prefix="/api/me", tags=["apps"])

WAIT_SECONDS = 25
STEP_SECONDS = 2


class FeedNotification(BaseModel):
    id: int
    kind: str
    params: dict
    link: str | None


class FeedMessage(BaseModel):
    conversation_id: int
    name: str
    kind: str  # channel or direct
    author: str | None
    body: str
    call: bool
    at: UtcDateTime


class Feed(BaseModel):
    unread: int
    chat_unread: int
    notifications: list[FeedNotification]
    messages: list[FeedMessage]
    calls: list[Ringing]
    reminders: list[dict]  # meetings starting within 10 minutes (the app shows each once)
    # Pass these back as notification_after / chat_after next time
    notification_after: int
    chat_after: str  # ISO time with microseconds, so the same message never comes twice


def _reminders(db, user: User) -> list[dict]:
    return [Reminder(**r).model_dump(mode="json") for r in due_reminders(db, user)]


def _snapshot(user_id: int, notification_after: int, chat_after: datetime) -> Feed:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return Feed(unread=0, chat_unread=0, notifications=[], messages=[], calls=[], reminders=[],
                        notification_after=notification_after, chat_after=chat_after.isoformat())
        rows = db.scalars(
            select(Notification).where(Notification.user_id == user.id, Notification.id > notification_after,
                                       Notification.read_at.is_(None)).order_by(Notification.id).limit(20)
        ).all()
        notes = [FeedNotification(id=n.id, kind=n.kind, params=json.loads(n.params or "{}"), link=n.link) for n in rows]
        messages = []
        newest = chat_after
        for c in conversations(user, db):
            if not c.unread or c.last is None or c.muted or c.notify == "none":
                continue
            at = c.last.at if c.last.at.tzinfo else c.last.at.replace(tzinfo=timezone.utc)
            if at <= chat_after:
                continue
            newest = max(newest, at)
            messages.append(FeedMessage(conversation_id=c.id, name=c.name, kind=c.kind, author=c.last.author,
                                        body=c.last.body, call=bool(c.last.call), at=at))
        calls = incoming(user, db)
        last_id = max([notification_after, *(n.id for n in notes)])
        return Feed(unread=_unread(db, user), chat_unread=unread_total(db, user), notifications=notes,
                    messages=messages, calls=calls, reminders=_reminders(db, user), notification_after=last_id, chat_after=newest.isoformat())


@router.get("/feed", response_model=Feed)
async def feed(user: CurrentUser, notification_after: int = Query(0, ge=0), chat_after: datetime | None = None,
               wait: bool = False) -> Feed:
    """What is new since the last call. With `wait`, hold the answer up to 25 s until something is there (a ringing
    call always counts). The first call (no cursors) only returns where things stand, so old items don't pop up."""
    user_id = user.id
    start = chat_after or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if notification_after == 0 and chat_after is None:
        with SessionLocal() as db:
            newest = db.scalar(select(Notification.id).where(Notification.user_id == user_id)
                               .order_by(Notification.id.desc()).limit(1)) or 0
        current = await asyncio.to_thread(_snapshot, user_id, newest, start)
        return current.model_copy(update={"notifications": [], "messages": []})
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (WAIT_SECONDS if wait else 0)
    while True:
        current = await asyncio.to_thread(_snapshot, user_id, notification_after, start)
        if current.notifications or current.messages or current.calls or loop.time() >= deadline:
            return current
        await asyncio.sleep(STEP_SECONDS)
