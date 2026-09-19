from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from ..db import db_conn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 邀请码（邀请制注册）: 管理员生成, 新人凭码在 /register 自助注册。
# 核销走原子 UPDATE (used_count < max_uses), 并发下不会超发。
# ---------------------------------------------------------------------------

# 去掉 0/O/1/I/L 等易混字符的 8 位码
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

_CST = timezone(timedelta(hours=8))

_COLS = """id, code, created_by, max_uses, used_count, expires_at, note,
           disabled, created_at"""


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def create_invite(
    created_by: str, max_uses: int = 1, expires_days: int | None = None, note: str = ""
) -> dict:
    """Mint one invite code. ``expires_days=None`` means never expires."""
    code = _generate_code()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=expires_days) if expires_days else None
    )
    with db_conn() as conn:
        row = conn.execute(
            f"""INSERT INTO invite_codes (code, created_by, max_uses, expires_at, note)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {_COLS}""",
            (code, created_by, max_uses, expires_at, note.strip()),
        ).fetchone()
    logger.info("invite: created code=%s... max_uses=%d expires_days=%s by=%s",
                code[:3], max_uses, expires_days, created_by)
    return dict(row)


def list_invites(limit: int = 200) -> list[dict]:
    """All invite codes, newest first (admin-only view)."""
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM invite_codes ORDER BY created_at DESC, id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def disable_invite(invite_id: str) -> bool:
    with db_conn() as conn:
        cur = conn.execute(
            "UPDATE invite_codes SET disabled = true WHERE id = %s AND disabled = false",
            (invite_id,),
        )
        return cur.rowcount > 0


def consume_invite(code: str) -> dict | None:
    """Atomically consume one use of ``code``; None when invalid/exhausted.

    核销条件在 WHERE 里一次判完（未禁用、未过期、未用尽），自增与判断是
    同一条语句，并发注册不会超发。返回 ``{"id", "created_by"}``。
    """
    if not code:
        return None
    with db_conn() as conn:
        row = conn.execute(
            """UPDATE invite_codes SET used_count = used_count + 1
               WHERE code = %s AND disabled = false
                 AND (expires_at IS NULL OR expires_at > now())
                 AND used_count < max_uses
               RETURNING id, created_by""",
            (code.strip().upper(),),
        ).fetchone()
    return dict(row) if row else None


def rollback_invite(invite_id: str) -> None:
    """核销回滚: 注册建号失败时把 used_count 减回来（不低于 0）。"""
    with db_conn() as conn:
        conn.execute(
            "UPDATE invite_codes SET used_count = GREATEST(used_count - 1, 0) WHERE id = %s",
            (invite_id,),
        )


def is_invite_valid(code: str) -> bool:
    """Check without consuming（测试/前端预检用）。"""
    with db_conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM invite_codes
               WHERE code = %s AND disabled = false
                 AND (expires_at IS NULL OR expires_at > now())
                 AND used_count < max_uses""",
            (code.strip().upper(),),
        ).fetchone()
    return row is not None
