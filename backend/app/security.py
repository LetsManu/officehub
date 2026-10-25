"""Password hashing, session tokens and a small login throttle."""

import hashlib
import os
import secrets
import threading
import time

import bcrypt


# Lower rounds are only meant for the test suite.
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# Used to keep login timing similar for unknown email addresses.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LoginThrottle:
    """Blocks a key after too many failed logins within a time window (in-memory)."""

    def __init__(self, max_attempts: int = 10, window_seconds: int = 15 * 60):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        return [t for t in self._failures.get(key, []) if now - t < self.window]

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key, time.monotonic())) >= self.max_attempts

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._failures[key] = self._recent(key, now) + [now]

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_throttle = LoginThrottle()
# Every address together, per account: generous, so people elsewhere are not locked out by someone guessing.
account_throttle = LoginThrottle(max_attempts=50)
