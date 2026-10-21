"""Team chat: channels in spaces and direct conversations between two people.

The browser asks for new messages every few seconds while a conversation is open (no extra server needed).
Chat is only visible to members: HR does not read other people's conversations.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import DB, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import Channel, ChannelMember, Message, Space, SpaceFile, SpaceMember, User, utcnow
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


class FileRef(BaseModel):
    id: int
    name: str
    file_type: str
    size: int


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


class Messages(BaseModel):
    conversation: Conversation
    messages: list[MessageOut]
    members: list[UserBrief]
    has_more: bool


class MessageIn(BaseModel):
    body: Body = ""
    file_id: int | None = None
    mentions: list[int] = []


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


def unread_total(db: Session, user: User) -> int:
    """Unread messages in all of the person's conversations (for the menu badge)."""
    total = 0
    for channel in _my_channels(db, user):
        total += _unread(db, channel.id, user.id)
    return total


def _unread(db: Session, channel_id: int, user_id: int) -> int:
    last = db.scalar(select(ChannelMember.last_read_id).where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user_id)) or 0
    return db.scalar(select(func.count()).select_from(Message).where(
        Message.channel_id == channel_id, Message.id > last, Message.author_id != user_id, Message.deleted.is_(False))) or 0


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
    last = db.scalar(select(Message).where(Message.channel_id == channel.id, Message.deleted.is_(False)).order_by(Message.id.desc()).limit(1))
    return Conversation(
        id=channel.id, kind="channel" if space else "direct",
        name=channel.name if space else (other.full_name if other else "–"),
        space_id=space.id if space else None, space_name=space.name if space else None,
        other=UserBrief.model_validate(other) if other else None, unread=_unread(db, channel.id, user.id),
        last=LastMessage(body=(last.body or (last.file.name if last.file else ""))[:120],
                         author=last.author.first_name if last.author else None, at=last.created_at,
                         call=last.meeting_id is not None) if last else None,
    )


def _message_out(message: Message, user: User) -> MessageOut:
    return MessageOut(
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
             limit: int = Query(50, ge=1, le=100)) -> Messages:
    channel = _channel(db, user, channel_id)
    query = select(Message).where(Message.channel_id == channel.id)
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
    return Messages(conversation=_conversation(db, user, channel), messages=[_message_out(m, user) for m in rows],
                    members=[UserBrief.model_validate(u) for u in _participants(db, channel)], has_more=has_more)


@router.post("/{channel_id}/messages", response_model=MessageOut, status_code=201)
def send(channel_id: int, body: MessageIn, user: CurrentUser, db: DB) -> MessageOut:
    channel = _channel(db, user, channel_id)
    if channel.space_id is not None and db.get(Space, channel.space_id).archived:
        raise ApiError(409, "space_archived", "This space is archived.")
    if not body.body and body.file_id is None:
        raise ApiError(422, "message_empty", "Please write a message.")
    if body.file_id is not None:
        item = db.get(SpaceFile, body.file_id)
        if item is None or item.deleted_at is not None or item.space_id != channel.space_id:
            raise ApiError(422, "file_invalid", "Files can only be shared from this space.")
    message = Message(channel_id=channel.id, author_id=user.id, body=body.body, file_id=body.file_id)
    db.add(message)
    db.flush()
    _read_position(db, channel.id, user.id).last_read_id = message.id
    participants = {u.id for u in _participants(db, channel)}
    mentioned = set(body.mentions) & participants
    if mentioned:
        where = db.get(Space, channel.space_id).name if channel.space_id else ""
        link = f"/chat/{channel.id}"
        notify_many(db, mentioned, user, "chat_mention", {"name": user.full_name, "channel": channel.name, "space": where}, link=link)
    db.commit()
    return _message_out(message, user)


@router.put("/messages/{message_id}", response_model=MessageOut)
def edit(message_id: int, body: EditIn, user: CurrentUser, db: DB) -> MessageOut:
    message = db.get(Message, message_id)
    if message is None or message.deleted:
        raise not_found("Message")
    _channel(db, user, message.channel_id)
    if message.author_id != user.id:
        raise forbidden("You can only change your own messages.")
    message.body, message.edited_at = body.body, utcnow()
    db.commit()
    return _message_out(message, user)


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
    db.commit()


@router.post("/{channel_id}/read", status_code=204)
def mark_read(channel_id: int, body: ReadIn, user: CurrentUser, db: DB) -> None:
    channel = _channel(db, user, channel_id)
    row = _read_position(db, channel.id, user.id)
    row.last_read_id = max(row.last_read_id, body.last_id)
    db.commit()
