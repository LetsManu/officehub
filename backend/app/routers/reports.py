"""Ready-made reports for managers and HR, as tables or CSV."""

import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from ..deps import DB, Approver
from ..errors import ApiError
from ..models import PENDING_STATUSES, Request, User, utcnow
from .admin import _csv_cell

router = APIRouter(prefix="/api/reports", tags=["reports"])

ReportName = Literal["absences", "expenses", "overdue", "equipment"]


class Report(BaseModel):
    name: str
    columns: list[str]
    rows: list[list[str | int | None]]


def _month_range(month: str | None) -> tuple[date, date]:
    try:
        start = datetime.strptime(month, "%Y-%m").date() if month else date.today().replace(day=1)
    except ValueError:
        raise ApiError(422, "invalid_filter", "Please choose a valid month.") from None
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start, end


def _absences(db, month: str | None) -> Report:
    start, end = _month_range(month)
    rows = db.scalars(
        select(Request)
        .join(User, Request.requester_id == User.id)
        .where(
            Request.type.in_(("vacation", "home_office")),
            Request.status == "approved",
            Request.start_date <= end,
            Request.end_date >= start,
        )
        .order_by(User.department, User.last_name, Request.start_date)
    )
    return Report(
        name="absences",
        columns=["person", "department", "type", "start_date", "end_date", "working_days"],
        rows=[
            [r.requester.full_name, r.requester.department, r.type, str(r.start_date), str(r.end_date), r.working_days]
            for r in rows
        ],
    )


def _expenses(db, date_from: date | None, date_to: date | None) -> Report:
    query = select(Request).where(Request.type == "expense", Request.status == "approved")
    if date_from:
        query = query.where(Request.start_date >= date_from)
    if date_to:
        query = query.where(Request.start_date <= date_to)
    totals: dict[tuple[str, str], tuple[int, int]] = {}
    for r in db.scalars(query):
        key = (r.category or "other", r.currency or "EUR")
        count, cents = totals.get(key, (0, 0))
        totals[key] = (count + 1, cents + (r.amount_cents or 0))
    return Report(
        name="expenses",
        columns=["category", "currency", "count", "total"],
        rows=[
            [category, currency, count, f"{Decimal(cents) / 100:.2f}"]
            for (category, currency), (count, cents) in sorted(totals.items())
        ],
    )


def _overdue(db, days: int) -> Report:
    limit = utcnow() - timedelta(days=days)
    rows = db.scalars(
        select(Request)
        .where(Request.status.in_(PENDING_STATUSES), Request.submitted_at <= limit)
        .order_by(Request.submitted_at)
    )
    today = utcnow().date()
    return Report(
        name="overdue",
        columns=["id", "title", "type", "person", "status", "submitted", "days_waiting"],
        rows=[
            [r.id, r.title, r.type, r.requester.full_name, r.status, str(r.submitted_at.date()), (today - r.submitted_at.date()).days]
            for r in rows
        ],
    )


def _equipment(db, date_from: date | None, date_to: date | None) -> Report:
    query = select(Request).where(Request.type == "equipment", Request.status == "approved")
    if date_from:
        query = query.where(Request.decided_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.where(Request.decided_at < datetime.combine(date_to + timedelta(days=1), time.min))
    rows = db.scalars(query.order_by(Request.decided_at.desc()))
    return Report(
        name="equipment",
        columns=["person", "department", "item", "category", "approved_on"],
        rows=[
            [r.requester.full_name, r.requester.department, r.item, r.category, str(r.decided_at.date()) if r.decided_at else ""]
            for r in rows
        ],
    )


@router.get("/{name}")
def report(
    name: ReportName,
    user: Approver,
    db: DB,
    month: str | None = Query(None, max_length=7),
    date_from: date | None = None,
    date_to: date | None = None,
    days: int = Query(7, ge=1, le=365),
    format: Literal["json", "csv"] = "json",
):
    if name == "absences":
        result = _absences(db, month)
    elif name == "expenses":
        result = _expenses(db, date_from, date_to)
    elif name == "overdue":
        result = _overdue(db, days)
    else:
        result = _equipment(db, date_from, date_to)
    if format == "json":
        return result
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(result.columns)
    for row in result.rows:
        writer.writerow([_csv_cell(v) for v in row])
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="report-{name}-{utcnow():%Y-%m-%d}.csv"'},
    )
