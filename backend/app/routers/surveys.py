"""Anonymous pulse surveys.

Answers are stored without the person and without a timestamp. A separate table only remembers
that someone took part, so nobody can answer twice. Results appear from five answers on, so a
single person's answers cannot be singled out.
"""

import json
import random
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import func, select

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, not_found
from ..models import Survey, SurveyParticipation, SurveyResponse, User
from ..services import notifications
from ..services.audit import audit

router = APIRouter(prefix="/api/surveys", tags=["surveys"])

MIN_RESULTS = 5

Text150 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Option = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class Question(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    kind: Literal["scale", "choice", "text"]
    options: Annotated[list[Option], Field(max_length=8)] = []

    @model_validator(mode="after")
    def _options(self):
        if self.kind == "choice" and len(self.options) < 2:
            raise ValueError("A choice question needs at least two options.")
        if self.kind != "choice":
            self.options = []
        return self


class SurveyIn(BaseModel):
    title: Text150
    intro: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    questions: Annotated[list[Question], Field(min_length=1, max_length=10)]
    closes_on: date | None = None
    results_public: bool = False


class SurveyUpdate(BaseModel):
    status: Literal["open", "closed"] | None = None
    closes_on: date | None = None
    results_public: bool | None = None


class SurveyOut(BaseModel):
    id: int
    title: str
    intro: str
    questions: list[Question]
    status: str
    closes_on: date | None
    results_public: bool
    answered: bool
    responses: int
    can_see_results: bool


class AnswersIn(BaseModel):
    # One answer per question: 1–5 for scale, option index for choice, text for text (may be empty)
    answers: Annotated[list[int | str | None], Field(max_length=10)]


class QuestionResult(BaseModel):
    text: str
    kind: str
    options: list[str]
    counts: list[int]  # scale: 1..5, choice: per option
    average: float | None
    texts: list[str]


class Results(BaseModel):
    survey: SurveyOut
    responses: int
    enough: bool
    questions: list[QuestionResult]


def _is_open(survey: Survey) -> bool:
    return survey.status == "open" and (survey.closes_on is None or survey.closes_on >= date.today())


def _count(db, survey: Survey) -> int:
    return db.scalar(select(func.count()).select_from(SurveyResponse).where(SurveyResponse.survey_id == survey.id)) or 0


def _out(db, survey: Survey, user: User) -> SurveyOut:
    status = "closed" if survey.status == "open" and not _is_open(survey) else survey.status
    return SurveyOut(
        id=survey.id, title=survey.title, intro=survey.intro, questions=json.loads(survey.questions),
        status=status, closes_on=survey.closes_on, results_public=survey.results_public,
        answered=db.get(SurveyParticipation, (survey.id, user.id)) is not None,
        responses=_count(db, survey),
        can_see_results=user.is_admin or (survey.results_public and status == "closed"),
    )


def _load(db, survey_id: int, user: User) -> Survey:
    survey = db.get(Survey, survey_id)
    if survey is None or (survey.status == "draft" and not user.is_admin):
        raise not_found("Survey")
    return survey


@router.get("", response_model=list[SurveyOut])
def list_surveys(user: CurrentUser, db: DB) -> list[SurveyOut]:
    query = select(Survey).order_by(Survey.created_at.desc())
    if not user.is_admin:
        query = query.where(Survey.status != "draft")
    return [_out(db, s, user) for s in db.scalars(query)]


@router.post("", response_model=SurveyOut, status_code=201)
def create_survey(body: SurveyIn, user: Admin, db: DB) -> SurveyOut:
    survey = Survey(
        title=body.title, intro=body.intro, questions=json.dumps([q.model_dump() for q in body.questions]),
        closes_on=body.closes_on, results_public=body.results_public, created_by_id=user.id,
    )
    db.add(survey)
    audit(db, user, "survey_created", body.title)
    db.commit()
    return _out(db, survey, user)


@router.patch("/{survey_id}", response_model=SurveyOut)
def update_survey(survey_id: int, body: SurveyUpdate, user: Admin, db: DB) -> SurveyOut:
    survey = _load(db, survey_id, user)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("status") == "open" and survey.status == "draft":
        people = db.scalars(select(User.id).where(User.is_active.is_(True)))
        notifications.notify_many(db, people, user, "survey_new", {"title": survey.title}, f"/surveys/{survey.id}")
    if changes.get("status") == "closed":
        audit(db, user, "survey_closed", survey.title)
    for field, value in changes.items():
        if value is not None or field == "closes_on":
            setattr(survey, field, value)
    db.commit()
    return _out(db, survey, user)


@router.post("/{survey_id}/respond", response_model=SurveyOut)
def respond(survey_id: int, body: AnswersIn, user: CurrentUser, db: DB) -> SurveyOut:
    survey = _load(db, survey_id, user)
    if not _is_open(survey):
        raise ApiError(409, "survey_closed", "This survey is closed.")
    if db.get(SurveyParticipation, (survey.id, user.id)):
        raise ApiError(409, "survey_answered", "You have already answered this survey.")
    questions = json.loads(survey.questions)
    if len(body.answers) != len(questions):
        raise ApiError(422, "survey_incomplete", "Please answer every question.")
    clean: list[int | str | None] = []
    for question, answer in zip(questions, body.answers):
        if question["kind"] == "scale":
            if not isinstance(answer, int) or not 1 <= answer <= 5:
                raise ApiError(422, "survey_incomplete", "Please answer every question.")
            clean.append(answer)
        elif question["kind"] == "choice":
            if not isinstance(answer, int) or not 0 <= answer < len(question["options"]):
                raise ApiError(422, "survey_incomplete", "Please answer every question.")
            clean.append(answer)
        else:
            text = str(answer or "").strip()[:1000]
            clean.append(text or None)
    db.add(SurveyParticipation(survey_id=survey.id, user_id=user.id))
    db.add(SurveyResponse(survey_id=survey.id, answers=json.dumps(clean)))
    db.commit()
    return _out(db, survey, user)


@router.get("/{survey_id}/results", response_model=Results)
def results(survey_id: int, user: CurrentUser, db: DB) -> Results:
    survey = _load(db, survey_id, user)
    out = _out(db, survey, user)
    if not out.can_see_results:
        raise not_found("Results")
    rows = [json.loads(r) for r in db.scalars(select(SurveyResponse.answers).where(SurveyResponse.survey_id == survey.id))]
    enough = len(rows) >= MIN_RESULTS
    questions: list[QuestionResult] = []
    for i, question in enumerate(json.loads(survey.questions)):
        values = [row[i] for row in rows if i < len(row) and row[i] is not None]
        size = 5 if question["kind"] == "scale" else len(question.get("options", []))
        counts = [0] * size
        texts: list[str] = []
        if enough:
            for value in values:
                if question["kind"] == "scale":
                    counts[value - 1] += 1
                elif question["kind"] == "choice":
                    counts[value] += 1
                else:
                    texts.append(value)
            random.shuffle(texts)  # the order must not reveal who answered when
        average = round(sum(values) / len(values), 1) if enough and question["kind"] == "scale" and values else None
        questions.append(QuestionResult(text=question["text"], kind=question["kind"], options=question.get("options", []),
                                        counts=counts, average=average, texts=texts))
    return Results(survey=out, responses=len(rows), enough=enough, questions=questions)
