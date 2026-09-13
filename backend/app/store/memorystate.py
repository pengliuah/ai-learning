from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from ..config import settings
from ..crypto import decrypt_field, encrypt_field
from ..db import db_conn
from ..schemas import *  # noqa: F401,F403

logger = logging.getLogger(__name__)
_CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Memory settings (per-user master switch for long-term Mem0 memory)
# ---------------------------------------------------------------------------

def get_memory_settings_row(user_id: str) -> dict:
    """Return ``{"enabled": bool}``, creating a default (enabled=true) row if missing."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT enabled FROM user_memory_settings WHERE user_id = %s", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO user_memory_settings (user_id) VALUES (%s)", (user_id,)
            )
            row = conn.execute(
                "SELECT enabled FROM user_memory_settings WHERE user_id = %s", (user_id,)
            ).fetchone()
    return {"enabled": bool(row["enabled"])}


def update_memory_settings(user_id: str, enabled: bool | None = None) -> dict:
    """Update the memory master switch (only non-None fields)."""
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO user_memory_settings (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (user_id,),
        )
        if enabled is not None:
            conn.execute(
                "UPDATE user_memory_settings SET enabled = %s WHERE user_id = %s",
                (enabled, user_id),
            )
        row = conn.execute(
            "SELECT enabled FROM user_memory_settings WHERE user_id = %s", (user_id,)
        ).fetchone()
    return {"enabled": bool(row["enabled"])}


def is_memory_enabled(user_id: str) -> bool:
    """True when the user's long-term memory master switch is on (default true)."""
    try:
        return bool(get_memory_settings_row(user_id)["enabled"])
    except Exception:
        return True


def get_memory_profile(user_id: str) -> str:
    """学生画像摘要（召回时注入）；没有画像返回空串。"""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT profile FROM user_memory_profile WHERE user_id = %s", (user_id,)
        ).fetchone()
    return (row["profile"] or "").strip() if row else ""


def is_profile_edited_by_user(user_id: str) -> bool:
    """用户是否在记忆页手动修改过画像（修改后夜间整理不再覆盖）。"""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT edited_by_user FROM user_memory_profile WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    return bool(row and row["edited_by_user"])


def save_memory_profile(user_id: str, profile: str, edited_by_user: bool = False) -> None:
    """写入/更新学生画像。

    edited_by_user 标记这条画像是否出自用户之手（用户改过就不再被夜间
    整理覆盖）；自动刷新写入 False 时不会清除已有的用户修改标记。
    """
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO user_memory_profile (user_id, profile, edited_by_user)
               VALUES (%s, %s, %s)
               ON CONFLICT (user_id)
               DO UPDATE SET profile = EXCLUDED.profile,
                             edited_by_user = user_memory_profile.edited_by_user OR EXCLUDED.edited_by_user,
                             updated_at = now()""",
            (user_id, (profile or "").strip(), edited_by_user),
        )


def stale_housekeeping_users(limit: int = 50) -> list[str]:
    """最久没被夜间整理任务处理过的用户（含从未处理过的）。

    只挑「记忆开着 + 真的用过记忆（有 memory 用量记录）」的用户，
    避免每轮为从不使用记忆的账号构建 mem0 实例。
    """
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT u.id::text AS id
               FROM users u
               LEFT JOIN memory_housekeeping h ON h.user_id = u.id
               WHERE (h.user_id IS NULL OR h.last_run_at < now() - make_interval(hours => %s))
                 AND COALESCE((SELECT s.enabled FROM user_memory_settings s
                               WHERE s.user_id = u.id), TRUE)
                 AND EXISTS (SELECT 1 FROM token_usage t
                             WHERE t.user_id = u.id AND t.gen_type = 'memory')
               ORDER BY h.last_run_at NULLS FIRST
               LIMIT %s""",
            (settings.memory_housekeeping_interval_hours, limit),
        ).fetchall()
    return [r["id"] for r in rows]


def touch_housekeeping(user_id: str) -> None:
    """推进该用户的整理水位（无论本轮成败都调用，避免坏用户被热循环重试）。"""
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO memory_housekeeping (user_id) VALUES (%s)
               ON CONFLICT (user_id)
               DO UPDATE SET last_run_at = now(), updated_at = now()""",
            (user_id,),
        )


def memory_housekeeping_status(user_id: str) -> dict:
    """整理状态一览：画像 + 水位 + 循环是否处理过该用户。"""
    with db_conn() as conn:
        row = conn.execute(
            """SELECT p.profile, p.updated_at AS profile_updated_at,
                      p.edited_by_user,
                      h.last_run_at, h.user_id IS NOT NULL AS touched
               FROM users u
               LEFT JOIN user_memory_profile p ON p.user_id = u.id
               LEFT JOIN memory_housekeeping h ON h.user_id = u.id
               WHERE u.id = %s""",
            (user_id,),
        ).fetchone()
    return {
        "profile": (row["profile"] or "").strip() if row else "",
        "profileUpdatedAt": row["profile_updated_at"] if row else None,
        "profileEditedByUser": bool(row["edited_by_user"]) if row else False,
        "lastRunAt": row["last_run_at"] if row else None,
        "touched": bool(row["touched"]) if row else False,
    }


