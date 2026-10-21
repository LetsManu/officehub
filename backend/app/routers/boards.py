"""Task boards in a space: columns, cards with assignees, due dates and comments."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select

from ..deps import DB, CurrentUser
from ..errors import ApiError, not_found
from ..models import PROJECT_COLORS, Board, BoardColumn, Card, CardAssignee, CardComment, Space, SpaceMember, User, utcnow
from ..schemas import UserBrief, UtcDateTime
from ..services.notifications import notify_many
from ..services.spaces import get_space, member_ids

router = APIRouter(prefix="/api/boards", tags=["boards"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ColumnName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)]


class CardOut(BaseModel):
    id: int
    column_id: int
    title: str
    position: int
    due_date: date | None
    label: str
    assignees: list[UserBrief]
    comment_count: int
    has_description: bool


class CommentOut(BaseModel):
    id: int
    author: UserBrief | None
    body: str
    created_at: UtcDateTime


class CardDetail(CardOut):
    description: str
    created_at: UtcDateTime
    comments: list[CommentOut]


class ColumnOut(BaseModel):
    id: int
    name: str
    position: int
    is_done: bool
    cards: list[CardOut]


class BoardOut(BaseModel):
    id: int
    name: str
    space_id: int
    space_name: str
    can_write: bool
    columns: list[ColumnOut]
    members: list[UserBrief]


class ColumnIn(BaseModel):
    name: ColumnName
    is_done: bool = False


class OrderIn(BaseModel):
    ids: list[int]


class CardIn(BaseModel):
    title: Title


class CardUpdate(BaseModel):
    title: Title
    description: Description = ""
    due_date: date | None = None
    label: str = ""
    assignee_ids: list[int] = []


class MoveIn(BaseModel):
    column_id: int
    position: int


class CommentIn(BaseModel):
    body: Body


class MyCard(BaseModel):
    id: int
    title: str
    due_date: date | None
    label: str
    column: str
    space_id: int
    space_name: str
    board_id: int


# ---------- helpers ----------


def _board(db: DB, user: User, board_id: int, write: bool = False) -> tuple[Board, Space]:
    board = db.get(Board, board_id)
    if board is None:
        raise not_found("Board")
    return board, get_space(db, user, board.space_id, write=write)


def _column(db: DB, user: User, column_id: int, write: bool = False) -> tuple[BoardColumn, Board, Space]:
    column = db.get(BoardColumn, column_id)
    if column is None:
        raise not_found("Column")
    board, space = _board(db, user, column.board_id, write)
    return column, board, space


def _card(db: DB, user: User, card_id: int, write: bool = False) -> tuple[Card, Board, Space]:
    card = db.get(Card, card_id)
    if card is None:
        raise not_found("Card")
    _column_, board, space = _column(db, user, card.column_id, write)
    return card, board, space


def _comment_counts(db: DB, card_ids: list[int]) -> dict[int, int]:
    if not card_ids:
        return {}
    rows = db.execute(select(CardComment.card_id, func.count()).where(CardComment.card_id.in_(card_ids)).group_by(CardComment.card_id))
    return dict(rows.all())


def _card_out(card: Card, comments: int) -> CardOut:
    return CardOut(
        id=card.id, column_id=card.column_id, title=card.title, position=card.position, due_date=card.due_date,
        label=card.label, assignees=[UserBrief.model_validate(a.user) for a in card.assignees],
        comment_count=comments, has_description=bool(card.description.strip()),
    )


def _card_detail(db: DB, card: Card) -> CardDetail:
    comments = db.scalars(select(CardComment).where(CardComment.card_id == card.id).order_by(CardComment.id)).all()
    base = _card_out(card, len(comments))
    return CardDetail(
        **base.model_dump(), description=card.description, created_at=card.created_at,
        comments=[CommentOut(id=c.id, author=UserBrief.model_validate(c.author) if c.author else None, body=c.body,
                             created_at=c.created_at) for c in comments],
    )


def _renumber(db: DB, column_id: int, moving: Card | None = None, position: int | None = None) -> None:
    cards = [c for c in db.scalars(select(Card).where(Card.column_id == column_id).order_by(Card.position, Card.id))
             if moving is None or c.id != moving.id]
    if moving is not None:
        cards.insert(max(0, min(position or 0, len(cards))), moving)
    for i, c in enumerate(cards):
        c.position = i


# ---------- endpoints ----------


@router.get("/mine", response_model=list[MyCard])
def my_cards(user: CurrentUser, db: DB) -> list[MyCard]:
    """Open cards assigned to me in all my spaces, soonest due first."""
    rows = db.execute(
        select(Card, BoardColumn, Board, Space)
        .join(CardAssignee, CardAssignee.card_id == Card.id)
        .join(BoardColumn, BoardColumn.id == Card.column_id)
        .join(Board, Board.id == BoardColumn.board_id)
        .join(Space, Space.id == Board.space_id)
        .join(SpaceMember, (SpaceMember.space_id == Space.id) & (SpaceMember.user_id == user.id))
        .where(CardAssignee.user_id == user.id, BoardColumn.is_done.is_(False), Space.archived.is_(False))
        .order_by(Card.due_date.is_(None), Card.due_date, Card.id)
    ).all()
    return [MyCard(id=c.id, title=c.title, due_date=c.due_date, label=c.label, column=col.name, space_id=s.id,
                   space_name=s.name, board_id=b.id) for c, col, b, s in rows]


@router.get("/{board_id}", response_model=BoardOut)
def get_board(board_id: int, user: CurrentUser, db: DB) -> BoardOut:
    board, space = _board(db, user, board_id)
    columns = db.scalars(select(BoardColumn).where(BoardColumn.board_id == board.id).order_by(BoardColumn.position, BoardColumn.id)).all()
    cards = db.scalars(select(Card).where(Card.column_id.in_([c.id for c in columns])).order_by(Card.position, Card.id)).all()
    counts = _comment_counts(db, [c.id for c in cards])
    members = db.scalars(select(User).where(User.id.in_(member_ids(db, space.id))).order_by(User.last_name, User.first_name))
    return BoardOut(
        id=board.id, name=board.name, space_id=space.id, space_name=space.name, can_write=not space.archived,
        columns=[ColumnOut(id=col.id, name=col.name, position=col.position, is_done=col.is_done,
                           cards=[_card_out(c, counts.get(c.id, 0)) for c in cards if c.column_id == col.id])
                 for col in columns],
        members=[UserBrief.model_validate(m) for m in members],
    )


@router.post("/{board_id}/columns", response_model=BoardOut, status_code=201)
def add_column(board_id: int, body: ColumnIn, user: CurrentUser, db: DB) -> BoardOut:
    board, _space = _board(db, user, board_id, write=True)
    last = db.scalar(select(func.max(BoardColumn.position)).where(BoardColumn.board_id == board.id))
    db.add(BoardColumn(board_id=board.id, name=body.name, is_done=body.is_done, position=(last or 0) + 1))
    db.commit()
    return get_board(board_id, user, db)


@router.put("/columns/{column_id}", response_model=BoardOut)
def update_column(column_id: int, body: ColumnIn, user: CurrentUser, db: DB) -> BoardOut:
    column, board, _space = _column(db, user, column_id, write=True)
    column.name, column.is_done = body.name, body.is_done
    db.commit()
    return get_board(board.id, user, db)


@router.delete("/columns/{column_id}", response_model=BoardOut)
def delete_column(column_id: int, user: CurrentUser, db: DB) -> BoardOut:
    column, board, _space = _column(db, user, column_id, write=True)
    if db.scalar(select(Card.id).where(Card.column_id == column.id).limit(1)) is not None:
        raise ApiError(409, "column_not_empty", "Move or delete the cards in this column first.")
    db.delete(column)
    db.commit()
    return get_board(board.id, user, db)


@router.put("/{board_id}/columns/order", response_model=BoardOut)
def order_columns(board_id: int, body: OrderIn, user: CurrentUser, db: DB) -> BoardOut:
    board, _space = _board(db, user, board_id, write=True)
    columns = {c.id: c for c in db.scalars(select(BoardColumn).where(BoardColumn.board_id == board.id))}
    if set(body.ids) != set(columns):
        raise ApiError(422, "validation", "Please send every column once.")
    for i, cid in enumerate(body.ids):
        columns[cid].position = i
    db.commit()
    return get_board(board.id, user, db)


@router.post("/columns/{column_id}/cards", response_model=CardOut, status_code=201)
def add_card(column_id: int, body: CardIn, user: CurrentUser, db: DB) -> CardOut:
    column, _board_, _space = _column(db, user, column_id, write=True)
    last = db.scalar(select(func.max(Card.position)).where(Card.column_id == column.id))
    card = Card(column_id=column.id, title=body.title, position=(last if last is not None else -1) + 1, created_by_id=user.id)
    db.add(card)
    db.commit()
    return _card_out(card, 0)


@router.get("/cards/{card_id}", response_model=CardDetail)
def get_card(card_id: int, user: CurrentUser, db: DB) -> CardDetail:
    card, _board_, _space = _card(db, user, card_id)
    return _card_detail(db, card)


@router.put("/cards/{card_id}", response_model=CardDetail)
def update_card(card_id: int, body: CardUpdate, user: CurrentUser, db: DB) -> CardDetail:
    card, _board_, space = _card(db, user, card_id, write=True)
    if body.label and body.label not in PROJECT_COLORS:
        raise ApiError(422, "invalid_choice", "Please choose one of the colours.")
    allowed = set(member_ids(db, space.id))
    wanted = set(body.assignee_ids)
    if not wanted <= allowed:
        raise ApiError(422, "assignee_invalid", "Only members of this space can be assigned.")
    before = {a.user_id for a in card.assignees}
    card.title, card.description, card.due_date, card.label = body.title, body.description, body.due_date, body.label
    card.assignees = [a for a in card.assignees if a.user_id in wanted]
    for uid in wanted - before:
        card.assignees.append(CardAssignee(user_id=uid))
    card.updated_at = utcnow()
    notify_many(db, wanted - before, user, "card_assigned", {"name": user.full_name, "title": card.title, "space": space.name},
                link=f"/spaces/{space.id}/board?card={card.id}")
    db.commit()
    return _card_detail(db, card)


@router.post("/cards/{card_id}/move", response_model=CardOut)
def move_card(card_id: int, body: MoveIn, user: CurrentUser, db: DB) -> CardOut:
    card, board, _space = _card(db, user, card_id, write=True)
    target = db.get(BoardColumn, body.column_id)
    if target is None or target.board_id != board.id:
        raise ApiError(422, "column_invalid", "This column does not exist.")
    source = card.column_id
    card.column_id = target.id
    card.updated_at = utcnow()
    db.flush()
    _renumber(db, target.id, card, body.position)
    if source != target.id:
        _renumber(db, source)
    db.commit()
    return _card_out(card, _comment_counts(db, [card.id]).get(card.id, 0))


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: int, user: CurrentUser, db: DB) -> None:
    card, _board_, _space = _card(db, user, card_id, write=True)
    column_id = card.column_id
    db.delete(card)
    db.flush()
    _renumber(db, column_id)
    db.commit()


@router.post("/cards/{card_id}/comments", response_model=CardDetail, status_code=201)
def add_comment(card_id: int, body: CommentIn, user: CurrentUser, db: DB) -> CardDetail:
    card, _board_, space = _card(db, user, card_id, write=True)
    db.add(CardComment(card_id=card.id, author_id=user.id, body=body.body))
    card.updated_at = utcnow()
    notify_many(db, [a.user_id for a in card.assignees], user, "card_comment",
                {"name": user.full_name, "title": card.title}, link=f"/spaces/{space.id}/board?card={card.id}")
    db.commit()
    return _card_detail(db, card)
