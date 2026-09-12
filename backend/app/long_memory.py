"""长期记忆（跨会话事实记忆）：Mem0 + 现有 Postgres 的 pgvector。

两层记忆的分工（docs/memory-plan.md §9）：
- ``app/memory.py``  会话内短期上下文：前端重发 history + trim/摘要压缩；
- 本模块             跨会话长期事实记忆：学生偏好/薄弱点/约定，教练对话专用。

写入（:func:`remember`）：对话结束后把本轮问答交给 ``mem0.add`` —— mem0 用用户的
大模型配置做一次事实抽取（哈希去重），随后再做一次 LLM 标注给新事实打上
分类/重要性元数据（自动整理的排序依据），失败只打日志，绝不影响对话。
读取（:func:`recall`）：教练回复前用本轮 goal 检索该用户的记忆，按
相似度 × 重要性 × 时间衰减重排，命中条目记访问反馈，注入"学生画像 + 事实"。
整理（:func:`housekeeping_loop`）：定时任务合并重复事实、标记过时矛盾、
重建学生画像（:func:`consolidate_user` / :func:`refresh_profile`）。

关键决策：
- 抽取 LLM  = 用户的大模型配置（``store.get_llm_config``），费用记 ``token_usage``
  （gen_type='memory'），模型设置页可见；
- Embedding = 用户的向量模型配置（``store.get_embedding_config``，Key/BaseURL
  留空自动回退大模型对应值）；
- 向量库    = 现有 Postgres 的 pgvector（HNSW），collection 按维度分表
  ``zhixue_memory_{dims}`` —— 不同用户配不同维度的向量模型也不互相污染；
- 实例缓存  ：mem0 ``Memory`` 绑定 llm/embedder/连接池，按配置指纹 LRU 缓存
  （上限 8）；用户在「模型设置」保存后由 ``agent.reset_model_runtime`` 一并清空；
- 启用条件  ：大模型 API Key 与向量模型都配置才启用（抽取依赖大模型）；
  mem0 的 history SQLite 用默认路径（容器内临时目录，仅审计用途，记忆本体在 PG）。

mem0 内部调用是同步阻塞的，一律经 ``asyncio.to_thread`` 执行，不堵事件循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from collections import OrderedDict
from datetime import datetime, timezone

from openai import OpenAI

from . import store
from .config import settings

logger = logging.getLogger(__name__)

COLLECTION_PREFIX = "zhixue_memory"
MAX_CACHED_INSTANCES = 8
RECALL_LIMIT = 5
LIST_LIMIT = 100

# --- 自动整理参数 -----------------------------------------------------------
RECALL_POOL = 20          # 召回候选池: 向量检索取这么多条, 再本地重排选 top N
DEFAULT_CATEGORY = "其他"
CATEGORIES = ("学习偏好", "知识水平", "学习目标", "个人背景", "其他")
DEFAULT_IMPORTANCE = 3    # 1-5; 未标注/解析失败时的默认值
HALF_LIFE_DAYS = 90.0     # 时间衰减半衰期: 事实越旧, 召回分越低 (有下限)
MAX_PROFILE_CHARS = 600   # 学生画像长度上限
MAX_HOUSEKEEPING_OPS = 20  # 每轮整理最多执行的操作数 (防 LLM 输出失控)
HOUSEKEEPING_START_DELAY_SECONDS = 300  # 启动后先等 5 分钟再跑第一轮
HOUSEKEEPING_INTERVAL_HOURS = settings.memory_housekeeping_interval_hours
HOUSEKEEPING_MAX_USERS = 50  # 每轮最多处理的用户数

CUSTOM_INSTRUCTIONS = (
    "只记录与学生学习相关、值得跨会话记住的事实（年级/学科/薄弱知识点/学习偏好/目标约定），"
    "用中文、以第三人称的「学生」来表述，每条一句话；"
    "一次性寒暄、当天心情/天气、与学习无关的闲聊不要记录，只保留之后辅导还用得上的信息；"
    "忽略密码、身份证号等敏感信息；对话中没有值得长期记住的内容就返回空列表。"
)

# fire-and-forget 写入任务的强引用集（防止 Task 被垃圾回收，见 asyncio 文档）
_background: set[asyncio.Task] = set()


def collection_name_for_dims(dims: int) -> str:
    """pgvector collection 按向量维度分表，避免不同维度模型互串。"""
    return f"{COLLECTION_PREFIX}_{dims}"


def _probe_dims(api_key: str, model: str, base_url: str) -> int:
    """用一次真实 embedding 调用探测向量维度（每次构建实例时执行一次）。"""
    client = OpenAI(api_key=api_key, base_url=base_url or None)
    resp = client.embeddings.create(model=model, input=["dims probe"])
    return len(resp.data[0].embedding)


def _make_usage_callback(user_id: str):
    """mem0 抽取调用的 token 用量上报（记到 token_usage, gen_type='memory'）。"""

    def _callback(_llm, response, _params) -> None:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        try:
            store.record_token_usage(
                user_id,
                "memory",
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                kind="llm",
            )
        except Exception as exc:  # 计量失败不影响记忆写入
            logger.warning("long_memory: 记录抽取用量失败: %s", exc)

    return _callback


def _metered_embedder_class(user_id: str):
    """带 token 计量的 OpenAI embedder 子类（mem0 的 embedder 无回调钩子）。

    行为与 mem0 的 OpenAIEmbedding 一致（含 dimensions 传参逻辑），
    差异仅在把每次调用的 usage 记到 token_usage(kind='embedding')。
    """
    from mem0.embeddings.openai import OpenAIEmbedding

    class _MeteredOpenAIEmbedding(OpenAIEmbedding):
        def _record(self, response) -> None:
            usage = getattr(response, "usage", None)
            if not usage:
                return
            try:
                store.record_token_usage(
                    user_id,
                    "memory",
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=0,
                    total_tokens=getattr(usage, "total_tokens", 0) or 0,
                    kind="embedding",
                )
            except Exception as exc:
                logger.warning("long_memory: 记录 embedding 用量失败: %s", exc)

        def _kwargs(self, texts: list[str]) -> dict:
            kwargs = {"input": texts, "model": self.config.model, "encoding_format": "float"}
            if self._pass_dimensions_to_api:
                kwargs["dimensions"] = self.config.embedding_dims
            return kwargs

        def embed(self, text, memory_action=None):
            resp = self.client.embeddings.create(**self._kwargs([text.replace("\n", " ")]))
            self._record(resp)
            return resp.data[0].embedding

        def embed_batch(self, texts, memory_action="add"):
            texts = [t.replace("\n", " ") for t in texts]
            out: list = []
            for i in range(0, len(texts), 100):  # 与上游一致的 100 条分批
                resp = self.client.embeddings.create(**self._kwargs(texts[i : i + 100]))
                self._record(resp)
                out.extend(item.embedding for item in sorted(resp.data, key=lambda x: x.index))
            return out

    return _MeteredOpenAIEmbedding


def _build_instance(user_id: str):
    """按该用户的当前配置构建一个 mem0 ``Memory``（含一次 dims 探测调用）。

    返回 None 表示记忆功能未启用（大模型 Key 或向量模型未配置）。
    mem0 在函数内导入，保持模块导入轻量。
    """
    llm_cfg = store.get_llm_config(user_id)
    emb_cfg = store.get_embedding_config(user_id)
    if not llm_cfg[0] or not emb_cfg[1]:
        return None

    from mem0 import Memory
    from mem0.configs.base import MemoryConfig
    from mem0.embeddings.configs import EmbedderConfig
    from mem0.llms.configs import LlmConfig
    from mem0.vector_stores.configs import VectorStoreConfig

    api_key, llm_model, llm_base_url, _ = llm_cfg
    emb_key, emb_model, emb_base_url = emb_cfg
    dims = _probe_dims(emb_key, emb_model, emb_base_url)

    config = MemoryConfig(
        llm=LlmConfig(
            provider="openai",
            config={
                "model": llm_model,
                "api_key": api_key,
                "openai_base_url": llm_base_url or None,
                "temperature": 0.1,
                "response_callback": _make_usage_callback(user_id),
            },
        ),
        embedder=EmbedderConfig(
            provider="openai",
            config={
                "model": emb_model,
                "api_key": emb_key,
                "openai_base_url": emb_base_url or None,
                "embedding_dims": dims,
            },
        ),
        vector_store=VectorStoreConfig(
            provider="pgvector",
            config={
                "connection_string": settings.database_url,
                "collection_name": collection_name_for_dims(dims),
                "embedding_model_dims": dims,
                "hnsw": True,
                "maxconn": 2,
            },
        ),
        custom_instructions=CUSTOM_INSTRUCTIONS,
    )
    mem = Memory(config)
    # 换装带计量的 embedder (维度/请求行为与默认实例一致, 差异仅是记用量)
    from mem0.configs.embeddings.base import BaseEmbedderConfig

    mem.embedding_model = _metered_embedder_class(user_id)(
        BaseEmbedderConfig(
            model=emb_model,
            api_key=emb_key,
            openai_base_url=emb_base_url or None,
            embedding_dims=dims,
        )
    )
    logger.info("long_memory: instance built (user=%s, dims=%d, collection=%s)",
                user_id, dims, collection_name_for_dims(dims))
    return mem


def _fingerprint(user_id: str) -> tuple:
    """实例缓存的配置指纹：任一配置变化都重建实例。"""
    llm_cfg = store.get_llm_config(user_id)
    emb_cfg = store.get_embedding_config(user_id)
    return (llm_cfg[0], llm_cfg[1], llm_cfg[2], emb_cfg[0], emb_cfg[1], emb_cfg[2],
            settings.database_url)


class _MemoryCache:
    """按配置指纹 LRU 缓存 mem0 Memory 实例（线程安全，构建在锁外）。"""

    def __init__(self, maxsize: int = MAX_CACHED_INSTANCES):
        self._maxsize = maxsize
        self._entries: OrderedDict[tuple, object] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_build(self, user_id: str):
        key = _fingerprint(user_id)
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
        # 构建（含一次 embedding 探测调用）放在锁外，避免并发用户互相阻塞
        instance = _build_instance(user_id)
        if instance is None:
            return None
        with self._lock:
            self._entries[key] = instance
            while len(self._entries) > self._maxsize:
                _, old = self._entries.popitem(last=False)
                try:
                    old.close()
                except Exception:
                    pass
        return instance

    def clear(self) -> None:
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for old in entries:
            try:
                old.close()
            except Exception:
                pass


_cache = _MemoryCache()


def _get_instance(user_id: str):
    """记忆功能入口的唯一取实例路径：未配置（大模型 Key 或向量模型缺失）返回 None。"""
    if not store.is_llm_configured_for_user(user_id) or not store.is_embedding_configured_for_user(user_id):
        return None
    return _cache.get_or_build(user_id)


def clear_cache() -> None:
    """用户在「模型设置」保存后调用：丢弃全部缓存实例，按新配置重建。"""
    _cache.clear()


def _format_memory_item(it: dict) -> dict:
    """把 mem0 结果项规范成 API 用的 dict（id / memory / createdAt / updatedAt）。"""
    return {
        "id": str(it.get("id") or ""),
        "memory": (it.get("memory") or "").strip(),
        "createdAt": it.get("created_at"),
        "updatedAt": it.get("updated_at"),
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
    """同步检索 + 重排 + 命中反馈，供 to_thread 调用。"""
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
    picked = items[:limit]
    _touch_memories(mem, picked)
    return picked


async def recall(user_id: str, query: str, limit: int = RECALL_LIMIT) -> str:
    """检索该用户的长期记忆，返回注入教练提示词的文本块；无记忆/未启用/失败返回 ""。

    结构：有学生画像时先给画像段落，再给重排后的 "• 事实" 列表。
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
        if not lines:
            return ""
        profile = await asyncio.to_thread(store.get_memory_profile, user_id)
        if profile:
            lines.insert(0, f"【学生画像】{profile}")
        logger.info("long_memory: recalled %d item(s) (user=%s)", len(picked), user_id)
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("long_memory.recall failed (user=%s): %s", user_id, exc)
        return ""


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


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_importance(value) -> int:
    return max(1, min(5, _as_int(value, DEFAULT_IMPORTANCE)))


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


# ---------------------------------------------------------------------------
# 学生画像: 把散落的原子事实定期 LLM 压缩成一段结构化摘要（语义记忆层）。
# 召回时画像在前、原子事实在后——矛盾在画像层被消解, 细节由事实层兜底。
# ---------------------------------------------------------------------------

_PROFILE_SYSTEM = (
    "你是学习记忆整理助手。根据下面的事实清单，写一段学生画像，"
    "帮助学生教练快速了解这位学生。\n"
    "要求：中文；按「学习偏好 / 知识水平 / 学习目标 / 个人背景」归类成简短要点；"
    "只使用清单里的事实，不要编造；事实相互矛盾时以更晚发生的为准；"
    f"总长度不超过 {MAX_PROFILE_CHARS} 字；直接输出画像正文，不要解释。"
)


async def refresh_profile(user_id: str) -> str:
    """重建学生画像并存库，返回画像文本；未启用/无记忆/失败返回空串。"""
    if not user_id or not store.is_memory_enabled(user_id):
        return ""
    try:
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
        stats["profile"] = bool(await refresh_profile(user_id))
        if stats["merged"] or stats["superseded"] or stats["profile"]:
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
