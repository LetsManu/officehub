"""Team chat: channels in spaces and direct conversations between two people.

Like Discord: replies in threads, emoji reactions, pinned messages, polls, voice messages and per-channel
notification settings (all / only mentions / none, or muted for a while).

The browser asks for new and changed messages every few seconds while a conversation is open (no extra server
needed). Chat is only visible to members: HR does not read other people's conversations.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..deps import DB, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import (
    Channel,
    ChannelMember,
    ChatPollOption,
    ChatPollVote,
    Message,
    Reaction,
    Space,
    SpaceFile,
    SpaceMember,
    User,
    utcnow,
)
from ..schemas import UserBrief, UtcDateTime
from ..services.notifications import notify_many

router = APIRouter(prefix="/api/chat", tags=["chat"])

Body = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
ChannelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class LastMessage(BaseModel):
    body: str
    author: str | None
    at: UtcDateTime
    call: bool = False


class Conversation(BaseModel):
    id: int
    kind: str  # channel or direct
    name: str
    space_id: int | None
    space_name: str | None
    other: UserBrief | None
    unread: int
    last: LastMessage | None
    notify: str = "all"  # all, mentions, none
    muted: bool = False


class FileRef(BaseModel):
    id: int
    name: str
    file_type: str
    size: int


class ReactionOut(BaseModel):
    emoji: str
    count: int
    mine: bool
    names: list[str]


class PollOptionOut(BaseModel):
    id: int
    text: str
    votes: int
    mine: bool
    voters: list[str]


class PollOut(BaseModel):
    options: list[PollOptionOut]
    multi: bool
    closed: bool
    total: int  # people who voted


class MessageOut(BaseModel):
    id: int
    author: UserBrief | None
    body: str
    file: FileRef | None
    created_at: UtcDateTime
    edited: bool
    deleted: bool
    mine: bool
    meeting: dict | None = None  # a call started in this conversation: {id, active}
    kind: str = "text"  # text, poll, voice
    parent_id: int | None = None
    reply_count: int = 0
    last_reply_at: UtcDateTime | None = None
    reply_people: list[str] = []
    pinned: bool = False
    reactions: list[ReactionOut] = []
    poll: PollOut | None = None
    audio_seconds: int | None = None


class Messages(BaseModel):
    conversation: Conversation
    messages: list[MessageOut]
    members: list[UserBrief]
    has_more: bool
    changed: list[MessageOut] = []  # earlier messages with new reactions, votes, replies … since `since`
    server_time: UtcDateTime | None = None


class Thread(BaseModel):
    parent: MessageOut
    replies: list[MessageOut]
    server_time: UtcDateTime


class MessageIn(BaseModel):
    body: Body = ""
    file_id: int | None = None
    mentions: list[int] = []
    parent_id: int | None = None  # reply in a thread


class ReactionIn(BaseModel):
    emoji: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]


class PollIn(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    options: Annotated[list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]],
                       Field(min_length=2, max_length=10)]
    multi: bool = False


class VoteIn(BaseModel):
    option_ids: list[int]


class SettingsIn(BaseModel):
    notify: Literal["all", "mentions", "none"] = "all"
    mute_minutes: int | None = Field(None, ge=0, le=60 * 24 * 30)  # 0 = unmute


class EditIn(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class DirectIn(BaseModel):
    user_id: int


class ChannelIn(BaseModel):
    space_id: int
    name: ChannelName


class ReadIn(BaseModel):
    last_id: int


# ---------- access ----------


def _member_of_space(db: Session, user: User, space_id: int) -> bool:
    return db.scalar(select(SpaceMember.id).where(SpaceMember.space_id == space_id, SpaceMember.user_id == user.id)) is not None


def _channel(db: Session, user: User, channel_id: int) -> Channel:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise not_found("Conversation")
    if channel.space_id is not None:
        if not _member_of_space(db, user, channel.space_id):
            raise not_found("Conversation")
    elif db.scalar(select(ChannelMember.id).where(ChannelMember.channel_id == channel.id, ChannelMember.user_id == user.id)) is None:
        raise not_found("Conversation")
    return channel


def _participants(db: Session, channel: Channel) -> list[User]:
    if channel.space_id is not None:
        ids = select(SpaceMember.user_id).where(SpaceMember.space_id == channel.space_id)
    else:
        ids = select(ChannelMember.user_id).where(ChannelMember.channel_id == channel.id)
    return list(db.scalars(select(User).where(User.id.in_(ids)).order_by(User.first_name, User.last_name)))


def _read_position(db: Session, channel_id: int, user_id: int) -> ChannelMember:
    row = db.scalar(select(ChannelMember).where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user_id))
    if row is None:
        row = ChannelMember(channel_id=channel_id, user_id=user_id, last_read_id=0)
        db.add(row)
        db.flush()
    return row


def _settings(db: Session, channel_id: int, user_id: int) -> tuple[str, bool]:
    """(notify level, muted right now) of one person in one conversation."""
    row = db.scalar(select(ChannelMember).where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user_id))
    if row is None:
        return "all", False
    return row.notify or "all", bool(row.muted_until and row.muted_until > utcnow())


def _wants(db: Session, channel_id: int, user_id: int, mentioned: bool) -> bool:
    """Should this person be notified about a new message here?"""
    level, muted = _settings(db, channel_id, user_id)
    return not muted and (level == "all" or (level == "mentions" and mentioned))


def unread_total(db: Session, user: User) -> int:
    """Unread messages for the menu badge: all of them where the person wants all, only mentions where they chose
    "mentions", none from muted conversations (like Discord)."""
    total = 0
    for channel in _my_channels(db, user):
        level, muted = _settings(db, channel.id, user.id)
        if muted or level == "none":
            continue
        total += _unread(db, channel.id, user.id, only_mentions=level == "mentions")
    return total


def _unread(db: Session, channel_id: int, user_id: int, only_mentions: bool = False) -> int:
    last = db.scalar(select(ChannelMember.last_read_id).where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user_id)) or 0
    query = select(func.count()).select_from(Message).where(
        Message.channel_id == channel_id, Message.id > last, Message.author_id != user_id, Message.deleted.is_(False),
        Message.parent_id.is_(None))
    if only_mentions:
        query = query.where(Message.mention_ids.like(f"%,{user_id},%"))
    return db.scalar(query) or 0


def _my_channels(db: Session, user: User) -> list[Channel]:
    spaces = select(SpaceMember.space_id).where(SpaceMember.user_id == user.id)
    channels = list(db.scalars(select(Channel).join(Space, Space.id == Channel.space_id)
                               .where(Channel.space_id.in_(spaces), Space.archived.is_(False))))
    channels += list(db.scalars(select(Channel).where(
        Channel.space_id.is_(None),
        Channel.id.in_(select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)))))
    return channels


def _conversation(db: Session, user: User, channel: Channel) -> Conversation:
    space = db.get(Space, channel.space_id) if channel.space_id else None
    other = None
    if channel.space_id is None:
        other = next((u for u in _participants(db, channel) if u.id != user.id), None)
    last = db.scalar(select(Message).where(Message.channel_id == channel.id, Message.deleted.is_(False),
                                           Message.parent_id.is_(None)).order_by(Message.id.desc()).limit(1))
    level, muted = _settings(db, channel.id, user.id)
    return Conversation(
        notify=level, muted=muted,
        id=channel.id, kind="channel" if space else "direct",
        name=channel.name if space else (other.full_name if other else "–"),
        space_id=space.id if space else None, space_name=space.name if space else None,
        other=UserBrief.model_validate(other) if other else None, unread=_unread(db, channel.id, user.id),
        last=LastMessage(body=(last.body or (last.file.name if last.file else "") or ("🎤" if last.kind == "voice" else ""))[:120],
                         author=last.author.first_name if last.author else None, at=last.created_at,
                         call=last.meeting_id is not None) if last else None,
    )


def _message_out(message: Message, user: User, db: Session | None = None) -> MessageOut:
    gone = message.deleted
    reactions: dict[str, list[Reaction]] = {}
    for r in message.reactions:
        reactions.setdefault(r.emoji, []).append(r)
    replies = []
    if db is not None and message.parent_id is None:
        replies = list(db.execute(select(Message.created_at, User.first_name).join(User, User.id == Message.author_id, isouter=True)
                                  .where(Message.parent_id == message.id, Message.deleted.is_(False)).order_by(Message.id)))
    poll = None
    if message.kind == "poll" and not gone:
        voters = {v.user_id for o in message.options for v in o.votes}
        poll = PollOut(multi=message.poll_multi, closed=message.poll_closed, total=len(voters), options=[
            PollOptionOut(id=o.id, text=o.text, votes=len(o.votes), mine=any(v.user_id == user.id for v in o.votes),
                          voters=[v.user.full_name for v in o.votes][:20]) for o in message.options])
    return MessageOut(
        kind=message.kind or "text", parent_id=message.parent_id, pinned=message.pinned and not gone,
        reply_count=len(replies), last_reply_at=replies[-1][0] if replies else None,
        reply_people=list(dict.fromkeys(name for _at, name in replies if name))[:3],
        reactions=[] if gone else [ReactionOut(emoji=e, count=len(rs), mine=any(r.user_id == user.id for r in rs),
                                               names=[r.user.full_name for r in rs][:15]) for e, rs in reactions.items()],
        poll=poll, audio_seconds=message.audio_seconds if message.kind == "voice" and not gone else None,
        id=message.id, author=UserBrief.model_validate(message.author) if message.author else None,
        body="" if message.deleted else message.body,
        file=FileRef(id=message.file.id, name=message.file.name, file_type=message.file.file_type, size=message.file.size)
        if message.file and not message.deleted and message.file.deleted_at is None else None,
        created_at=message.created_at, edited=message.edited_at is not None, deleted=message.deleted,
        mine=message.author_id == user.id,
        meeting={"id": message.meeting.id, "active": message.meeting.ended_at is None} if message.meeting else None,
    )


# ---------- endpoints ----------


@router.get("", response_model=list[Conversation])
def conversations(user: CurrentUser, db: DB) -> list[Conversation]:
    items = [_conversation(db, user, c) for c in _my_channels(db, user)]
    items.sort(key=lambda c: (c.last.at.timestamp() if c.last else 0), reverse=True)
    return items


@router.post("/direct", response_model=Conversation)
def direct(body: DirectIn, user: CurrentUser, db: DB) -> Conversation:
    return _conversation(db, user, direct_channel(db, user, body.user_id))


def direct_channel(db: DB, user: User, other_id: int) -> Channel:
    """The one conversation between two people (made on first use)."""
    other = db.get(User, other_id)
    if other is None or not other.is_active or other.id == user.id:
        raise ApiError(422, "person_required", "Please choose a person.")
    key = f"{min(user.id, other.id)}:{max(user.id, other.id)}"
    channel = db.scalar(select(Channel).where(Channel.direct_key == key))
    if channel is None:
        channel = Channel(direct_key=key)
        db.add(channel)
        db.flush()
        db.add_all([ChannelMember(channel_id=channel.id, user_id=user.id), ChannelMember(channel_id=channel.id, user_id=other.id)])
        db.commit()
    return channel


@router.post("/channels", response_model=Conversation, status_code=201)
def new_channel(body: ChannelIn, user: CurrentUser, db: DB) -> Conversation:
    space = db.get(Space, body.space_id)
    if space is None or not _member_of_space(db, user, space.id):
        raise not_found("Space")
    if space.archived:
        raise ApiError(409, "space_archived", "This space is archived.")
    channel = Channel(space_id=space.id, name=body.name)
    db.add(channel)
    db.commit()
    return _conversation(db, user, channel)


@router.get("/{channel_id}/messages", response_model=Messages)
def messages(channel_id: int, user: CurrentUser, db: DB, after: int = 0, before: int | None = None,
             limit: int = Query(50, ge=1, le=100), since: datetime | None = None) -> Messages:
    channel = _channel(db, user, channel_id)
    now = utcnow()
    query = select(Message).where(Message.channel_id == channel.id, Message.parent_id.is_(None))
    if after:
        rows = db.scalars(query.where(Message.id > after).order_by(Message.id).limit(limit + 1)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
    else:
        if before:
            query = query.where(Message.id < before)
        rows = list(reversed(db.scalars(query.order_by(Message.id.desc()).limit(limit + 1)).all()))
        has_more = len(rows) > limit
        rows = rows[-limit:]
    changed = []
    if since is not None:
        known = {m.id for m in rows}
        changed = [m for m in db.scalars(query.where(Message.changed_at >= _naive(since), Message.id <= (after or 0))
                                         .order_by(Message.id).limit(200)) if m.id not in known]
    return Messages(conversation=_conversation(db, user, channel), messages=[_message_out(m, user, db) for m in rows],
                    members=[UserBrief.model_validate(u) for u in _participants(db, channel)], has_more=has_more,
                    changed=[_message_out(m, user, db) for m in changed], server_time=now)


def _naive(value: datetime) -> datetime:
    """Times from the browser come with a time zone; they are stored as UTC without one."""
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _message(db: Session, user: User, message_id: int) -> tuple[Message, Channel]:
    message = db.get(Message, message_id)
    if message is None:
        raise not_found("Message")
    return message, _channel(db, user, message.channel_id)


def _touch(message: Message) -> None:
    """Mark a message as changed so open chats fetch it again (and its thread's first message)."""
    message.changed_at = utcnow()


def _writable(db: Session, channel: Channel) -> None:
    if channel.space_id is not None and db.get(Space, channel.space_id).archived:
        raise ApiError(409, "space_archived", "This space is archived.")


def _thread_parent(db: Session, channel: Channel, parent_id: int | None) -> Message | None:
    if parent_id is None:
        return None
    parent = db.get(Message, parent_id)
    if parent is None or parent.channel_id != channel.id or parent.parent_id is not None or parent.deleted:
        raise ApiError(422, "thread_invalid", "This thread does not exist here.")
    return parent


def _after_post(db: Session, user: User, channel: Channel, message: Message, mentions: list[int]) -> None:
    """Read position, mentions and thread notifications for a new message."""
    if message.parent_id is None:
        _read_position(db, channel.id, user.id).last_read_id = message.id
    participants = {u.id for u in _participants(db, channel)}
    mentioned = (set(mentions) & participants) - {user.id}
    message.mention_ids = "," + ",".join(str(i) for i in sorted(mentioned)) + "," if mentioned else ""
    where = db.get(Space, channel.space_id).name if channel.space_id else ""
    link = f"/chat/{channel.id}" + (f"?thread={message.parent_id}" if message.parent_id else "")
    wanted = [uid for uid in mentioned if _wants(db, channel.id, uid, mentioned=True)]
    if wanted:
        notify_many(db, wanted, user, "chat_mention", {"name": user.full_name, "channel": channel.name, "space": where}, link=link)
    if message.parent_id is not None:
        parent = db.get(Message, message.parent_id)
        _touch(parent)
        involved = {parent.author_id} | set(db.scalars(select(Message.author_id).where(Message.parent_id == parent.id)))
        involved = {uid for uid in involved if uid and uid in participants and uid != user.id and uid not in mentioned}
        notify_many(db, [uid for uid in involved if _wants(db, channel.id, uid, mentioned=True)], user, "chat_reply",
                    {"name": user.full_name, "text": (parent.body or "")[:60]}, link=link)


@router.get("/messages/{message_id}/thread", response_model=Thread)
def thread(message_id: int, user: CurrentUser, db: DB) -> Thread:
    parent, _channel_row = _message(db, user, message_id)
    if parent.parent_id is not None:
        parent = db.get(Message, parent.parent_id)
    replies = db.scalars(select(Message).where(Message.parent_id == parent.id).order_by(Message.id))
    return Thread(parent=_message_out(parent, user, db), replies=[_message_out(m, user) for m in replies], server_time=utcnow())


@router.post("/{channel_id}/messages", response_model=MessageOut, status_code=201)
def send(channel_id: int, body: MessageIn, user: CurrentUser, db: DB) -> MessageOut:
    channel = _channel(db, user, channel_id)
    _writable(db, channel)
    parent = _thread_parent(db, channel, body.parent_id)
    if not body.body and body.file_id is None:
        raise ApiError(422, "message_empty", "Please write a message.")
    if body.file_id is not None:
        item = db.get(SpaceFile, body.file_id)
        if item is None or item.deleted_at is not None or item.space_id != channel.space_id:
            raise ApiError(422, "file_invalid", "Files can only be shared from this space.")
    message = Message(channel_id=channel.id, author_id=user.id, body=body.body, file_id=body.file_id,
                      parent_id=parent.id if parent else None)
    db.add(message)
    db.flush()
    _after_post(db, user, channel, message, body.mentions)
    db.commit()
    return _message_out(message, user, db)


@router.put("/messages/{message_id}", response_model=MessageOut)
def edit(message_id: int, body: EditIn, user: CurrentUser, db: DB) -> MessageOut:
    message = db.get(Message, message_id)
    if message is None or message.deleted:
        raise not_found("Message")
    _channel(db, user, message.channel_id)
    if message.author_id != user.id:
        raise forbidden("You can only change your own messages.")
    message.body, message.edited_at = body.body, utcnow()
    _touch(message)
    db.commit()
    return _message_out(message, user, db)


@router.delete("/messages/{message_id}", status_code=204)
def delete(message_id: int, user: CurrentUser, db: DB) -> None:
    message = db.get(Message, message_id)
    if message is None or message.deleted:
        raise not_found("Message")
    channel = _channel(db, user, message.channel_id)
    is_manager = channel.space_id is not None and db.scalar(select(SpaceMember.role).where(
        SpaceMember.space_id == channel.space_id, SpaceMember.user_id == user.id)) == "manager"
    if message.author_id != user.id and not is_manager:
        raise forbidden("You can only delete your own messages.")
    message.deleted, message.body, message.file_id = True, "", None
    if message.audio_path:
        (settings.upload_dir / message.audio_path).unlink(missing_ok=True)
        message.audio_path = None
    _touch(message)
    if message.parent_id:
        _touch(db.get(Message, message.parent_id))
    db.commit()


@router.post("/{channel_id}/read", status_code=204)
def mark_read(channel_id: int, body: ReadIn, user: CurrentUser, db: DB) -> None:
    channel = _channel(db, user, channel_id)
    row = _read_position(db, channel.id, user.id)
    row.last_read_id = max(row.last_read_id, body.last_id)
    db.commit()


# ---------- reactions, pins ----------


@router.post("/messages/{message_id}/reactions", response_model=MessageOut)
def react(message_id: int, body: ReactionIn, user: CurrentUser, db: DB) -> MessageOut:
    """Add my reaction, or take it back when it is already there."""
    message, _channel_row = _message(db, user, message_id)
    if message.deleted or any(c.isascii() and c.isalnum() for c in body.emoji):
        raise ApiError(422, "invalid_emoji", "Please choose an emoji.")
    mine = next((r for r in message.reactions if r.user_id == user.id and r.emoji == body.emoji), None)
    if mine is not None:
        message.reactions.remove(mine)
    elif len({r.emoji for r in message.reactions}) >= 20:
        raise ApiError(422, "too_many_reactions", "This message has enough different reactions.")
    else:
        message.reactions.append(Reaction(user_id=user.id, emoji=body.emoji))
    _touch(message)
    db.commit()
    db.refresh(message)
    return _message_out(message, user, db)


@router.post("/messages/{message_id}/pin", response_model=MessageOut)
def pin(message_id: int, user: CurrentUser, db: DB) -> MessageOut:
    message, channel = _message(db, user, message_id)
    if message.deleted or message.parent_id is not None:
        raise ApiError(422, "cannot_pin", "Only messages in the conversation can be pinned.")
    _writable(db, channel)
    message.pinned = not message.pinned
    _touch(message)
    db.commit()
    return _message_out(message, user, db)


@router.get("/{channel_id}/pins", response_model=list[MessageOut])
def pins(channel_id: int, user: CurrentUser, db: DB) -> list[MessageOut]:
    channel = _channel(db, user, channel_id)
    rows = db.scalars(select(Message).where(Message.channel_id == channel.id, Message.pinned.is_(True),
                                            Message.deleted.is_(False)).order_by(Message.id.desc()))
    return [_message_out(m, user, db) for m in rows]


# ---------- polls ----------


@router.post("/{channel_id}/polls", response_model=MessageOut, status_code=201)
def new_poll(channel_id: int, body: PollIn, user: CurrentUser, db: DB) -> MessageOut:
    channel = _channel(db, user, channel_id)
    _writable(db, channel)
    texts = list(dict.fromkeys(body.options))
    if len(texts) < 2:
        raise ApiError(422, "poll_options", "Please give at least two different answers.")
    message = Message(channel_id=channel.id, author_id=user.id, body=body.question, kind="poll", poll_multi=body.multi,
                      options=[ChatPollOption(text=text, position=i) for i, text in enumerate(texts)])
    db.add(message)
    db.flush()
    _after_post(db, user, channel, message, [])
    db.commit()
    return _message_out(message, user, db)


@router.post("/messages/{message_id}/vote", response_model=MessageOut)
def vote(message_id: int, body: VoteIn, user: CurrentUser, db: DB) -> MessageOut:
    """Set my answer (replaces an earlier one; an empty list takes my vote back)."""
    message, _channel_row = _message(db, user, message_id)
    if message.kind != "poll" or message.deleted:
        raise not_found("Poll")
    if message.poll_closed:
        raise ApiError(409, "poll_closed", "This poll is closed.")
    chosen = set(body.option_ids)
    valid = {o.id for o in message.options}
    if not chosen <= valid or (not message.poll_multi and len(chosen) > 1):
        raise ApiError(422, "invalid_choice", "Please choose one of the answers.")
    for option in message.options:
        mine = next((v for v in option.votes if v.user_id == user.id), None)
        if option.id in chosen and mine is None:
            option.votes.append(ChatPollVote(user_id=user.id))
        elif option.id not in chosen and mine is not None:
            option.votes.remove(mine)
    _touch(message)
    db.commit()
    db.refresh(message)
    return _message_out(message, user, db)


@router.post("/messages/{message_id}/close-poll", response_model=MessageOut)
def close_poll(message_id: int, user: CurrentUser, db: DB) -> MessageOut:
    message, _channel_row = _message(db, user, message_id)
    if message.kind != "poll":
        raise not_found("Poll")
    if message.author_id != user.id:
        raise forbidden("Only the person who asked can close the poll.")
    message.poll_closed = True
    _touch(message)
    db.commit()
    return _message_out(message, user, db)


# ---------- voice messages ----------

AUDIO_TYPES = {"audio/webm": b"\x1a\x45\xdf\xa3", "audio/ogg": b"OggS", "audio/mp4": None}
VOICE_MAX_BYTES = 6 * 1024 * 1024
VOICE_MAX_SECONDS = 300


@router.post("/{channel_id}/voice", response_model=MessageOut, status_code=201)
async def voice(channel_id: int, user: CurrentUser, db: DB, file: UploadFile = File(...),
                seconds: int = Form(..., ge=1, le=VOICE_MAX_SECONDS), parent_id: int | None = Form(None)) -> MessageOut:
    """A short recorded voice message (recorded in the browser, stored like other uploads)."""
    channel = _channel(db, user, channel_id)
    _writable(db, channel)
    parent = _thread_parent(db, channel, parent_id)
    data = await file.read(VOICE_MAX_BYTES + 1)
    if len(data) > VOICE_MAX_BYTES:
        raise ApiError(413, "file_too_large", "The voice message is too long.")
    kind = (file.content_type or "").split(";")[0].strip()
    magic = AUDIO_TYPES.get(kind, b"?")
    if magic == b"?" or (magic is not None and not data.startswith(magic)) or (magic is None and data[4:8] != b"ftyp"):
        raise ApiError(422, "file_type", "This recording cannot be used.")
    folder = settings.upload_dir / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"voice/{secrets.token_hex(16)}"
    (settings.upload_dir / name).write_bytes(data)
    message = Message(channel_id=channel.id, author_id=user.id, kind="voice", audio_path=name, audio_type=kind,
                      audio_seconds=seconds, parent_id=parent.id if parent else None)
    db.add(message)
    db.flush()
    _after_post(db, user, channel, message, [])
    db.commit()
    return _message_out(message, user, db)


@router.get("/messages/{message_id}/audio")
def audio(message_id: int, user: CurrentUser, db: DB) -> FileResponse:
    message, _channel_row = _message(db, user, message_id)
    if message.kind != "voice" or message.deleted or not message.audio_path:
        raise not_found("Voice message")
    return FileResponse(settings.upload_dir / message.audio_path, media_type=message.audio_type or "audio/webm",
                        headers={"Cache-Control": "private, max-age=86400"})


# ---------- notification settings per conversation ----------


@router.put("/{channel_id}/settings", response_model=Conversation)
def conversation_settings(channel_id: int, body: SettingsIn, user: CurrentUser, db: DB) -> Conversation:
    channel = _channel(db, user, channel_id)
    row = _read_position(db, channel.id, user.id)
    row.notify = body.notify
    if body.mute_minutes is not None:
        row.muted_until = utcnow() + timedelta(minutes=body.mute_minutes) if body.mute_minutes else None
    db.commit()
    return _conversation(db, user, channel)
