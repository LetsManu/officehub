"""Ideas box: anyone can suggest an improvement, colleagues support it, HR answers."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select

from ..deps import DB, HR, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import Idea, IdeaVote, User
from ..schemas import UserBrief, UtcDateTime
from ..services import notifications
from ..services.audit import audit

router = APIRouter(prefix="/api/ideas", tags=["ideas"])

Status = Literal["new", "review", "planned", "done", "declined"]


class IdeaIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class IdeaStatusIn(BaseModel):
    status: Status
    response: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class IdeaOut(BaseModel):
    id: int
    title: str
    body: str
    author: UserBrief
    status: str
    response: str
    votes: int
    voted: bool
    can_delete: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime


def _out(db, idea: Idea, user: User) -> IdeaOut:
    votes = db.scalar(select(func.count()).select_from(IdeaVote).where(IdeaVote.idea_id == idea.id)) or 0
    return IdeaOut(
        id=idea.id, title=idea.title, body=idea.body, author=UserBrief.model_validate(idea.author), status=idea.status,
        response=idea.response, votes=votes, voted=db.get(IdeaVote, (idea.id, user.id)) is not None,
        can_delete=user.is_hr or (idea.author_id == user.id and idea.status == "new"),
        created_at=idea.created_at, updated_at=idea.updated_at,
    )


@router.get("", response_model=list[IdeaOut])
def list_ideas(
    user: CurrentUser, db: DB, status: Status | None = None, sort: Literal["votes", "new"] = Query("votes")
) -> list[IdeaOut]:
    query = select(Idea)
    if status:
        query = query.where(Idea.status == status)
    items = [_out(db, i, user) for i in db.scalars(query.order_by(Idea.created_at.desc()))]
    if sort == "votes":
        items.sort(key=lambda i: (i.status in ("done", "declined"), -i.votes))
    return items


@router.post("", response_model=IdeaOut, status_code=201)
def create_idea(body: IdeaIn, user: CurrentUser, db: DB) -> IdeaOut:
    idea = Idea(title=body.title, body=body.body, author_id=user.id)
    db.add(idea)
    db.flush()
    db.add(IdeaVote(idea_id=idea.id, user_id=user.id))  # authors support their own idea
    db.commit()
    return _out(db, idea, user)


@router.post("/{idea_id}/vote", response_model=IdeaOut)
def toggle_vote(idea_id: int, user: CurrentUser, db: DB) -> IdeaOut:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise not_found("Idea")
    if idea.status in ("done", "declined"):
        raise ApiError(409, "idea_closed", "This idea is already decided.")
    vote = db.get(IdeaVote, (idea.id, user.id))
    if vote:
        db.delete(vote)
    else:
        db.add(IdeaVote(idea_id=idea.id, user_id=user.id))
    db.commit()
    return _out(db, idea, user)


@router.put("/{idea_id}/status", response_model=IdeaOut)
def set_status(idea_id: int, body: IdeaStatusIn, user: HR, db: DB) -> IdeaOut:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise not_found("Idea")
    idea.status, idea.response = body.status, body.response
    notifications.notify_many(db, [idea.author_id], user, "idea_status", {"title": idea.title, "status": body.status}, "/ideas")
    audit(db, user, "idea_status", idea.title, status=body.status)
    db.commit()
    return _out(db, idea, user)


@router.delete("/{idea_id}", status_code=204)
def delete_idea(idea_id: int, user: CurrentUser, db: DB) -> None:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise not_found("Idea")
    if not _out(db, idea, user).can_delete:
        raise forbidden("Only new ideas can be deleted by their author.")
    db.delete(idea)
    db.commit()
