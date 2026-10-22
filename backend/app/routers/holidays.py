"""Public holidays (built in for AT, DE, CH) and company holidays."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, StringConstraints

from ..deps import DB, HR, CurrentUser
from ..errors import ApiError, not_found
from ..holidays import DE_STATES
from ..models import CompanyHoliday
from ..services.audit import audit
from ..services.holidays import holiday_config, holidays_in
from ..services.settings import set_setting

router = APIRouter(prefix="/api/holidays", tags=["holidays"])


class HolidayOut(BaseModel):
    date: date
    name_de: str
    name_en: str
    company: bool
    id: int | None = None


class HolidayConfig(BaseModel):
    country: Literal["", "AT", "DE", "CH"]
    region: str
    company_holidays: list[HolidayOut]


class HolidayConfigIn(BaseModel):
    country: Literal["", "AT", "DE", "CH"]
    region: Annotated[str, StringConstraints(max_length=4)] = ""


class CompanyHolidayIn(BaseModel):
    day: date
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


@router.get("", response_model=list[HolidayOut])
def list_holidays(user: CurrentUser, db: DB, year: int = Query(..., ge=2000, le=2100)) -> list[HolidayOut]:
    ids = {h.day: h.id for h in db.query(CompanyHoliday).all()}
    return [
        HolidayOut(date=d, name_de=de, name_en=en, company=company, id=ids.get(d) if company else None)
        for d, de, en, company in holidays_in(db, date(year, 1, 1), date(year, 12, 31))
    ]


def _config(db) -> HolidayConfig:
    config = holiday_config(db)
    company = [
        HolidayOut(date=h.day, name_de=h.name, name_en=h.name, company=True, id=h.id)
        for h in db.query(CompanyHoliday).filter(CompanyHoliday.day >= date(date.today().year, 1, 1)).order_by(CompanyHoliday.day)
    ]
    return HolidayConfig(country=config["country"], region=config["region"], company_holidays=company)


@router.get("/config", response_model=HolidayConfig)
def get_config(user: HR, db: DB) -> HolidayConfig:
    return _config(db)


@router.put("/config", response_model=HolidayConfig)
def update_config(body: HolidayConfigIn, user: HR, db: DB) -> HolidayConfig:
    region = body.region.upper() if body.country == "DE" else ""
    if region and region not in DE_STATES:
        raise ApiError(422, "region_invalid", "Please choose a federal state.")
    set_setting(db, "holidays", {"country": body.country, "region": region})
    audit(db, user, "holidays_updated", f"{body.country or '-'} {region}".strip())
    db.commit()
    return _config(db)


@router.post("/company", response_model=HolidayConfig, status_code=201)
def add_company_holiday(body: CompanyHolidayIn, user: HR, db: DB) -> HolidayConfig:
    if db.query(CompanyHoliday).filter(CompanyHoliday.day == body.day).first():
        raise ApiError(409, "holiday_exists", "There is already a holiday on this day.")
    db.add(CompanyHoliday(day=body.day, name=body.name))
    audit(db, user, "holidays_updated", f"{body.day} {body.name}")
    db.commit()
    return _config(db)


@router.delete("/company/{holiday_id}", response_model=HolidayConfig)
def delete_company_holiday(holiday_id: int, user: HR, db: DB) -> HolidayConfig:
    row = db.get(CompanyHoliday, holiday_id)
    if row is None:
        raise not_found("Holiday")
    audit(db, user, "holidays_updated", f"removed {row.day} {row.name}")
    db.delete(row)
    db.commit()
    return _config(db)
