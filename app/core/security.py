"""Password hashing and JWT issuing.

Uses `bcrypt` directly rather than `passlib`. passlib 1.7.4 (last released 2020)
reads `bcrypt.__about__.__version__`, an attribute removed in bcrypt 4.1+, which
produced a trapped-exception warning on every import. The two functions below are
all this project used passlib for.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"

# bcrypt hashes at most 72 bytes and silently ignores the rest.
BCRYPT_MAX_BYTES = 72


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject)}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def _encode(password: str) -> bytes:
    """UTF-8 encode, truncated to bcrypt's limit on a character boundary.

    Truncating raw bytes could split a multi-byte character; decoding back with
    errors="ignore" drops the partial one.
    """
    raw = password.encode("utf-8")
    if len(raw) <= BCRYPT_MAX_BYTES:
        return raw
    return raw[:BCRYPT_MAX_BYTES].decode("utf-8", errors="ignore").encode("utf-8")


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(plain_password), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed/legacy hash in the DB — treat as a failed login, not a 500.
        return False
