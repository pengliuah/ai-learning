from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from ..config import settings
from ..db import db_conn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 学习资料附件 (全模态转写): 上传的原始文件 + 转写出的 markdown 文本。
#
# 原始文件存文件系统 (settings.attachments_dir, 部署时挂 docker 卷, 随目录单独
# 备份), 数据库只存元数据 + 相对路径 path —— 大二进制进库会把 pg_dump 备份
# 拖爆, 这是常规的"DB 存引用、FS 存内容"分工。转写在后台异步进行, 前端轮询
# transcript_status。
# ---------------------------------------------------------------------------


def _storage_root() -> Path:
    root = Path(settings.attachments_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


# 列表/详情共用的元数据列 (不含 path/文件内容, 不外泄也不拖数据)
_META_COLS = (
    "id, user_id, filename, mime, size_bytes, transcript, transcript_status, created_at"
)


def _write_file(path_rel: str, data: bytes) -> None:
    dest = _storage_root() / path_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _read_file(path_rel: str) -> bytes | None:
    dest = _storage_root() / path_rel
    try:
        return dest.read_bytes()
    except OSError:
        # 文件缺失 (备份只恢复了库没恢复目录等) 按"内容不可用"处理
        logger.warning("attachments: file missing on disk: %s", path_rel)
        return None


def _unlink(path_rel: str) -> None:
    dest = _storage_root() / path_rel
    try:
        dest.unlink()
    except OSError:
        pass
    # 顺路清理空的用户目录
    try:
        dest.parent.rmdir()
    except OSError:
        pass


def create_attachment(user_id: str, filename: str, mime: str, data: bytes) -> dict:
    """Store one upload, or return the existing row for identical content.

    同文件去重: 先按 (user_id, sha256) 查一把, 该用户已传过同内容文件就
    **直接返回老记录**（不写盘、不建新行, 返回值带 reused=True）——多模态
    模型只付一次钱, 列表里也不会堆一排重复文件。优先复用已解析完成的；
    同状态的取最新。仅限同一用户内复用（转写文本视为用户数据，不跨账号）。

    新文件先写盘再插行；插行失败时回滚刚写的文件，保证库里没有"幽灵路径"。
    """
    sha = hashlib.sha256(data).hexdigest()
    with db_conn() as conn:
        existing = conn.execute(
            f"""SELECT {_META_COLS} FROM attachments
                WHERE user_id = %s AND sha256 = %s
                ORDER BY CASE transcript_status
                            WHEN 'done' THEN 0 ELSE 1
                         END, created_at DESC
                LIMIT 1""",
            (user_id, sha),
        ).fetchone()
    if existing is not None:
        logger.info(
            "attachments: 同文件已存在, 复用老记录 (user=%s file=%r sha=%s... status=%s)",
            user_id, filename, sha[:12], existing["transcript_status"],
        )
        return {**dict(existing), "reused": True}

    att_id = str(uuid.uuid4())
    path_rel = f"{user_id}/{att_id}.bin"
    _write_file(path_rel, data)
    try:
        with db_conn() as conn:
            row = conn.execute(
                """INSERT INTO attachments (id, user_id, filename, mime, size_bytes, path, sha256)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, filename, mime, size_bytes,
                             transcript, transcript_status, created_at""",
                (att_id, user_id, filename, mime, len(data), path_rel, sha),
            ).fetchone()
        return dict(row)
    except Exception:
        _unlink(path_rel)
        raise


def list_attachments(user_id: str, limit: int = 200) -> list[dict]:
    """All attachments of the user, newest first (meta only, no file data)."""
    with db_conn() as conn:
        rows = conn.execute(
            f"""SELECT {_META_COLS} FROM attachments
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s""",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_attachment(user_id: str, attachment_id: str, *, with_data: bool = False) -> dict | None:
    """Return one attachment row for the owner (None otherwise / bad UUID).

    ``with_data=True`` 时把磁盘上的原始文件读进返回值的 ``data`` 字段；
    文件缺失时 ``data`` 为 None，由调用方决定如何响应。
    """
    cols = _META_COLS
    if with_data:
        cols += ", path"
    try:
        with db_conn() as conn:
            row = conn.execute(
                f"SELECT {cols} FROM attachments WHERE id = %s AND user_id = %s",
                (attachment_id, user_id),
            ).fetchone()
    except Exception:
        # 非法 UUID 等 → 统一按"不存在"处理, API 层转 404
        return None
    if row is None:
        return None
    out = dict(row)
    if with_data:
        out["data"] = _read_file(out["path"]) if out.get("path") else None
    return out


def update_transcript(attachment_id: str, transcript: str, status: str) -> None:
    """Persist a transcription result/status (done / failed / running)."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE attachments SET transcript = %s, transcript_status = %s WHERE id = %s",
            (transcript, status, attachment_id),
        )


def delete_attachment(user_id: str, attachment_id: str) -> bool:
    """Delete the metadata row and the backing file (best-effort unlink)."""
    with db_conn() as conn:
        row = conn.execute(
            "DELETE FROM attachments WHERE id = %s AND user_id = %s RETURNING path",
            (attachment_id, user_id),
        ).fetchone()
    if row is None:
        return False
    if row["path"]:
        _unlink(row["path"])
    return True


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


def storage_usage() -> int:
    """Total bytes on disk under the attachments root (运维/巡检用)。"""
    root = _storage_root()
    total = 0
    for child in root.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total
