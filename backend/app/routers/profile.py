from fastapi import APIRouter

from ..deps import DB, CurrentUser
from ..errors import ApiError
from ..models import User
from ..schemas import PasswordChange, ProfileUpdate, UserOut
from ..security import hash_password, verify_password

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=UserOut)
def get_profile(user: CurrentUser) -> User:
    return user


@router.patch("", response_model=UserOut)
def update_profile(body: ProfileUpdate, user: CurrentUser, db: DB) -> User:
    # Only personal fields are accepted; role and email cannot be changed here.
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    return user


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, user: CurrentUser, db: DB) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise ApiError(422, "wrong_password", "Your current password is not correct.")
    user.password_hash = hash_password(body.new_password)
    db.commit()
