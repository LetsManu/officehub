from fastapi import APIRouter

from ..deps import DB, CurrentUser
from ..errors import ApiError
from ..models import User
from ..schemas import PasswordChange, ProfileUpdate, UserOut
from ..security import hash_password, verify_password

router = APIRouter(prefix="/api/profile", tags=["profile"])

_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


@router.get("", response_model=UserOut)
def get_profile(user: CurrentUser) -> User:
    return user


@router.patch("", response_model=UserOut)
def update_profile(body: ProfileUpdate, user: CurrentUser, db: DB) -> User:
    # Only personal fields are accepted; role and email cannot be changed here.
    changes = body.model_dump(exclude_unset=True)
    if "birthday_day" in changes or "birthday_month" in changes:
        day, month = changes.pop("birthday_day", None), changes.pop("birthday_month", None)
        if (day is None) != (month is None) or (day and month and day > _DAYS_IN_MONTH[month - 1]):
            error = ApiError(422, "birthday_invalid", "Please choose a valid day and month.")
            error.field = "birthday_day"  # type: ignore[attr-defined]
            raise error
        user.birthday_day, user.birthday_month = day, month
    for field, value in changes.items():
        if value is None:
            continue
        if field == "pinned_tiles":
            value = ",".join(dict.fromkeys(value))
        setattr(user, field, value)
    db.commit()
    return user


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, user: CurrentUser, db: DB) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise ApiError(422, "wrong_password", "Your current password is not correct.")
    user.password_hash = hash_password(body.new_password)
    db.commit()
