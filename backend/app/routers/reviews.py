"""Yearly employee review conversations.

HR starts a review for a person and their reviewer. Both prepare separately; each person only
sees the other's preparation once both have finished theirs. After the meeting the reviewer
records the agreed goals and both confirm. Only the two participants and HR can see a review.
"""

import json
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import or_, select

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import Review, User, utcnow
from ..schemas import UserBrief, UtcDateTime
from ..services import notifications

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

EMPLOYEE_QUESTIONS = ("achievements", "challenges", "support", "wishes")
REVIEWER_QUESTIONS = ("strengths", "development", "feedback")

Answer = Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)]


class ReviewCreate(BaseModel):
    employee_id: int
    reviewer_id: int
    year: Annotated[int, Field(ge=2000, le=2100)]
    meeting_date: date | None = None


class PrepIn(BaseModel):
    answers: dict[str, Answer]
    done: bool = False


class ReviewUpdate(BaseModel):
    meeting_date: date | None = None
    goals: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None


class ReviewOut(BaseModel):
    id: int
    year: int
    status: str
    employee: UserBrief
    reviewer: UserBrief
    meeting_date: date | None
    my_side: Literal["employee", "reviewer", "hr"]
    employee_prep_done: bool
    reviewer_prep_done: bool
    # Answers are only included where the viewer may read them
    employee_prep: dict[str, str] | None
    reviewer_prep: dict[str, str] | None
    goals: str
    employee_confirmed_at: UtcDateTime | None
    reviewer_confirmed_at: UtcDateTime | None
    updated_at: UtcDateTime


def _side(review: Review, user: User) -> Literal["employee", "reviewer", "hr"] | None:
    if review.employee_id == user.id:
        return "employee"
    if review.reviewer_id == user.id:
        return "reviewer"
    return "hr" if user.is_admin else None


def _out(review: Review, user: User) -> ReviewOut:
    side = _side(review, user)
    assert side is not None
    both_done = review.employee_prep_done and review.reviewer_prep_done
    show_employee = side in ("employee", "hr") or both_done
    show_reviewer = side in ("reviewer", "hr") or both_done
    return ReviewOut(
        id=review.id,
        year=review.year,
        status=review.status,
        employee=review.employee,
        reviewer=review.reviewer,
        meeting_date=review.meeting_date,
        my_side=side,
        employee_prep_done=review.employee_prep_done,
        reviewer_prep_done=review.reviewer_prep_done,
        employee_prep=json.loads(review.employee_prep or "{}") if show_employee else None,
        reviewer_prep=json.loads(review.reviewer_prep or "{}") if show_reviewer else None,
        goals=review.goals,
        employee_confirmed_at=review.employee_confirmed_at,
        reviewer_confirmed_at=review.reviewer_confirmed_at,
        updated_at=review.updated_at,
    )


def _load(db, review_id: int, user: User) -> Review:
    review = db.get(Review, review_id)
    if review is None or _side(review, user) is None:
        raise not_found("Review")
    return review


@router.get("", response_model=list[ReviewOut])
def list_reviews(user: CurrentUser, db: DB) -> list[ReviewOut]:
    query = select(Review)
    if not user.is_admin:
        query = query.where(or_(Review.employee_id == user.id, Review.reviewer_id == user.id))
    rows = db.scalars(query.order_by(Review.year.desc(), Review.id.desc()))
    return [_out(r, user) for r in rows]


@router.post("", response_model=ReviewOut, status_code=201)
def create_review(body: ReviewCreate, user: Admin, db: DB) -> ReviewOut:
    employee, reviewer = db.get(User, body.employee_id), db.get(User, body.reviewer_id)
    if employee is None or reviewer is None or not employee.is_active or not reviewer.is_active:
        raise ApiError(422, "person_invalid", "Please choose active people.")
    if employee.id == reviewer.id:
        raise ApiError(422, "same_person", "The reviewer must be a different person.")
    exists = db.scalar(select(Review).where(Review.employee_id == employee.id, Review.year == body.year))
    if exists:
        raise ApiError(409, "review_exists", "This person already has a review for that year.")
    review = Review(**body.model_dump())
    db.add(review)
    db.flush()
    for person, other in ((employee, reviewer), (reviewer, employee)):
        notifications.notify(
            db, person.id, "review_created", {"name": other.full_name, "year": body.year}, f"/reviews/{review.id}"
        )
    db.commit()
    db.refresh(review)
    return _out(review, user)


@router.get("/{review_id}", response_model=ReviewOut)
def get_review(review_id: int, user: CurrentUser, db: DB) -> ReviewOut:
    return _out(_load(db, review_id, user), user)


@router.put("/{review_id}/prep", response_model=ReviewOut)
def save_prep(review_id: int, body: PrepIn, user: CurrentUser, db: DB) -> ReviewOut:
    review = _load(db, review_id, user)
    side = _side(review, user)
    if side == "hr":
        raise forbidden("Only the participants prepare the review.")
    if review.status == "completed":
        raise ApiError(409, "review_closed", "This review is already completed.")
    questions = EMPLOYEE_QUESTIONS if side == "employee" else REVIEWER_QUESTIONS
    answers = {key: body.answers.get(key, "") for key in questions}
    if side == "employee":
        review.employee_prep, review.employee_prep_done = json.dumps(answers), body.done
    else:
        review.reviewer_prep, review.reviewer_prep_done = json.dumps(answers), body.done
    db.commit()
    return _out(review, user)


@router.patch("/{review_id}", response_model=ReviewOut)
def update_review(review_id: int, body: ReviewUpdate, user: CurrentUser, db: DB) -> ReviewOut:
    review = _load(db, review_id, user)
    if _side(review, user) not in ("reviewer", "hr"):
        raise forbidden("Only the reviewer or HR can change this.")
    if review.status == "completed":
        raise ApiError(409, "review_closed", "This review is already completed.")
    changes = body.model_dump(exclude_unset=True)
    if "goals" in changes and changes["goals"] is not None and changes["goals"] != review.goals:
        # Changed goals must be confirmed again by both.
        review.employee_confirmed_at = review.reviewer_confirmed_at = None
    for field, value in changes.items():
        if value is not None or field == "meeting_date":
            setattr(review, field, value)
    db.commit()
    return _out(review, user)


@router.post("/{review_id}/confirm", response_model=ReviewOut)
def confirm(review_id: int, user: CurrentUser, db: DB) -> ReviewOut:
    review = _load(db, review_id, user)
    side = _side(review, user)
    if side == "hr":
        raise forbidden("Only the participants confirm the review.")
    if not review.goals.strip():
        raise ApiError(409, "goals_missing", "The agreed goals have not been written down yet.")
    now = utcnow()
    if side == "employee":
        review.employee_confirmed_at = review.employee_confirmed_at or now
    else:
        review.reviewer_confirmed_at = review.reviewer_confirmed_at or now
    if review.employee_confirmed_at and review.reviewer_confirmed_at:
        review.status = "completed"
    db.commit()
    return _out(review, user)
