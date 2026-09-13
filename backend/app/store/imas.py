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
# IMA settings (per-user table: credentials + skill prompt)
# ---------------------------------------------------------------------------

def get_ima_settings_row(user_id: str) -> dict:
    """Return the user's ima settings row, creating defaults if missing.

    ima_api_key 出库时解密（历史明文原样透传，下次保存即完成加密迁移）。
    """
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_ima_settings WHERE user_id = %s", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO user_ima_settings (user_id) VALUES (%s)", (user_id,)
            )
            row = conn.execute(
                "SELECT * FROM user_ima_settings WHERE user_id = %s", (user_id,)
            ).fetchone()
    out = dict(row)
    out["ima_api_key"] = decrypt_field(out.get("ima_api_key") or "")
    return out


def update_ima_settings(
    user_id: str,
    client_id: str | None = None,
    api_key: str | None = None,
    skill_prompt: str | None = None,
) -> dict:
    """Update IMA credential / skill-prompt fields (only non-None are set)."""
    sets: list[str] = []
    params: list = []
    if client_id is not None:
        sets.append("ima_client_id = %s")
        params.append(client_id)
    if api_key is not None:
        sets.append("ima_api_key = %s")
        params.append(encrypt_field(api_key))
    if skill_prompt is not None:
        sets.append("ima_skill_prompt = %s")
        params.append(skill_prompt)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO user_ima_settings (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (user_id,),
        )
        if sets:
            params.append(user_id)
            conn.execute(
                f"""UPDATE user_ima_settings SET {', '.join(sets)}
                    WHERE user_id = %s""",
                params,
            )
    return get_ima_settings_row(user_id)


# ---------------------------------------------------------------------------
