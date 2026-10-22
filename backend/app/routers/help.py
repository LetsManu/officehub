"""Help pages: short questions and answers HR maintains, grouped by portal section."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import or_, select

from ..deps import DB, HR, CurrentUser
from ..errors import not_found
from ..models import HelpArticle
from ..schemas import UtcDateTime

router = APIRouter(prefix="/api/help", tags=["help"])

Section = Literal["general", "dashboard", "requests", "documents", "announcements", "directory", "rooms", "visitors"]


class ArticleIn(BaseModel):
    section: Section = "general"
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    sort_order: Annotated[int, Field(ge=0, le=1000)] = 0
    active: bool = True


class ArticleOut(BaseModel):
    id: int
    section: str
    question: str
    answer: str
    sort_order: int
    active: bool
    helpful_yes: int
    helpful_no: int
    updated_at: UtcDateTime

    model_config = {"from_attributes": True}


class FeedbackIn(BaseModel):
    helpful: bool


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=list[ArticleOut])
def list_articles(
    user: CurrentUser,
    db: DB,
    q: str | None = Query(None, max_length=100),
    section: Section | None = None,
    include_inactive: bool = False,
) -> list[HelpArticle]:
    query = select(HelpArticle)
    if not (include_inactive and user.is_hr):
        query = query.where(HelpArticle.active.is_(True))
    if section:
        query = query.where(HelpArticle.section == section)
    if term := (q or "").strip():
        pattern = f"%{_escape_like(term)}%"
        query = query.where(or_(HelpArticle.question.ilike(pattern, escape="\\"), HelpArticle.answer.ilike(pattern, escape="\\")))
    return list(db.scalars(query.order_by(HelpArticle.section, HelpArticle.sort_order, HelpArticle.id)))


@router.post("", response_model=ArticleOut, status_code=201)
def create_article(body: ArticleIn, user: HR, db: DB) -> HelpArticle:
    article = HelpArticle(**body.model_dump())
    db.add(article)
    db.commit()
    return article


@router.put("/{article_id}", response_model=ArticleOut)
def update_article(article_id: int, body: ArticleIn, user: HR, db: DB) -> HelpArticle:
    article = db.get(HelpArticle, article_id)
    if article is None:
        raise not_found("Help article")
    for field, value in body.model_dump().items():
        setattr(article, field, value)
    db.commit()
    return article


@router.delete("/{article_id}", status_code=204)
def delete_article(article_id: int, user: HR, db: DB) -> None:
    article = db.get(HelpArticle, article_id)
    if article is None:
        raise not_found("Help article")
    db.delete(article)
    db.commit()


@router.post("/{article_id}/feedback", response_model=ArticleOut)
def feedback(article_id: int, body: FeedbackIn, user: CurrentUser, db: DB) -> HelpArticle:
    """'Was this helpful?' – a simple counter so HR sees which answers need work."""
    article = db.get(HelpArticle, article_id)
    if article is None or not article.active:
        raise not_found("Help article")
    if body.helpful:
        article.helpful_yes += 1
    else:
        article.helpful_no += 1
    db.commit()
    return article
