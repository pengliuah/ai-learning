from __future__ import annotations

import logging

from ..db import db_conn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 学习资料附件 (全模态转写): 上传的原始文件 + 转写出的 markdown 文本。
# 原始文件存 BYTEA; 转写后台异步进行, 前端轮询 transcript_status。
# ---------------------------------------------------------------------------


def create_attachment(user_id: str, filename: str, mime: str, data: bytes) -> dict:
    """Insert one attachment row (transcript pending) and return its row."""
    with db_conn() as conn:
        row = conn.execute(
            """INSERT INTO attachments (user_id, filename, mime, size_bytes, data)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id, filename, mime, size_bytes,
                         transcript, transcript_status, created_at""",
            (user_id, filename, mime, len(data), data),
        ).fetchone()
    return dict(row)


def get_attachment(user_id: str, attachment_id: str, *, with_data: bool = False) -> dict | None:
    """Return one attachment row for the owner (None otherwise / bad UUID)."""
    cols = "id, user_id, filename, mime, size_bytes, transcript, transcript_status, created_at"
    if with_data:
        cols += ", data"
    try:
        with db_conn() as conn:
            row = conn.execute(
                f"SELECT {cols} FROM attachments WHERE id = %s AND user_id = %s",
                (attachment_id, user_id),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        # 非法 UUID 等 → 统一按"不存在"处理, API 层转 404
        return None


def update_transcript(attachment_id: str, transcript: str, status: str) -> None:
    """Persist a transcription result/status (done / failed / running)."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE attachments SET transcript = %s, transcript_status = %s WHERE id = %s",
            (transcript, status, attachment_id),
        )


def delete_attachment(user_id: str, attachment_id: str) -> bool:
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM attachments WHERE id = %s AND user_id = %s",
            (attachment_id, user_id),
        )
        return cur.rowcount > 0


def get_attachments_transcripts(user_id: str, attachment_ids: list[str]) -> list[dict]:
    """Resolve attachment ids to ready transcripts, preserving input order.

    只返回 done 状态的转写; 未完成/不存在的附件静默跳过 (调用方据此判断
    是否需要等待)。Bad UUIDs are ignored, not raised.
    """
    out: list[dict] = []
    if not attachment_ids:
        return out
    for aid in attachment_ids:
        try:
            with db_conn() as conn:
                row = conn.execute(
                    """SELECT id, filename, transcript FROM attachments
                       WHERE id = %s AND user_id = %s AND transcript_status = 'done'""",
                    (aid, user_id),
                ).fetchone()
            if row:
                out.append(dict(row))
        except Exception:
            continue
    return out
