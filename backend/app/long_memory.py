"""长期记忆: 读写召回门面 + 实例层 (memory_client) + 整理层 (memory_curation)。"""

from __future__ import annotations

import asyncio
import json
import math
import logging
from datetime import datetime, timezone

from . import store
from .memory_client import (  # noqa: F401  实例层与常量 re-export
    CATEGORIES,
    COLLECTION_PREFIX,
    CUSTOM_INSTRUCTIONS,
    DEFAULT_CATEGORY,
    DEFAULT_IMPORTANCE,
    HALF_LIFE_DAYS,
    HOUSEKEEPING_INTERVAL_HOURS,
    HOUSEKEEPING_MAX_USERS,
    HOUSEKEEPING_START_DELAY_SECONDS,
    LIST_LIMIT,
    MAX_CACHED_INSTANCES,
    MAX_HOUSEKEEPING_OPS,
    MAX_PROFILE_CHARS,
    RECALL_POOL,
    RECALL_LIMIT,
    _MemoryCache,
    _as_int,
    _build_instance,
    _cache,
    _clamp_importance,
    _get_instance,
    clear_cache,
    collection_name_for_dims,
)
from .memory_curation import (  # noqa: F401  整理层 re-export
    _enrich_new_memories,
    classify_facts,
    consolidate_user,
    housekeeping_loop,
    parse_classification,
    parse_housekeeping,
    refresh_profile,
)

logger = logging.getLogger(__name__)

# fire-and-forget 任务的强引用集（防止 Task 被垃圾回收）
_background: set = set()

def _format_memory_item(it: dict) -> dict:
    """把 mem0 结果项规范成 API 用的 dict。

    整理元数据 (category/importance/superseded) 在 mem0 返回项的 metadata
    子字典里, 一并带出供状态页/管理 UI 使用。
    """
    meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
    return {
        "id": str(it.get("id") or ""),
        "memory": (it.get("memory") or "").strip(),
        "createdAt": it.get("created_at"),
        "updatedAt": it.get("updated_at"),
        "category": meta.get("category"),
        "importance": meta.get("importance"),
        "superseded": bool(meta.get("superseded")),
    }


def _memory_sort_key(item: dict) -> str:
    """时间倒序排序键：优先 updatedAt，否则 createdAt；无时间沉底。"""
    return item.get("updatedAt") or item.get("createdAt") or ""



# ---------------------------------------------------------------------------
# 召回重排: mem0 的向量相似度只是"语义像不像", 这里再叠加
# 重要性权重(写入时 LLM 标注)与时间衰减, 并排除被整理任务标记过时的条目。
# ---------------------------------------------------------------------------

def _parse_dt(value) -> datetime | None:
    """宽容地解析 payload 里的时间（ISO 字符串或 epoch 秒），失败返回 None。"""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def rank_score(
    similarity: float,
    importance: int,
    created_at: datetime | None,
    now: datetime,
) -> float:
    """召回排序分 = 相似度 × 重要性权重 × 时间衰减。

    重要性 1-5 映射到 0.6~1.0 的乘子（未标注按 3 ≈ 0.8）；
    衰减以 HALF_LIFE_DAYS 为半衰期指数下降，但有 0.75 的下限——
    老而重要的记忆不该被彻底埋没。
    """
    imp = max(1, min(5, int(importance or DEFAULT_IMPORTANCE)))
    importance_weight = 0.5 + 0.1 * imp
    if created_at is None:
        age_days = 0.0
    else:
        age_days = max(0.0, (now - created_at).total_seconds() / 86400)
    recency = 0.75 + 0.25 * math.exp(-age_days / HALF_LIFE_DAYS)
    return float(similarity) * importance_weight * recency


def _item_rank_key(item: dict, now: datetime) -> float:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    created = _parse_dt(item.get("created_at") or meta.get("created_at"))
    try:
        similarity = float(item.get("score") or 0.0)
    except (TypeError, ValueError):
        similarity = 0.0
    return rank_score(similarity, _clamp_importance(meta.get("importance")), created, now)


