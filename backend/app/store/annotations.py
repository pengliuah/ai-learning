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
# Annotations (per-user 学习内容批注, Word 式笔记)
#
# 锚定模型: (plan_id, module_key) + quote/prefix/suffix, 前端在渲染后的
# DOM 文本里重定位。不 FK modules.id —— 保存/重建计划会更换模块 UUID。
# ---------------------------------------------------------------------------

def _annotation_public(row) -> dict:
    return {
        "id": str(row["id"]),
        "planId": str(row["plan_id"]),
        "moduleKey": row["module_key"],
        "quote": row["quote"],
        "prefix": row["prefix"],
        "suffix": row["suffix"],
        "note": row["note"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _assert_plan_owner(conn, user_id: str, plan_id: str) -> None:
    """Raise KeyError when the plan does not exist or is not the user's."""
    row = conn.execute(
        "SELECT 1 FROM plans WHERE id::text = %s AND user_id::text = %s",
        (plan_id, user_id),
    ).fetchone()
    if row is None:
        raise KeyError(plan_id)


def list_annotations(user_id: str, plan_id: str, module_key: str) -> list[dict]:
    """The user's annotations for one module, oldest first."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT a.* FROM annotations a
               JOIN plans p ON p.id = a.plan_id
               WHERE a.user_id::text = %s AND p.id::text = %s AND a.module_key = %s
               ORDER BY a.created_at, a.id""",
            (user_id, plan_id, module_key),
        ).fetchall()
    return [_annotation_public(r) for r in rows]


def list_all_annotations(user_id: str) -> list[dict]:
    """The user's annotations across all plans/modules (bookmark list page).

    Each row carries plan/module titles for display; newest first. A missing
    module row (content regenerated away) keeps the annotation with a null
    module title.
    """
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT a.*, p.title AS plan_title, m.title AS module_title
               FROM annotations a
               JOIN plans p ON p.id = a.plan_id
               LEFT JOIN modules m ON m.plan_id = a.plan_id AND m.key = a.module_key
               WHERE a.user_id::text = %s
               ORDER BY a.created_at DESC, a.id DESC""",
            (user_id,),
        ).fetchall()
    items = []
    for r in rows:
        d = _annotation_public(r)
        d["plan_title"] = r["plan_title"]
        d["module_title"] = r["module_title"]
        items.append(d)
    return items


def create_annotation(
    user_id: str,
    plan_id: str,
    module_key: str,
    quote: str,
    prefix: str = "",
    suffix: str = "",
    note: str = "",
) -> dict:
    """Insert one annotation; raises KeyError when the plan is not the user's."""
    with db_conn() as conn:
        _assert_plan_owner(conn, user_id, plan_id)
        row = conn.execute(
            """INSERT INTO annotations (user_id, plan_id, module_key, quote, prefix, suffix, note)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (user_id, plan_id, module_key, quote, prefix, suffix, note),
        ).fetchone()
    return _annotation_public(row)


def update_annotation(
    user_id: str, plan_id: str, annotation_id: str, note: str
) -> dict:
    """Update an annotation's note; raises KeyError when not found/not owned."""
    with db_conn() as conn:
        _assert_plan_owner(conn, user_id, plan_id)
        row = conn.execute(
            """UPDATE annotations SET note = %s
               WHERE id::text = %s AND plan_id::text = %s AND user_id::text = %s
               RETURNING *""",
            (note, annotation_id, plan_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError(annotation_id)
    return _annotation_public(row)


def delete_annotation(user_id: str, plan_id: str, annotation_id: str) -> bool:
    """Delete one annotation; False when not found or not owned."""
    with db_conn() as conn:
        _assert_plan_owner(conn, user_id, plan_id)
        row = conn.execute(
            """DELETE FROM annotations
               WHERE id::text = %s AND plan_id::text = %s AND user_id::text = %s
               RETURNING id""",
            (annotation_id, plan_id, user_id),
        ).fetchone()
    return row is not None
