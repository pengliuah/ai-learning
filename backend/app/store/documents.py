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


