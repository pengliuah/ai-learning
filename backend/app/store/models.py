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
# Model settings (per-user: LLM API key / model / base URL)
#
# Saved from the web UI ("模型设置"). Empty fields fall back to the ARK_*
# environment variables (and their built-in defaults), so env vars still
# seed fresh deployments.
# ---------------------------------------------------------------------------

def get_model_settings_row(user_id: str) -> dict:
    """Return the user's model settings row, creating defaults if missing.

    API Key 字段出库时解密（历史上是明文的行原样透传，下次保存即完成加密迁移）。
    """
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_model_settings WHERE user_id = %s", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO user_model_settings (user_id) VALUES (%s)", (user_id,)
            )
            row = conn.execute(
                "SELECT * FROM user_model_settings WHERE user_id = %s", (user_id,)
            ).fetchone()
    out = dict(row)
    out["api_key"] = decrypt_field(out.get("api_key") or "")
    out["embedding_api_key"] = decrypt_field(out.get("embedding_api_key") or "")
    return out


def update_model_settings(
    user_id: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    max_tokens: int | None = None,
    embedding_api_key: str | None = None,
    embedding_model: str | None = None,
    embedding_base_url: str | None = None,
) -> dict:
    """Update model settings fields (only non-None are set, values stripped)."""
    sets: list[str] = []
    params: list = []
    if api_key is not None:
        sets.append("api_key = %s")
        params.append(encrypt_field(api_key.strip()))
    if model is not None:
        sets.append("model = %s")
        params.append(model.strip())
    if base_url is not None:
        sets.append("base_url = %s")
        params.append(base_url.strip())
    if max_tokens is not None:
        sets.append("max_tokens = %s")
        params.append(max_tokens)
    if embedding_api_key is not None:
        sets.append("embedding_api_key = %s")
        params.append(encrypt_field(embedding_api_key.strip()))
    if embedding_model is not None:
        sets.append("embedding_model = %s")
        params.append(embedding_model.strip())
    if embedding_base_url is not None:
        sets.append("embedding_base_url = %s")
        params.append(embedding_base_url.strip())
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO user_model_settings (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (user_id,),
        )
        if sets:
            params.append(user_id)
            conn.execute(
                f"""UPDATE user_model_settings SET {', '.join(sets)}
                    WHERE user_id = %s""",
                params,
            )
    return get_model_settings_row(user_id)


def get_llm_config(user_id: str) -> tuple[str, str, str, int]:
    """The user's LLM config ``(api_key, model, base_url, max_tokens)``.

    Single source of truth is the user's ``user_model_settings`` DB row
    (configured on the web UI). No environment-variable fallback: an empty
    ``api_key`` means the user has not configured the model yet, and LLM
    calls will be refused until they do.
    """
    row = get_model_settings_row(user_id)
    return (
        row["api_key"],
        row["model"],
        row["base_url"],
        row.get("max_tokens") or 8192,
    )


def is_llm_configured_for_user(user_id: str) -> bool:
    """True when the user has saved a model API key in the database."""
    try:
        return bool(get_llm_config(user_id)[0])
    except Exception:
        return False


def get_embedding_config(user_id: str) -> tuple[str, str, str]:
    """The user's embedding config ``(api_key, model, base_url)``.

    模型名必填才视为已配置；embedding_api_key / embedding_base_url 留空时
    回退到大模型的对应值（同一服务商下常见）。未配置返回空三元组。
    """
    row = get_model_settings_row(user_id)
    model = (row.get("embedding_model") or "").strip()
    if not model:
        return ("", "", "")
    api_key = (row.get("embedding_api_key") or "").strip() or row["api_key"]
    base_url = (row.get("embedding_base_url") or "").strip() or row["base_url"]
    return (api_key, model, base_url)


def is_embedding_configured_for_user(user_id: str) -> bool:
    """True when the user has saved an embedding model in the database."""
    try:
        return bool(get_embedding_config(user_id)[1])
    except Exception:
        return False


