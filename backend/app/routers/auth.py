from datetime import timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, select

from .. import totp
from ..config import settings
from ..deps import DB, SESSION_COOKIE, CurrentUser
from ..errors import ApiError
from ..models import AuthSession, User, utcnow
from ..schemas import LoginIn, UserOut
from ..security import DUMMY_HASH, hash_token, login_throttle, new_session_token, verify_password
from ..services.security import use_recovery_code

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: DB) -> User:
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{body.email}"
    if login_throttle.is_blocked(key):
        raise ApiError(429, "too_many_attempts", "Too many failed sign-in attempts. Please wait 15 minutes.")

    user = db.scalar(select(User).where(User.email == body.email))
    valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or not user.is_active:
        login_throttle.fail(key)
        raise ApiError(401, "invalid_credentials", "The email address or password is not correct.")
    if user.totp_enabled and user.totp_secret:
        # Password was right; ask for the authenticator code without counting a failure.
        if not body.code:
            raise ApiError(401, "two_factor_required", "Please enter the code from your authenticator app.")
        ok = totp.verify(user.totp_secret, body.code) or use_recovery_code(user, body.code)
        if not ok:
            login_throttle.fail(key)
            raise ApiError(401, "two_factor_invalid", "The code is not correct.")
    login_throttle.reset(key)

    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    token = new_session_token()
    db.add(AuthSession(token_hash=hash_token(token), user_id=user.id, expires_at=now + timedelta(hours=settings.session_hours)))
    db.commit()

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
