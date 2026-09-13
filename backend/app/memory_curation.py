"""记忆自动整理: 标注 / 画像 / 夜间合并与过时标记 (从 long_memory.py 拆出)。

依赖 memory_client 的实例层; 对外由 long_memory.py 门面 re-export。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from . import store
from .memory_client import (
    CATEGORIES,
    DEFAULT_CATEGORY,
    DEFAULT_IMPORTANCE,
    HOUSEKEEPING_INTERVAL_HOURS,
    HOUSEKEEPING_MAX_USERS,
    HOUSEKEEPING_START_DELAY_SECONDS,
    MAX_HOUSEKEEPING_OPS,
    MAX_PROFILE_CHARS,
    _clamp_importance,
    _get_instance,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 写入打标签: mem0 的 add 是纯新增管道(哈希去重, 无逐条元数据), 这里在写入后
# 用一次 LLM 调用给新事实统一标注 category/importance, 写回 payload metadata。
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM = (
    "你是学习记忆整理助手。对给定的若干条学生事实逐条标注：\n"
    'category: 从 ["学习偏好", "知识水平", "学习目标", "个人背景", "其他"] 中选一个；\n'
    "importance: 1-5 整数，5=对长期辅导非常关键（年级、学习目标、重大偏好），"
    "3=一般事实，1=可有可无的细节。\n"
    '只输出 JSON：{"items": [{"index": 0, "category": "学习偏好", "importance": 3}]}，'
    "index 对应输入条目的序号，不要输出解释。"
)


def _loads_loose(raw: str) -> dict:
    """尽力从 LLM 输出中解析 JSON：截取首个 { 到最后一个 } 的片段，失败返回 {}。"""
    if not raw:
        return {}
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(raw[start : end + 1], strict=False)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def parse_classification(raw: str, count: int) -> list[dict]:
    """解析标注 LLM 的输出为 count 个标签；解析不出的条目用默认值兜底。"""
    labels = [
        {"category": DEFAULT_CATEGORY, "importance": DEFAULT_IMPORTANCE}
        for _ in range(count)
    ]
    items = _loads_loose(raw).get("items")
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        idx = it.get("index")
        if not isinstance(idx, int) or not 0 <= idx < count:
            continue
        if it.get("category") in CATEGORIES:
            labels[idx]["category"] = it["category"]
        labels[idx]["importance"] = _clamp_importance(it.get("importance"))
    return labels


def classify_facts(mem, texts: list[str]) -> list[dict]:
    """给一批事实标注 category/importance（1 次 LLM 调用，经 mem0 计量）。

    任何失败都退回默认标签 —— 标注只是增强，绝不能让写入失败。
    """
    if not texts:
        return []
    defaults = [
        {"category": DEFAULT_CATEGORY, "importance": DEFAULT_IMPORTANCE}
        for _ in texts
    ]
    try:
        listing = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
        raw = mem.llm.generate_response(
            [
                {"role": "system", "content": _CLASSIFY_SYSTEM},
                {"role": "user", "content": listing},
            ]
        )
        labels = parse_classification(raw or "", len(texts))
        return labels or defaults
    except Exception as exc:
        logger.warning("long_memory: 事实标注失败, 用默认标签: %s", exc)
        return defaults


def _enrich_new_memories(mem, result: dict | None) -> None:
    """add() 之后给新写入的事实写回 category/importance 元数据。"""
    items = [
        (r.get("id"), (r.get("memory") or "").strip())
        for r in (result or {}).get("results") or []
        if r.get("id") and (r.get("memory") or "").strip()
    ]
    if not items:
        return
    labels = classify_facts(mem, [text for _, text in items])
    for (mid, _text), label in zip(items, labels):
        try:
            mem.update(mid, metadata=dict(label))
        except Exception as exc:
            logger.debug("long_memory: 标签写回失败 id=%s: %s", mid, exc)


# ---------------------------------------------------------------------------
# 学生画像: 把散落的原子事实定期 LLM 压缩成一段结构化摘要（语义记忆层）。
# 召回时画像在前、原子事实在后——矛盾在画像层被消解, 细节由事实层兜底。
# ---------------------------------------------------------------------------

_PROFILE_SYSTEM = (
    "你是学习记忆整理助手。根据下面的事实清单，为学生教练整理一份「学生画像」，"
    "这份画像会展示给学生本人并允许其修改，所以要写得清晰、好读、好改。\n"
    "要求：\n"
    "- 中文；先用一句话概括这位学生，再用「小标题 + 要点列表」组织；\n"
    "- 小标题按内容自然划分（如 学习偏好 / 知识水平 / 目标与进展 / 个人背景），"
    "有什么写什么，不必凑齐固定模板；\n"
    "- 每个要点保留具体细节（数字、名称、时间、程度），一行一条，方便逐条修改；\n"
    "- 只使用清单里的事实，不要编造；事实冲突时以更晚发生的为准，"
    "并在该要点末尾标注（YYYY-MM 更新）；\n"
    f"- 总长度不超过 {MAX_PROFILE_CHARS} 字；直接输出画像正文，不要解释。"
)


async def refresh_profile(user_id: str) -> str:
    """重建学生画像并存库，返回画像文本；未启用/无记忆/失败返回空串。

    用户在记忆页手动修改过画像 (edited_by_user=true) 时跳过自动刷新——
    用户的修正优先于夜间整理。
    """
    if not user_id or not store.is_memory_enabled(user_id):
        return ""
    try:
        if store.is_profile_edited_by_user(user_id):
            logger.info("long_memory: 画像被用户手动修改过, 跳过自动刷新 (user=%s)", user_id)
            return (await asyncio.to_thread(store.get_memory_profile, user_id)) or ""
        mem = _get_instance(user_id)
        if mem is None:
            return ""

        def _build() -> str:
            result = mem.get_all(filters={"user_id": user_id}, top_k=300)
            facts = [
                (it.get("memory") or "").strip()
                for it in (result or {}).get("results") or []
                if (it.get("memory") or "").strip()
                and not (it.get("metadata") or {}).get("superseded")
            ]
            if not facts:
                store.save_memory_profile(user_id, "")
                return ""
            listing = "\n".join(f"- {t}" for t in facts[:200])
            profile = (mem.llm.generate_response(
                [
                    {"role": "system", "content": _PROFILE_SYSTEM},
                    {"role": "user", "content": listing},
                ]
            ) or "").strip()
            profile = profile[:MAX_PROFILE_CHARS]
            store.save_memory_profile(user_id, profile)
            return profile

        profile = await asyncio.to_thread(_build)
        if profile:
            logger.info("long_memory: 学生画像已更新 (user=%s, %d chars)", user_id, len(profile))
        return profile
    except Exception as exc:
        logger.warning("long_memory.refresh_profile failed (user=%s): %s", user_id, exc)
        return ""


# ---------------------------------------------------------------------------
# 夜间整理: 合并语义重复 / 标记过时矛盾 / 之后刷新画像。
# 只用 mem0 公开 API（update/delete），操作白名单化且总数封顶，坏输出直接丢弃。
# ---------------------------------------------------------------------------

_HOUSEKEEPING_SYSTEM = (
    "你是学习记忆整理助手。下面是一名学生的长期记忆事实清单，"
    "每行格式：编号. [日期][分类|重要性] 内容。\n"
    "请只做两类整理，输出 JSON，不要解释：\n"
    '1) merges: 语义重复的多条合并成一条，'
    '{"keep_id": "保留条目的编号", "drop_ids": ["要删除的条目编号", ...], '
    '"text": "合并后的一句话事实（中文，以「学生」开头）"}；\n'
    '2) supersede: 明显过时或与较新事实矛盾的旧条目，'
    '{"id": "编号", "reason": "简述原因"}，被标记的条目将不再参与召回；\n'
    "不要新增记忆，不要改动没有问题的条目，操作总数不超过 "
    f"{MAX_HOUSEKEEPING_OPS}。没有需要整理的，输出 "
    '{"merges": [], "supersede": []}。\n'
    '输出格式：{"merges": [...], "supersede": [...]}'
)


def parse_housekeeping(raw: str) -> dict:
    """解析整理 LLM 的输出；结构不对的部分直接丢弃。"""
    data = _loads_loose(raw)
    ops = {"merges": [], "supersede": []}
    for m in data.get("merges") if isinstance(data.get("merges"), list) else []:
        if isinstance(m, dict) and m.get("keep_id") is not None:
            ops["merges"].append(m)
    for s in data.get("supersede") if isinstance(data.get("supersede"), list) else []:
        if isinstance(s, dict) and s.get("id") is not None:
            ops["supersede"].append(s)
    return ops


def _apply_housekeeping_ops(mem, live_items: list[dict], ops: dict) -> dict:
    """把整理操作应用到向量库，返回实际生效的条数。非法编号/失败的单条跳过。"""
    id_by_idx = {str(i): it.get("id") for i, it in enumerate(live_items) if it.get("id")}
    merged_texts: list[tuple[str, str]] = []  # (memory_id, merged_text) 待重新标注
    merged = superseded = 0

    for op in ops.get("merges")[:MAX_HOUSEKEEPING_OPS]:
        keep = id_by_idx.get(str(op.get("keep_id")))
        drops = [
            id_by_idx[str(d)]
            for d in op.get("drop_ids") or []
            if str(d) in id_by_idx and id_by_idx[str(d)] != keep
        ]
        text = (op.get("text") or "").strip()
        if not keep or not drops or not text:
            continue
        try:
            mem.update(keep, text=text)
            for d in drops:
                mem.delete(d)
            merged += 1
            merged_texts.append((keep, text))
        except Exception as exc:
            logger.warning("long_memory: 合并失败 (keep=%s): %s", keep, exc)

    for op in ops.get("supersede")[:MAX_HOUSEKEEPING_OPS]:
        sid = id_by_idx.get(str(op.get("id")))
        if not sid:
            continue
        try:
            mem.update(
                sid,
                metadata={
                    "superseded": True,
                    "superseded_reason": (op.get("reason") or "")[:100],
                },
            )
            superseded += 1
        except Exception as exc:
            logger.warning("long_memory: 过时标记失败 (id=%s): %s", sid, exc)

    # 合并后的新文本重新标注分类/重要性（1 次 LLM 调用）
    if merged_texts:
        labels = classify_facts(mem, [t for _, t in merged_texts])
        for (mid, _t), label in zip(merged_texts, labels):
            try:
                mem.update(mid, metadata=dict(label))
            except Exception as exc:
                logger.debug("long_memory: 合并后标注失败 id=%s: %s", mid, exc)

    return {"merged": merged, "superseded": superseded}


async def consolidate_user(user_id: str) -> dict:
    """整理单个用户的记忆：合并重复 → 标记过时 → 刷新画像。返回统计。

    整理只用用户的模型配置（经 mem0 计量）；任何失败都吞掉并返回当前统计。
    """
    stats = {"merged": 0, "superseded": 0, "profile": False}
    if not user_id or not store.is_memory_enabled(user_id):
        return stats
    try:
        mem = _get_instance(user_id)
        if mem is None:
            return stats

        def _run() -> dict:
            result = mem.get_all(filters={"user_id": user_id}, top_k=400)
            live = [
                it
                for it in (result or {}).get("results") or []
                if (it.get("memory") or "").strip()
                and not (it.get("metadata") or {}).get("superseded")
            ]
            if len(live) < 2:
                return {"merged": 0, "superseded": 0}
            lines = []
            for i, it in enumerate(live):
                meta = it.get("metadata") or {}
                created = (str(it.get("created_at") or "") or "????-??-??")[:10]
                lines.append(
                    f"{i}. [{created}]"
                    f"[{meta.get('category') or DEFAULT_CATEGORY}|"
                    f"{meta.get('importance') or DEFAULT_IMPORTANCE}] "
                    f"{it['memory'].strip()}"
                )
            raw = mem.llm.generate_response(
                [
                    {"role": "system", "content": _HOUSEKEEPING_SYSTEM},
                    {"role": "user", "content": "\n".join(lines)},
                ]
            )
            return _apply_housekeeping_ops(mem, live, parse_housekeeping(raw or ""))

        stats.update(await asyncio.to_thread(_run))
        # 用户手动修正过画像时 refresh_profile 会跳过重写, 这里如实标记 False
        if store.is_profile_edited_by_user(user_id):
            stats["profile"] = False
        else:
            stats["profile"] = bool(await refresh_profile(user_id))
        logger.info("long_memory: 整理完成 (user=%s) %s", user_id, stats)
        return stats
    except Exception as exc:
        logger.warning("long_memory.consolidate_user failed (user=%s): %s", user_id, exc)
        return stats


async def housekeeping_loop() -> None:
    """夜间整理循环：启动后延迟数分钟跑第一轮，之后每轮间隔数小时。

    由 main 的 lifespan 拉起（MEMORY_HOUSEKEEPING=false 可关闭）。
    每轮只处理「最久未整理」的有限个用户；单用户失败不影响其他用户。
    """
    logger.info(
        "long_memory: 夜间整理循环启动 (首轮延迟 %ds, 间隔 %dh)",
        HOUSEKEEPING_START_DELAY_SECONDS,
        HOUSEKEEPING_INTERVAL_HOURS,
    )
    await asyncio.sleep(HOUSEKEEPING_START_DELAY_SECONDS)
    while True:
        try:
            # 顺手清理过期/已吊销的 refresh token (原本无人调用, 表只进不出)
            await asyncio.to_thread(store.delete_expired_refresh_tokens)
            users = await asyncio.to_thread(
                store.stale_housekeeping_users, HOUSEKEEPING_MAX_USERS
            )
            for uid in users:
                try:
                    await consolidate_user(uid)
                except Exception as exc:  # 单用户失败继续下一个
                    logger.warning("long_memory: 整理用户失败 (user=%s): %s", uid, exc)
                finally:
                    await asyncio.to_thread(store.touch_housekeeping, uid)
            if users:
                logger.info("long_memory: 本轮整理完成, %d 个用户", len(users))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("long_memory.housekeeping_loop: %s", exc)
        await asyncio.sleep(HOUSEKEEPING_INTERVAL_HOURS * 3600)
