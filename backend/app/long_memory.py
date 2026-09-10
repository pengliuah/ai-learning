"""长期记忆（跨会话事实记忆）：Mem0 + 现有 Postgres 的 pgvector。

两层记忆的分工（docs/memory-plan.md §9）：
- ``app/memory.py``  会话内短期上下文：前端重发 history + trim/摘要压缩；
- 本模块             跨会话长期事实记忆：学生偏好/薄弱点/约定，教练对话专用。

写入（:func:`remember`）：对话结束后把本轮问答交给 ``mem0.add`` —— mem0 用用户的
大模型配置做一次事实抽取（自带哈希去重与关联），失败只打日志，绝不影响对话。
读取（:func:`recall`）：教练回复前用本轮 goal 检索该用户的记忆，拼成 "• 事实" 列表。

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
import logging
import threading
from collections import OrderedDict

from openai import OpenAI

from . import store
from .config import settings

logger = logging.getLogger(__name__)

COLLECTION_PREFIX = "zhixue_memory"
MAX_CACHED_INSTANCES = 8
RECALL_LIMIT = 5
LIST_LIMIT = 100

CUSTOM_INSTRUCTIONS = (
    "只记录与学生学习相关、值得跨会话记住的事实（年级/学科/薄弱知识点/学习偏好/目标约定），"
    "用中文、以第三人称的「学生」来表述，每条一句话；"
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


async def recall(user_id: str, query: str, limit: int = RECALL_LIMIT) -> str:
    """检索该用户的长期记忆，返回 "• 事实" 多行文本；无记忆/未启用/失败返回 ""。

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
        result = await asyncio.to_thread(
            mem.search,
            query.strip(),
            top_k=limit,
            filters={"user_id": user_id},
        )
        items = (result or {}).get("results") or []
        lines = [f"• {it['memory']}" for it in items if it.get("memory")]
        if lines:
            logger.info("long_memory: recalled %d item(s) (user=%s)", len(lines), user_id)
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("long_memory.recall failed (user=%s): %s", user_id, exc)
        return ""


async def remember(user_id: str, goal: str, reply: str) -> None:
    """把本轮问答写入长期记忆（mem0 内部做事实抽取，1 次大模型调用）。

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

        def _add() -> None:
            mem.add(messages, user_id=user_id)

        await asyncio.to_thread(_add)
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
