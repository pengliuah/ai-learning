"""Password hashing, token issuing/rotation, and FastAPI auth dependencies.

Token model (双 token):
  - Access token: stateless JWT (HS256), short-lived, sent as
    ``Authorization: Bearer <token>`` on every request.
  - Refresh token: opaque ``secrets.token_urlsafe`` string; only its SHA-256
    hash is stored in ``refresh_tokens``. Rotated on every use (the presented
    token is revoked and a fresh one issued) so a stolen, already-used token
    cannot be replayed. Logout revokes it explicitly.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import store
from .config import settings

logger = logging.getLogger(__name__)

_jwt_alg = "HS256"

# Bearer extraction: auto_error=False so we can raise a uniform 401.
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Access token (JWT)
# ---------------------------------------------------------------------------

def create_access_token(user: dict[str, Any]) -> str:
    payload = {
        "sub": str(user["id"]),
        "role": user["role"],
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_jwt_alg)


# ---------------------------------------------------------------------------
# Refresh tokens (opaque, hashed at rest, rotated on use)
# ---------------------------------------------------------------------------

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_refresh_token(user_id: str) -> str:
    raw = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    store.create_refresh_token_row(user_id=user_id, token_hash=_hash_token(raw), expires_at=expires_at)
    return raw


def revoke_refresh_token(raw: str) -> None:
    store.revoke_refresh_token_row(_hash_token(raw))


def rotate_refresh_token(raw: str) -> tuple[dict[str, Any], str, str]:
    """Validate a refresh token, revoke it, and issue a fresh token pair.

    Returns ``(user, access_token, refresh_token)``. Raises 401 when the token
    is unknown/expired/revoked. If a *revoked* token is presented again that
    indicates replay of a (possibly stolen) token -- revoke every refresh
    token of the owning user as damage control.
    """
    row = store.get_refresh_token_row(_hash_token(raw))
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的 refresh token")
    if row["revoked"]:
        logger.warning("已吊销的 refresh token 被再次使用（疑似泄露），吊销该用户全部会话")
        store.revoke_all_refresh_tokens(str(row["user_id"]))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token 已失效")
    if row["expires_at"] <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token 已过期")

    user = store.get_user(str(row["user_id"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    store.revoke_refresh_token_row(_hash_token(raw))
    return user, create_access_token(user), create_refresh_token(str(user["id"]))


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[_jwt_alg])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的登录凭证")
    user = store.get_user(str(payload.get("sub")))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


AuthRole = Literal["admin", "user"]
