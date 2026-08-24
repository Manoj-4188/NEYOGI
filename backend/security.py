"""Authentication and role gating for the officer console.

The public dashboard is unauthenticated by design -- price and supply
transparency is the point of the system. The officer console is not: it exposes
pipeline internals, the confusion matrix and the manual parcel-verification
toggle, which writes to ground truth. Those sit behind a bearer token carrying
an ``officer`` or ``admin`` role.

Run ``python -m backend.security hash <password>`` to generate a bcrypt hash
for the ``OFFICER_ACCOUNTS`` environment variable.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status as http_status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend import db
from backend.config import settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

ROLE_HIERARCHY = {"officer": 1, "admin": 2}


@dataclass(frozen=True)
class Principal:
    username: str
    role: str

    def has_role(self, required: str) -> bool:
        return ROLE_HIERARCHY.get(self.role, 0) >= ROLE_HIERARCHY.get(required, 99)


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    import bcrypt

    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def create_access_token(username: str, role: str) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    ttl = timedelta(minutes=settings.jwt_ttl_minutes)
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "iss": "neyogi",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def decode_token(token: str) -> Principal:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="neyogi",
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Session expired; sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    username = payload.get("sub")
    role = payload.get("role")
    if not username or role not in ROLE_HIERARCHY:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a usable subject or role.",
        )
    return Principal(username=str(username), role=str(role))


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


async def authenticate(username: str, password: str) -> Principal | None:
    """Verify credentials against the ``users`` table.

    Always runs a bcrypt comparison, even for an unknown username, so response
    timing does not reveal which accounts exist.
    """
    row = await db.fetch_one(
        "SELECT username, password_hash, role, is_active FROM users WHERE username = %s",
        (username,),
    )
    if row is None:
        # Dummy verification against a real hash to equalise timing.
        verify_password(password, hash_password(secrets.token_hex(16)))
        return None

    db_username, password_hash, role, is_active = row
    if not verify_password(password, password_hash):
        return None
    if not is_active:
        logger.warning("Sign-in attempt on deactivated account %r", username)
        return None

    await db.execute(
        "UPDATE users SET last_login_at = now() WHERE username = %s", (db_username,)
    )
    return Principal(username=db_username, role=role)


async def seed_officer_accounts() -> int:
    """Seed accounts from ``OFFICER_ACCOUNTS`` if they do not already exist.

    Format: ``username:bcrypt_hash`` pairs, comma separated. Existing rows are
    left untouched, so this never overwrites a rotated password.
    """
    raw = settings.officer_accounts.strip()
    if not raw:
        return 0

    seeded = 0
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        username, _, password_hash = entry.partition(":")
        username, password_hash = username.strip(), password_hash.strip()
        if not username or not password_hash.startswith("$2"):
            logger.warning(
                "Skipping OFFICER_ACCOUNTS entry for %r: value must be a bcrypt hash, "
                "not a plaintext password.",
                username,
            )
            continue
        changed = await db.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (%s, %s, 'officer')
            ON CONFLICT (username) DO NOTHING
            """,
            (username, password_hash),
        )
        seeded += max(changed, 0)

    if seeded:
        logger.info("Seeded %d officer account(s) from OFFICER_ACCOUNTS", seeded)
    return seeded


# --------------------------------------------------------------------------
# FastAPI dependencies
# --------------------------------------------------------------------------


async def current_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="This endpoint requires an officer sign-in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(credentials.credentials)


def require_role(required: str):
    """Dependency factory gating an endpoint on a minimum role."""

    async def _dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if not principal.has_role(required):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires the {required} role.",
            )
        return principal

    return _dependency


require_officer = require_role("officer")
require_admin = require_role("admin")


def main() -> int:  # pragma: no cover - operator utility
    """``python -m backend.security hash <password>``"""
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "hash":
        print(hash_password(sys.argv[2]))
        return 0
    print("usage: python -m backend.security hash <password>", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
