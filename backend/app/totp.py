"""Time-based one-time passwords (RFC 6238) for authenticator apps, using only the standard library."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_code(secret: str, at: float | None = None) -> str:
    return _code(secret, int((at if at is not None else time.time()) // PERIOD))


def verify(secret: str, code: str, at: float | None = None, window: int = 1) -> bool:
    """Accepts the current code and one step before/after to allow for clock drift."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return False
    counter = int((at if at is not None else time.time()) // PERIOD)
    return any(hmac.compare_digest(_code(secret, counter + step), code) for step in range(-window, window + 1))


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account)}"
        f"?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}"
    )


def new_recovery_codes(count: int = 8) -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)) for _ in range(count)]
