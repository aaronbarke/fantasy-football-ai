import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from functools import cache
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.utils.limits import ai_quota_counter, client_ip

bearer_scheme = HTTPBearer(auto_error=False)

# bcrypt only reads the first 72 bytes of a password (bcrypt>=5 raises past it).
BCRYPT_MAX_BYTES = 72
# Marks a password_hash that no password can match: accounts that sign in with
# Google or the demo button.
UNUSABLE_PASSWORD_PREFIX = "!"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:BCRYPT_MAX_BYTES], bcrypt.gensalt()).decode()


@cache
def _dummy_hash() -> bytes:
    return bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt())


def verify_password(password: str, hashed: str | None) -> bool:
    """Constant-work check: an unknown email or a password-less account still
    pays for one bcrypt round, so response time doesn't reveal which emails
    are registered."""
    candidate = password.encode()[:BCRYPT_MAX_BYTES]
    if not hashed or not hashed.startswith("$2"):
        bcrypt.checkpw(candidate, _dummy_hash())
        return False
    try:
        return bcrypt.checkpw(candidate, hashed.encode())
    except ValueError:
        return False


def has_usable_password(user: User) -> bool:
    return not (user.password_hash or "").startswith(UNUSABLE_PASSWORD_PREFIX)


def session_version(user: User) -> str:
    """Fingerprint of the account's credential, stamped into every token.
    Replacing the password hash therefore signs out every existing session."""
    digest = hmac.new(
        get_settings().jwt_secret.encode(), (user.password_hash or "").encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest[:12]).decode()


def _create_token(
    user: User, token_type: str, expires_delta: timedelta, extra: dict[str, Any] | None
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        **(extra or {}),
        "sub": str(user.id),
        "type": token_type,
        "sv": session_version(user),
        "exp": now + expires_delta,
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user: User, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    return _create_token(
        user, "access", timedelta(minutes=settings.access_token_expire_minutes), extra
    )


def create_refresh_token(user: User, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    return _create_token(
        user, "refresh", timedelta(days=settings.refresh_token_expire_days), extra
    )


def decode_claims(token: str, expected_type: str = "access") -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    return payload


def decode_token(token: str, expected_type: str = "access") -> str:
    return decode_claims(token, expected_type)["sub"]


async def user_for_claims(db: AsyncSession, claims: dict[str, Any]) -> User:
    """The token's user, provided the session hasn't been revoked since."""
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if not hmac.compare_digest(str(claims.get("sv", "")), session_version(user)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired — sign in again")
    return user


DEMO_EMAIL = "demo@ffai.app"


def is_demo(user: User) -> bool:
    return user.email.lower() == DEMO_EMAIL


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    claims = decode_claims(credentials.credentials)
    user = await user_for_claims(db, claims)
    # Routes that need more than the user (the demo session id) read it here.
    request.state.token_claims = claims
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Admin-only endpoints: must match a configured admin email. With none
    configured, allowed in development but blocked in production."""
    settings = get_settings()
    admins = settings.admin_email_list
    if admins:
        if user.email.lower() not in admins:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    elif settings.is_production:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin endpoints are disabled")
    return user


async def block_demo(user: User = Depends(get_current_user)) -> User:
    """Disallow state-changing/costly actions on the shared demo account."""
    if is_demo(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This action is disabled on the shared demo account.",
        )
    return user


async def ai_quota(request: Request, user: User = Depends(get_current_user)) -> User:
    """Spend one of the caller's daily AI calls (routes that call Claude)."""
    settings = get_settings()
    if is_demo(user):
        limits = [
            (f"demo-ip:{client_ip(request)}", settings.ai_daily_limit_demo_per_ip),
            ("demo-total", settings.ai_daily_limit_demo_total),
        ]
    else:
        limits = [(f"user:{user.id}", settings.ai_daily_limit_per_user)]
    if not ai_quota_counter.take(limits):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You've hit today's AI limit — it resets at midnight UTC.",
        )
    return user
