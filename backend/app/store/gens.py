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

# Gen settings (per-user, per-type: plan / content / quiz strategy prompts)
# ---------------------------------------------------------------------------

_GEN_TYPES = ("plan", "content", "quiz", "grade")


def get_gen_settings_row(user_id: str) -> dict:
    """Return {"plan": str, "content": str, "quiz": str} for the user.

    Ensures all three rows exist, creating missing ones with empty defaults.
    """
    with db_conn() as conn:
        for gt in _GEN_TYPES:
            conn.execute(
                """INSERT INTO user_gen_settings (user_id, gen_type)
                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                (user_id, gt),
            )
        rows = conn.execute(
            """SELECT gen_type, strategy FROM user_gen_settings
               WHERE user_id = %s ORDER BY gen_type""",
            (user_id,),
        ).fetchall()
    return {r["gen_type"]: r["strategy"] for r in rows}


def update_gen_settings(
    user_id: str,
    plan: str | None = None,
    content: str | None = None,
    quiz: str | None = None,
    grade: str | None = None,
) -> dict:
    """Update specific gen-strategy fields (only non-None are set)."""
    updates = {"plan": plan, "content": content, "quiz": quiz, "grade": grade}
    with db_conn() as conn:
        for gt, val in updates.items():
            if val is not None:
                conn.execute(
                    """INSERT INTO user_gen_settings (user_id, gen_type, strategy)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (user_id, gen_type)
                       DO UPDATE SET strategy = EXCLUDED.strategy""",
                    (user_id, gt, val),
                )
        rows = conn.execute(
            """SELECT gen_type, strategy FROM user_gen_settings
               WHERE user_id = %s ORDER BY gen_type""",
            (user_id,),
        ).fetchall()
    return {r["gen_type"]: r["strategy"] for r in rows}


