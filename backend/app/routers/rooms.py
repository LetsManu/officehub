"""Bookable places (meeting rooms, desks, parking spaces) and bookings."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, forbidden, not_found
from ..models import Room, RoomBooking
from ..services import notifications

router = APIRouter(prefix="/api/rooms", tags=["rooms"])

# Bookable hours (local time) and step in minutes
DAY_START, DAY_END, STEP = "07:00", "20:00", 15

Time = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


Kind = Literal["room", "desk", "parking"]


class RoomIn(BaseModel):
    kind: Kind = "room"
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    seats: Annotated[int, Field(ge=1, le=500)] = 4
    equipment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    active: bool = True


class RoomOut(BaseModel):
    id: int
    kind: str
    name: str
    seats: int
    equipment: str
    active: bool


class BookingIn(BaseModel):
    room_id: int
    day: date
    start_time: Time
    end_time: Time
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class BookingOut(BaseModel):
    id: int
    room_id: int
    room_name: str
    room_kind: str
    day: date
    start_time: str
    end_time: str
    title: str
    person_id: int
    person_name: str
    can_cancel: bool


def _out(booking: RoomBooking, viewer_id: int, is_admin: bool) -> BookingOut:
    return BookingOut(
        id=booking.id,
        room_id=booking.room_id,
        room_name=booking.room.name,
        room_kind=booking.room.kind,
        day=booking.day,
        start_time=booking.start_time,
        end_time=booking.end_time,
        title=booking.title,
        person_id=booking.user_id,
        person_name=booking.user.full_name,
        can_cancel=booking.user_id == viewer_id or is_admin,
    )


def _field_error(field: str, code: str, message: str) -> ApiError:
    error = ApiError(422, code, message)
    error.field = field  # type: ignore[attr-defined]
    return error


@router.get("", response_model=list[RoomOut])
def list_rooms(user: CurrentUser, db: DB, include_inactive: bool = False, kind: Kind | None = None) -> list[Room]:
    query = select(Room)
    if kind:
        query = query.where(Room.kind == kind)
    if not (include_inactive and user.is_admin):
        query = query.where(Room.active.is_(True))
    return list(db.scalars(query.order_by(Room.kind, Room.name)))


@router.post("", response_model=RoomOut, status_code=201)
def create_room(body: RoomIn, user: Admin, db: DB) -> Room:
    room = Room(**body.model_dump())
    db.add(room)
    db.commit()
    return room


@router.patch("/{room_id}", response_model=RoomOut)
def update_room(room_id: int, body: RoomIn, user: Admin, db: DB) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise not_found("Room")
    for field, value in body.model_dump().items():
        setattr(room, field, value)
    db.commit()
    return room


@router.get("/bookings", response_model=list[BookingOut])
def bookings_for_day(user: CurrentUser, db: DB, day: date = Query(...)) -> list[BookingOut]:
    rows = db.scalars(select(RoomBooking).where(RoomBooking.day == day).order_by(RoomBooking.start_time))
    return [_out(b, user.id, user.is_admin) for b in rows]


@router.get("/bookings/mine", response_model=list[BookingOut])
def my_bookings(user: CurrentUser, db: DB) -> list[BookingOut]:
    rows = db.scalars(
        select(RoomBooking)
        .where(RoomBooking.user_id == user.id, RoomBooking.day >= date.today())
        .order_by(RoomBooking.day, RoomBooking.start_time)
        .limit(50)
    )
    return [_out(b, user.id, user.is_admin) for b in rows]


@router.post("/bookings", response_model=BookingOut, status_code=201)
def book(body: BookingIn, user: CurrentUser, db: DB) -> BookingOut:
    room = db.get(Room, body.room_id)
    if room is None or not room.active:
        raise _field_error("room_id", "room_invalid", "Please choose a room.")
    if body.day < date.today():
        raise _field_error("day", "day_past", "Please choose today or a later day.")
    if body.end_time <= body.start_time:
        raise _field_error("end_time", "end_before_start_time", "The end time must be after the start time.")
    if body.start_time < DAY_START or body.end_time > DAY_END:
        raise _field_error("start_time", "outside_hours", f"Rooms can be booked between {DAY_START} and {DAY_END}.")
    for value in (body.start_time, body.end_time):
        if int(value[3:]) % STEP:
            raise _field_error("start_time", "time_step", "Please use quarter hours (e.g. 09:15).")
    # Same-day "HH:MM" strings compare correctly as text.
    clash = db.scalar(
        select(RoomBooking).where(
            RoomBooking.room_id == room.id,
            RoomBooking.day == body.day,
            RoomBooking.start_time < body.end_time,
            RoomBooking.end_time > body.start_time,
        )
    )
    if clash is None and room.kind != "room":
        # One desk (or parking space) per person at a time is enough.
        clash_own = db.scalar(
            select(RoomBooking)
            .join(Room, Room.id == RoomBooking.room_id)
            .where(
                Room.kind == room.kind,
                RoomBooking.user_id == user.id,
                RoomBooking.day == body.day,
                RoomBooking.start_time < body.end_time,
                RoomBooking.end_time > body.start_time,
            )
        )
        if clash_own is not None:
            raise _field_error(
                "room_id", "already_booked_kind", f"You already booked {clash_own.room.name} for this time."
            )
    if clash is not None:
        raise _field_error(
            "start_time",
            "room_taken",
            f"The room is already booked from {clash.start_time} to {clash.end_time}.",
        )
    booking = RoomBooking(user_id=user.id, **body.model_dump())
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return _out(booking, user.id, user.is_admin)


@router.delete("/bookings/{booking_id}", status_code=204)
def cancel_booking(booking_id: int, user: CurrentUser, db: DB) -> None:
    booking = db.get(RoomBooking, booking_id)
    if booking is None:
        raise not_found("Booking")
    if booking.user_id != user.id and not user.is_admin:
        raise forbidden("Only the person who booked the room can cancel it.")
    notifications.notify_many(
        db,
        [booking.user_id],
        user,
        "booking_cancelled",
        {"name": user.full_name, "room": booking.room.name, "title": booking.title, "day": booking.day.isoformat(),
         "time": booking.start_time},
        "/rooms",
    )
    db.delete(booking)
    db.commit()
