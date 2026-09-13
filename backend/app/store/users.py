from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from psycopg import errors as psycopg_errors
from psycopg.types.json import Jsonb

from ..config import settings
from ..crypto import decrypt_field, encrypt_field
from ..db import db_conn
from ..schemas import *  # noqa: F401,F403

logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Users (account system) — used by auth.py and the admin routes
# ---------------------------------------------------------------------------

def _user_public(row) -> dict:
    """Public shape of a users row (never includes the password hash)."""
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "createdAt": row["created_at"],
    }


def create_user(
    username: str, password_hash: str, role: str = "user", email: str | None = None
) -> dict:
    """Create a user and return its public dict. Raises ValueError on
    duplicate username/email."""
    with db_conn() as conn:
        try:
            row = conn.execute(
                """INSERT INTO users (username, password_hash, role, email)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id, username, email, role, created_at""",
                (username, password_hash, role, email),
            ).fetchone()
        except psycopg_errors.UniqueViolation as exc:
            raise ValueError("用户名或邮箱已存在") from exc
    logger.info("create_user: %s role=%s", username, role)
    return _user_public(row)


def get_user(user_id: str) -> dict | None:
    """Full user row (including password_hash) by id, or None."""
    with db_conn() as conn:
        row = conn.execute(
            """SELECT id, username, email, password_hash, role,
                      wechat_unionid, wechat_openid, created_at, updated_at
               FROM users WHERE id = %s""",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    """Full user row (including password_hash) by username, or None."""
    with db_conn() as conn:
        row = conn.execute(
            """SELECT id, username, email, password_hash, role,
                      wechat_unionid, wechat_openid, created_at, updated_at
               FROM users WHERE username = %s""",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    """All users (public shape), newest first."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT id, username, email, role, created_at
               FROM users ORDER BY created_at DESC"""
        ).fetchall()
    return [_user_public(r) for r in rows]


def delete_user(user_id: str) -> bool:
    with db_conn() as conn:
        result = conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        deleted = result.rowcount > 0
    logger.info("delete_user: user=%s deleted=%s", user_id, deleted)
    return deleted


def update_user_password(user_id: str, password_hash: str) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, user_id),
        )
    logger.info("update_user_password: user=%s", user_id)


# ---------------------------------------------------------------------------
# Refresh tokens (opaque, only SHA-256 hashes are stored)
# ---------------------------------------------------------------------------

def create_refresh_token_row(user_id: str, token_hash: str, expires_at) -> None:
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
               VALUES (%s, %s, %s)""",
            (user_id, token_hash, expires_at),
        )


def get_refresh_token_row(token_hash: str) -> dict | None:
    with db_conn() as conn:
        row = conn.execute(
            """SELECT id, user_id, token_hash, expires_at, revoked
               FROM refresh_tokens WHERE token_hash = %s""",
            (token_hash,),
        ).fetchone()
    return dict(row) if row else None


def revoke_refresh_token_row(token_hash: str) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE refresh_tokens SET revoked = true WHERE token_hash = %s",
            (token_hash,),
        )


def revoke_all_refresh_tokens(user_id: str) -> None:
    """Revoke every refresh token of a user (logout-everywhere / leak
    response / password change)."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE refresh_tokens SET revoked = true WHERE user_id = %s",
            (user_id,),
        )
    logger.info("revoke_all_refresh_tokens: user=%s", user_id)


def delete_expired_refresh_tokens() -> None:
    """Best-effort housekeeping: remove expired/revoked rows."""
    with db_conn() as conn:
        conn.execute(
            """DELETE FROM refresh_tokens
               WHERE expires_at < now() OR revoked = true"""
        )


