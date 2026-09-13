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
# ---------------------------------------------------------------------------
# Token usage (per-user LLM 用量统计)
#
# 每次 LLM 调用成功后由 agent 层写入一行, 供「模型设置」页展示
# 今日 / 本月 / 累计的 token 消耗与请求次数。时间聚合按东八区。
# ---------------------------------------------------------------------------

_CST = timezone(timedelta(hours=8))


def record_token_usage(
    user_id: str,
    gen_type: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    model: str | None = None,
    kind: str = "llm",
) -> None:
    """Insert one usage row.

    ``kind`` distinguishes the billed model type: ``"llm"`` (大模型, 默认)
    or ``"embedding"`` (向量模型). ``model`` defaults to the user's configured
    LLM or embedding model respectively.
    """
    if model is None:
        try:
            if kind == "embedding":
                model = get_embedding_config(user_id)[1] or ""
            else:
                model = get_llm_config(user_id)[1] or ""
        except Exception:
            model = ""
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO token_usage
                   (user_id, gen_type, model, input_tokens, output_tokens, total_tokens, kind)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (user_id, gen_type, model, input_tokens, output_tokens, total_tokens, kind),
        )


def get_usage_summary(user_id: str) -> dict:
    """Aggregated token usage for today / this month / all time (CST)."""
    now = datetime.now(_CST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def _sum(since: datetime) -> dict:
        """One time bucket, split by model kind (llm / embedding)."""
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT kind,
                          COUNT(*) AS requests,
                          COALESCE(SUM(input_tokens), 0) AS input_tokens,
                          COALESCE(SUM(output_tokens), 0) AS output_tokens,
                          COALESCE(SUM(total_tokens), 0) AS total_tokens
                   FROM token_usage
                   WHERE user_id = %s AND created_at >= %s
                   GROUP BY kind""",
                (user_id, since),
            ).fetchall()
        by_kind = {r["kind"]: r for r in rows}

        def _stat(kind: str) -> dict:
            row = by_kind.get(kind)
            return {
                "requests": int(row["requests"]) if row else 0,
                "inputTokens": int(row["input_tokens"]) if row else 0,
                "outputTokens": int(row["output_tokens"]) if row else 0,
                "totalTokens": int(row["total_tokens"]) if row else 0,
            }

        return {"llm": _stat("llm"), "embedding": _stat("embedding")}

    return {
        "today": _sum(today_start),
        "month": _sum(month_start),
        "allTime": _sum(epoch),
    }


