"""PostgreSQL-backed store: CRUD for learning plans and module artifacts.

Replaces the former JSON-file store (plans.json).  All plan operations are
scoped to an owning ``user_id`` (account system): the caller (routes) passes
the authenticated user's id and every query filters on ``plans.user_id``.

Plan interface:

    list_documents / list_items / get_document / save_document
    create_document / delete_document / update_module   (all take user_id)

``update_module`` keeps the ``mutate(module)`` callback pattern: it loads the
module, applies the callback, then syncs the module and all its child rows
(content, questions, grading result + question results) back to the DB in one
transaction.

Settings (model / IMA / generation strategy) are per-user tables keyed by
``user_id``; the database is the single source of truth. User accounts and
refresh tokens are managed here too (used by ``auth.py`` and the routes).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from psycopg import errors as psycopg_errors
from psycopg.types.json import Jsonb

from .config import settings
from .db import db_conn
from .schemas import (
    Assessment,
    Content,
    Difficulty,
    Document,
    GradingResult,
    Level,
    Module,
    ModuleStatus,
    Plan,
    PlanListItem,
    PlanSource,
    Question,
    QuestionResult,
    QuestionType,
    Quiz,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Row -> Pydantic assembly
# ---------------------------------------------------------------------------

def _load_module(conn, row) -> Module:
    """Build a Module (with content / quiz / result) from a modules row."""
    mod_id = row["id"]

    content: Content | None = None
    cr = conn.execute(
        "SELECT markdown, key_takeaways FROM module_contents WHERE module_id = %s",
        (mod_id,),
    ).fetchone()
    if cr:
        content = Content(markdown=cr["markdown"], keyTakeaways=cr["key_takeaways"])

    quiz: Quiz | None = None
    q_rows = conn.execute(
        """SELECT key, type, prompt, options, answer, answers, model_answer,
                  key_points, explanation
           FROM questions WHERE module_id = %s ORDER BY sort_order""",
        (mod_id,),
    ).fetchall()
    if q_rows:
        quiz = Quiz(questions=[
            Question(
                id=qr["key"],
                type=QuestionType(qr["type"]),
                prompt=qr["prompt"],
                options=qr["options"],
                answer=qr["answer"],
                answers=qr.get("answers") or [],
                modelAnswer=qr["model_answer"],
                keyPoints=qr["key_points"],
                explanation=qr["explanation"],
            )
            for qr in q_rows
        ])

    result: GradingResult | None = None
    gr = conn.execute(
        """SELECT total_score, max_score, strengths, weaknesses,
                  recommendations, assessment_level
           FROM grading_results WHERE module_id = %s""",
        (mod_id,),
    ).fetchone()
    if gr:
        qr_rows = conn.execute(
            """SELECT question_key, score, max_score, correct, feedback,
                      student_answer
               FROM question_results WHERE grading_module_id = %s
               ORDER BY sort_order""",
            (mod_id,),
        ).fetchall()
        result = GradingResult(
            results=[
                QuestionResult(
                    questionId=qrr["question_key"],
                    score=float(qrr["score"]),
                    maxScore=float(qrr["max_score"]),
                    correct=qrr["correct"],
                    feedback=qrr["feedback"],
                    studentAnswer=qrr["student_answer"],
                )
                for qrr in qr_rows
            ],
            totalScore=float(gr["total_score"]),
            maxScore=float(gr["max_score"]),
            assessment=Assessment(
                strengths=gr["strengths"],
                weaknesses=gr["weaknesses"],
                recommendations=gr["recommendations"],
                level=Level(gr["assessment_level"]),
            ),
        )

    return Module(
        id=row["key"],
        title=row["title"],
        summary=row["summary"],
        objectives=row["objectives"],
        minutes=row["minutes"],
        difficulty=Difficulty(row["difficulty"]),
        status=ModuleStatus(row["status"]),
        content=content,
        quiz=quiz,
        result=result,
        answers=row["answers"],
    )


def _load_document(conn, plan_id: str, user_id: str) -> Document | None:
    """Assemble a full Document (plan + all modules + children) from DB.

    Scoped to ``user_id``: another user's plan id looks up as missing.
    Ids are compared as text so malformed (non-UUID) ids from URLs simply
    match nothing instead of raising a cast error.
    """
    row = conn.execute(
        """SELECT id, title, goal, summary, level, total_minutes,
                  source_input, source_mode, created_at, updated_at
           FROM plans WHERE id::text = %s AND user_id::text = %s""",
        (plan_id, user_id),
    ).fetchone()
    if row is None:
        return None

    mod_rows = conn.execute(
        """SELECT id, key, title, summary, objectives, minutes, difficulty,
                  status, sort_order, answers
           FROM modules WHERE plan_id = %s ORDER BY sort_order""",
        (plan_id,),
    ).fetchall()
    modules = [_load_module(conn, mr) for mr in mod_rows]

    return Document(
        id=str(row["id"]),
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
        source=PlanSource(input=row["source_input"], mode=row["source_mode"]),
        plan=Plan(
            title=row["title"],
            goal=row["goal"],
            summary=row["summary"],
            level=Level(row["level"]),
            totalMinutes=row["total_minutes"],
            modules=modules,
        ),
    )


# ---------------------------------------------------------------------------
# Pydantic -> DB row writers
# ---------------------------------------------------------------------------

def _insert_children(conn, mod_uuid: str, module: Module, now: datetime) -> None:
    """Insert content, questions, and grading result for a module.

    Assumes the module row already exists and has no child rows yet (used by
    both create and the delete-then-insert sync in update).
    """
    if module.content is not None:
        conn.execute(
            """INSERT INTO module_contents
                   (module_id, markdown, key_takeaways, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (mod_uuid, module.content.markdown,
             Jsonb(module.content.keyTakeaways), now, now),
        )

    if module.quiz is not None:
        for j, q in enumerate(module.quiz.questions):
            conn.execute(
                """INSERT INTO questions
                       (module_id, key, type, prompt, options, answer, answers,
                        model_answer, key_points, explanation, sort_order)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (mod_uuid, q.id, q.type.value, q.prompt, Jsonb(q.options),
                 q.answer, Jsonb(q.answers), q.modelAnswer, Jsonb(q.keyPoints),
                 q.explanation, j),
            )

    if module.result is not None:
        r = module.result
        conn.execute(
            """INSERT INTO grading_results
                   (module_id, total_score, max_score, strengths, weaknesses,
                    recommendations, assessment_level, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (mod_uuid, r.totalScore, r.maxScore,
             Jsonb(r.assessment.strengths), Jsonb(r.assessment.weaknesses),
             Jsonb(r.assessment.recommendations), r.assessment.level.value, now),
        )
        for j, qr in enumerate(r.results):
            conn.execute(
                """INSERT INTO question_results
                       (grading_module_id, question_key, score, max_score,
                        correct, feedback, student_answer, sort_order)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (mod_uuid, qr.questionId, qr.score, qr.maxScore,
                 qr.correct, qr.feedback, qr.studentAnswer, j),
            )


def _sync_module(conn, plan_id: str, module: Module) -> None:
    """Update a module row and replace all its child rows.

    Called after ``mutate()`` has modified the in-memory Module: writes the
    new status / answers, then deletes and re-inserts content, questions, and
    grading result so the DB matches the Pydantic object exactly.
    """
    row = conn.execute(
        "SELECT id FROM modules WHERE plan_id = %s AND key = %s",
        (plan_id, module.id),
    ).fetchone()
    if row is None:
        raise KeyError(module.id)
    mod_uuid = row["id"]

    answers_val = Jsonb(module.answers) if module.answers is not None else None
    conn.execute(
        "UPDATE modules SET status = %s, answers = %s WHERE id = %s",
        (module.status.value, answers_val, mod_uuid),
    )

    now = datetime.now(timezone.utc)

    # Delete old children, then re-insert (handles create/replace/clear).
    conn.execute("DELETE FROM module_contents WHERE module_id = %s", (mod_uuid,))
    conn.execute("DELETE FROM questions WHERE module_id = %s", (mod_uuid,))
    conn.execute("DELETE FROM grading_results WHERE module_id = %s", (mod_uuid,))
    _insert_children(conn, mod_uuid, module, now)

    # Touch plan row so its updated_at trigger fires.
    conn.execute("UPDATE plans SET updated_at = now() WHERE id = %s", (plan_id,))


# ---------------------------------------------------------------------------
# Public store API (same interface as the former JSON store)
# ---------------------------------------------------------------------------

def list_documents(user_id: str) -> list[Document]:
    with db_conn() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM plans WHERE user_id = %s ORDER BY sort_order, created_at",
            (user_id,)).fetchall()]
        docs = [_load_document(conn, str(pid), user_id) for pid in ids]
    logger.debug("list_documents: user=%s count=%d", user_id, len(docs))
    return docs


def list_items(user_id: str, q: str | None = None) -> list[PlanListItem]:
    """List the user's plan summaries, optionally filtered by a
    case-insensitive title substring. An empty/whitespace ``q`` (or None)
    returns all of the user's plans."""
    q = (q or "").strip()
    where = "WHERE p.user_id = %s AND p.title ILIKE %s" if q else "WHERE p.user_id = %s"
    params: tuple = (user_id, f"%{q}%") if q else (user_id,)
    sql = f"""SELECT p.id, p.title, p.created_at,
                     COUNT(m.id) AS total,
                     COUNT(m.id) FILTER (WHERE m.status = 'completed') AS done
              FROM plans p
              LEFT JOIN modules m ON m.plan_id = p.id
              {where}
              GROUP BY p.id, p.title, p.created_at
              ORDER BY p.sort_order, p.created_at"""
    with db_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = [
        PlanListItem(
            id=str(r["id"]),
            title=r["title"],
            createdAt=r["created_at"],
            progress=round(r["done"] / r["total"], 4) if r["total"] else 0.0,
        )
        for r in rows
    ]
    logger.debug("list_items: q=%s count=%d", q or "-", len(items))
    return items


def get_document(plan_id: str, user_id: str) -> Document | None:
    with db_conn() as conn:
        doc = _load_document(conn, plan_id, user_id)
    logger.debug("get_document: plan_id=%s found=%s", plan_id, doc is not None)
    return doc


def save_document(doc: Document, user_id: str) -> Document:
    """Upsert a full document (plan + modules + children) owned by ``user_id``.

    Used by ``create_document``; also supports re-saving an existing doc by
    replacing all modules and their children.
    """
    now = datetime.now(timezone.utc)
    p = doc.plan
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO plans
                   (id, user_id, title, goal, summary, level, total_minutes,
                    source_input, source_mode, sort_order, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                       COALESCE((SELECT MAX(sort_order) + 1 FROM plans WHERE user_id = %s), 0),
                       %s, %s)
               ON CONFLICT (id) DO UPDATE SET
                   title = EXCLUDED.title, goal = EXCLUDED.goal,
                   summary = EXCLUDED.summary, level = EXCLUDED.level,
                   total_minutes = EXCLUDED.total_minutes,
                   source_input = EXCLUDED.source_input,
                   source_mode = EXCLUDED.source_mode""",
            (doc.id, user_id, p.title, p.goal, p.summary, p.level.value,
             p.totalMinutes, doc.source.input, doc.source.mode,
             user_id, doc.createdAt, doc.updatedAt),
        )
        # Replace modules (cascade deletes old children).
        conn.execute("DELETE FROM modules WHERE plan_id = %s", (doc.id,))
        for i, module in enumerate(p.modules):
            mod_uuid = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO modules
                       (id, plan_id, key, title, summary, objectives, minutes,
                        difficulty, status, sort_order, answers,
                        created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (mod_uuid, doc.id, module.id, module.title, module.summary,
                 Jsonb(module.objectives), module.minutes, module.difficulty.value,
                 module.status.value, i,
                 Jsonb(module.answers) if module.answers is not None else None,
                 now, now),
            )
            _insert_children(conn, mod_uuid, module, now)
    logger.debug("save_document: plan_id=%s", doc.id)
    return doc


def create_document(source: PlanSource, plan: Plan, user_id: str) -> Document:
    now = datetime.now(timezone.utc)
    doc = Document(
        id=str(uuid.uuid4()),
        createdAt=now,
        updatedAt=now,
        source=source,
        plan=plan,
    )
    logger.debug("create_document: plan_id=%s title=%s", doc.id, plan.title)
    return save_document(doc, user_id)


def delete_document(plan_id: str, user_id: str) -> bool:
    with db_conn() as conn:
        result = conn.execute(
            "DELETE FROM plans WHERE id::text = %s AND user_id::text = %s",
            (plan_id, user_id))
        deleted = result.rowcount > 0
    logger.debug("delete_document: plan_id=%s deleted=%s", plan_id, deleted)
    return deleted


def update_module(
    plan_id: str, module_id: str, mutate: Callable[[Module], None], user_id: str
) -> Document:
    """Load a module, apply ``mutate``, sync changes to DB, return full doc."""
    logger.debug("update_module: plan_id=%s module_id=%s", plan_id, module_id)
    with db_conn() as conn:
        doc = _load_document(conn, plan_id, user_id)
        if doc is None:
            raise KeyError(plan_id)
        module = next((m for m in doc.plan.modules if m.id == module_id), None)
        if module is None:
            raise KeyError(module_id)
        mutate(module)
        _sync_module(conn, plan_id, module)
        # Reload to pick up the trigger-set updated_at and any DB defaults.
        doc = _load_document(conn, plan_id, user_id)
    return doc


def reorder_plans(plan_ids: list[str], user_id: str) -> None:
    """持久化学习计划列表的手动排序（首页拖拽排序）。

    ``plan_ids`` 顺序即新顺序；只更新当前用户的 ``plans.sort_order``。
    """
    with db_conn() as conn:
        for pos, plan_id in enumerate(plan_ids):
            conn.execute(
                "UPDATE plans SET sort_order = %s WHERE id::text = %s AND user_id::text = %s",
                (pos, plan_id, user_id),
            )
    logger.debug("reorder_plans: user=%s count=%d", user_id, len(plan_ids))


# ---------------------------------------------------------------------------
# IMA settings (per-user table: credentials + skill prompt)
# ---------------------------------------------------------------------------

def get_ima_settings_row(user_id: str) -> dict:
    """Return the user's ima settings row, creating defaults if missing."""
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
    return dict(row)


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
        params.append(api_key)
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
        row = conn.execute(
            "SELECT * FROM user_ima_settings WHERE user_id = %s", (user_id,)
        ).fetchone()
    return dict(row)


# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Model settings (per-user: LLM API key / model / base URL)
#
# Saved from the web UI ("模型设置"). Empty fields fall back to the ARK_*
# environment variables (and their built-in defaults), so env vars still
# seed fresh deployments.
# ---------------------------------------------------------------------------

def get_model_settings_row(user_id: str) -> dict:
    """Return the user's model settings row, creating defaults if missing."""
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
    return dict(row)


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
        params.append(api_key.strip())
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
        params.append(embedding_api_key.strip())
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
        row = conn.execute(
            "SELECT * FROM user_model_settings WHERE user_id = %s", (user_id,)
        ).fetchone()
    return dict(row)


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


def save_memory_profile(user_id: str, profile: str) -> None:
    """写入/更新学生画像（夜间整理与画像重建共用）。"""
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO user_memory_profile (user_id, profile) VALUES (%s, %s)
               ON CONFLICT (user_id)
               DO UPDATE SET profile = EXCLUDED.profile, updated_at = now()""",
            (user_id, (profile or "").strip()),
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
