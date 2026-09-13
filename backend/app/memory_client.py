"""mem0 实例层: 实例构建/配置指纹缓存/计量 (从 long_memory.py 拆出)。

curation 与读写门面都经由本层取得 mem0 ``Memory``; 常量集中在这里,
门面 (long_memory.py) 全量 re-export 以保持 ``long_memory.X`` 的兼容。
"""

from __future__ import annotations

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
LIST_LIMIT = 500

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
    "用中文、以第三人称的「学生」来表述；每条一到两句话，"
    "保留关键细节（具体数字、名称、时间、程度、原因），不要为了精简而丢信息；"
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



def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_importance(value) -> int:
    return max(1, min(5, _as_int(value, DEFAULT_IMPORTANCE)))