def _touch_memories(mem, items: list[dict]) -> None:
    """命中反馈：被召回注入的记忆记一次访问（access_count/last_accessed_at）。

    mem0 的 update(metadata=...) 是 payload 合并语义且不动正文；
    单条失败只降级，不影响召回。
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    for it in items:
        mid = it.get("id")
        if not mid:
            continue
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        try:
            mem.update(
                mid,
                metadata={
                    "access_count": _as_int(meta.get("access_count")) + 1,
                    "last_accessed_at": now_iso,
                },
            )
        except Exception as exc:
            logger.debug("long_memory: 命中反馈写回失败 id=%s: %s", mid, exc)


def _sync_recall(mem, user_id: str, query: str, limit: int) -> list[dict]:
    """同步检索 + 重排，供 to_thread 调用（不含命中反馈——那要走后台）。"""
    now = datetime.now(timezone.utc)
    result = mem.search(query, top_k=RECALL_POOL, filters={"user_id": user_id})
    items = []
    for it in (result or {}).get("results") or []:
        if not (it.get("memory") or "").strip():
            continue
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        if meta.get("superseded"):
            continue  # 被整理任务标记过时的旧事实不再参与召回
        items.append(it)
    items.sort(key=lambda it: _item_rank_key(it, now), reverse=True)
    return items[:limit]


async def recall(user_id: str, query: str, limit: int = RECALL_LIMIT) -> str:
    """检索该用户的长期记忆，返回注入教练提示词的文本块；无记忆/未启用/失败返回 ""。

    结构：有学生画像时先给画像段落，再给重排后的 "• 事实" 列表。
    命中反馈（access_count 写回）走后台任务——mem0 的 update 即使只改元数据
    也会重新调一次 embedding，不能让它阻塞教练的首 token。
    任何异常都吞掉并只打日志 —— 记忆检索绝不能让教练对话失败。
    """
    if not user_id or not query.strip():
        return ""
    if not store.is_memory_enabled(user_id):
        return ""
    try:
        mem = _get_instance(user_id)
        if mem is None:
            return ""
        picked = await asyncio.to_thread(_sync_recall, mem, user_id, query.strip(), limit)
        lines = [f"• {it['memory'].strip()}" for it in picked if it.get("memory")]
        if lines:
            # 命中反馈 fire-and-forget（复用 _background 强引用集）
            task = asyncio.create_task(asyncio.to_thread(_touch_memories, mem, picked))
            _background.add(task)
            task.add_done_callback(_background.discard)
            profile = await asyncio.to_thread(store.get_memory_profile, user_id)
            if profile:
                lines.insert(0, f"【学生画像】{profile}")
            logger.info("long_memory: recalled %d item(s) (user=%s)", len(picked), user_id)
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("long_memory.recall failed (user=%s): %s", user_id, exc)
        return ""



async def remember(user_id: str, goal: str, reply: str) -> None:
    """把本轮问答写入长期记忆（mem0 事实抽取 + 标签标注，2 次大模型调用）。

    任何异常都吞掉并只打日志 —— 记忆写入绝不能让教练对话失败。
    """
    goal = (goal or "").strip()
    reply = (reply or "").strip()
    if not user_id or not goal or not reply:
        return
    if not store.is_memory_enabled(user_id):
        logger.debug("long_memory: 总开关关闭，跳过写入 (user=%s)", user_id)
        return
    try:
        mem = _get_instance(user_id)
        if mem is None:
            logger.debug("long_memory: 未启用（大模型/向量模型未配齐），跳过写入 (user=%s)", user_id)
            return
        messages = [
            {"role": "user", "content": goal},
            {"role": "assistant", "content": reply},
        ]

        def _add_and_enrich() -> None:
            result = mem.add(messages, user_id=user_id)
            # 抽取不到新事实 / 标注失败都只是少了元数据, 不影响记忆本体
            _enrich_new_memories(mem, result)

        await asyncio.to_thread(_add_and_enrich)
        logger.info("long_memory: memory written (user=%s, goal=%d chars)", user_id, len(goal))
    except Exception as exc:
        logger.warning("long_memory.remember failed (user=%s): %s", user_id, exc)


async def list_memories(user_id: str, limit: int = LIST_LIMIT) -> list[dict]:
    """列出该用户的长期记忆；未配置模型或失败时返回空列表。

    管理页用：总开关关闭时仍可查看已有记忆。
    """
    if not user_id:
        return []
    try:
        mem = _get_instance(user_id)
        if mem is None:
            return []
        result = await asyncio.to_thread(
            mem.get_all,
            filters={"user_id": user_id},
            top_k=limit,
        )
        items = (result or {}).get("results") or []
        out = [_format_memory_item(it) for it in items if it.get("memory")]
        out = [m for m in out if m["id"]]
        out.sort(key=_memory_sort_key, reverse=True)
        return out
    except Exception as exc:
        logger.warning("long_memory.list_memories failed (user=%s): %s", user_id, exc)
        return []


async def delete_memory(user_id: str, memory_id: str) -> bool:
    """删除一条属于该用户的记忆。成功 True；不存在或不属于该用户 False。

    未配置模型时无法访问向量库，返回 False。
    """
    memory_id = (memory_id or "").strip()
    if not user_id or not memory_id:
        return False
    try:
        mem = _get_instance(user_id)
        if mem is None:
            return False

        def _owned_delete() -> bool:
            existing = mem.get(memory_id)
            if not existing:
                return False
            # 只允许删自己的记忆（mem0 按 id 全局查，必须校验 user_id）
            if str(existing.get("user_id") or "") != str(user_id):
                return False
            mem.delete(memory_id)
            return True

        ok = await asyncio.to_thread(_owned_delete)
        if ok:
            logger.info("long_memory: deleted (user=%s, id=%s)", user_id, memory_id)
        return ok
    except Exception as exc:
        logger.warning("long_memory.delete_memory failed (user=%s, id=%s): %s",
                       user_id, memory_id, exc)
        return False


async def update_memory_text(user_id: str, memory_id: str, text: str) -> bool:
    """用户编辑一条属于自己的长期记忆的正文。

    mem0 的 update 会保留 payload 元数据并重新 embedding；归属校验同删除。
    """
    memory_id = (memory_id or "").strip()
    text = (text or "").strip()
    if not user_id or not memory_id or not text:
        return False
    try:
        mem = _get_instance(user_id)
        if mem is None:
            return False

        def _owned_update() -> bool:
            existing = mem.get(memory_id)
            if not existing:
                return False
            if str(existing.get("user_id") or "") != str(user_id):
                return False
            mem.update(memory_id, text=text)
            # 正文变了, 原分类/重要性可能不再贴切: 顺路重标注一次
            try:
                label = classify_facts(mem, [text])[0]
                mem.update(memory_id, metadata=dict(label))
            except Exception as exc:
                logger.debug("long_memory: 编辑后重标注失败 id=%s: %s", memory_id, exc)
            return True

        ok = await asyncio.to_thread(_owned_update)
        if ok:
            logger.info("long_memory: memory edited (user=%s, id=%s, %d chars)",
                        user_id, memory_id, len(text))
        return ok
    except Exception as exc:
        logger.warning("long_memory.update_memory_text failed (user=%s, id=%s): %s",
                       user_id, memory_id, exc)
        return False


async def archive(user_id: str, content: str) -> bool:
    """把用户明确要求保存的内容原样写入长期记忆（聊天页「存档」按钮）。

    用 ``infer=False`` 跳过抽取，逐字入库——用户点名要记的内容不做改写；
    入库后仍走一次标注（分类/重要性）。任何失败吞掉返回 False。
    """
    content = (content or "").strip()
    if not user_id or not content:
        return False
    if not store.is_memory_enabled(user_id):
        return False
    try:
        mem = _get_instance(user_id)
        if mem is None:
            return False

        def _add_and_enrich() -> None:
            result = mem.add(
                [{"role": "user", "content": content}],
                user_id=user_id,
                infer=False,
            )
            _enrich_new_memories(mem, result)

        await asyncio.to_thread(_add_and_enrich)
        logger.info("long_memory: archived (user=%s, %d chars)", user_id, len(content))
        return True
    except Exception as exc:
        logger.warning("long_memory.archive failed (user=%s): %s", user_id, exc)
        return False


def remember_background(user_id: str, goal: str, reply: str) -> None:
    """在事件循环里创建后台写入任务（fire-and-forget），立即返回。

    供 ``coach_stream`` 的 finally 块调用：响应收尾不被记忆写入阻塞。
    不在事件循环里（如测试同步调用）时静默跳过。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(remember(user_id, goal, reply))
    _background.add(task)
    task.add_done_callback(_background.discard)


