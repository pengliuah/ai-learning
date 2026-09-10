"""Long-term memory (Mem0) glue tests — mem0 itself is faked out.

The real mem0 Memory needs network (LLM extraction + embeddings), so these
tests stub the instance layer and verify the glue: enable conditions,
recall formatting, remember payloads, error swallowing, and the background
task helper.
"""
from __future__ import annotations

import asyncio

import pytest

from app import long_memory, store


class _FakeMemory:
    def __init__(self, results=None, fail=False, get_all_results=None, get_map=None):
        self._results = results if results is not None else [{"memory": "学生喜欢天文", "score": 0.8}]
        self._get_all_results = (
            get_all_results
            if get_all_results is not None
            else [
                {
                    "id": "m1",
                    "memory": "学生喜欢天文",
                    "user_id": None,  # filled per-call if needed
                    "created_at": "2026-09-01T00:00:00Z",
                    "updated_at": None,
                }
            ]
        )
        self._get_map = get_map if get_map is not None else {}
        self._fail = fail
        self.searches: list[tuple] = []
        self.adds: list[tuple] = []
        self.get_alls: list[tuple] = []
        self.deletes: list[str] = []
        self.closed = False

    def search(self, query, **kwargs):
        if self._fail:
            raise RuntimeError("search boom")
        self.searches.append((query, kwargs))
        return {"results": self._results}

    def add(self, messages, **kwargs):
        if self._fail:
            raise RuntimeError("add boom")
        self.adds.append((messages, kwargs))

    def get_all(self, **kwargs):
        if self._fail:
            raise RuntimeError("get_all boom")
        self.get_alls.append(kwargs)
        return {"results": self._get_all_results}

    def get(self, memory_id):
        if self._fail:
            raise RuntimeError("get boom")
        return self._get_map.get(memory_id)

    def delete(self, memory_id):
        if self._fail:
            raise RuntimeError("delete boom")
        self.deletes.append(memory_id)
        return {"message": "ok"}

    def close(self):
        self.closed = True


class _StubCache:
    def __init__(self, instance):
        self.instance = instance
        self.build_attempts = 0

    def get_or_build(self, user_id):
        self.build_attempts += 1
        return self.instance

    def clear(self):
        self.instance = None


def test_collection_name_for_dims():
    assert long_memory.collection_name_for_dims(1024) == "zhixue_memory_1024"


def _configure_models(admin_user) -> str:
    """给测试用户配上模型设置, 使记忆功能处于「已启用」状态; 返回 user_id。"""
    user_id = str(admin_user["id"])
    store.update_model_settings(
        user_id,
        api_key="sk-test", model="test-chat-model", base_url="http://localhost:9/v1",
        embedding_model="test-embedding", embedding_base_url="http://localhost:9/v1",
        embedding_api_key="sk-emb",
    )
    return user_id


def test_recall_formats_and_scopes(tmp_store, admin_user):
    fake = _FakeMemory()
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    user_id = _configure_models(admin_user)
    try:
        out = asyncio.run(long_memory.recall(user_id, "我上次学到哪了"))
    finally:
        long_memory._cache = original
    assert out == "• 学生喜欢天文"
    assert fake.searches[0][0] == "我上次学到哪了"
    assert fake.searches[0][1]["filters"] == {"user_id": user_id}


def test_recall_empty_results_and_errors(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    original = long_memory._cache
    long_memory._cache = _StubCache(_FakeMemory(results=[]))
    try:
        assert asyncio.run(long_memory.recall(user_id, "hi")) == ""
        long_memory._cache = _StubCache(_FakeMemory(fail=True))
        # 异常吞掉, 返回空串 —— 记忆故障绝不影响对话
        assert asyncio.run(long_memory.recall(user_id, "hi")) == ""
    finally:
        long_memory._cache = original


def test_recall_skipped_without_query_or_user():
    assert asyncio.run(long_memory.recall("", "hi")) == ""
    assert asyncio.run(long_memory.recall("u1", "   ")) == ""


def test_remember_sends_turn_and_scopes(tmp_store, admin_user):
    fake = _FakeMemory()
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    user_id = _configure_models(admin_user)
    try:
        asyncio.run(long_memory.remember(user_id, "我喜欢天文", "好的，记住啦"))
    finally:
        long_memory._cache = original
    assert len(fake.adds) == 1
    messages, kwargs = fake.adds[0]
    assert messages == [
        {"role": "user", "content": "我喜欢天文"},
        {"role": "assistant", "content": "好的，记住啦"},
    ]
    assert kwargs == {"user_id": user_id}


def test_remember_ignores_empty_and_errors(tmp_store, admin_user):
    fake = _FakeMemory(fail=True)
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    user_id = _configure_models(admin_user)
    try:
        # 空内容不写; 失败只吞掉不抛
        asyncio.run(long_memory.remember(user_id, "", "reply"))
        asyncio.run(long_memory.remember(user_id, "goal", ""))
        asyncio.run(long_memory.remember(user_id, "goal", "reply"))
        assert fake.adds == []
    finally:
        long_memory._cache = original


def test_unconfigured_user_skips_everything(tmp_store, admin_user):
    """没配大模型 Key / 向量模型时, 整个记忆功能静默停用。"""
    user_id = str(admin_user["id"])  # tmp_store 里刚建的用户, 未配置任何模型
    original = long_memory._cache
    stub = _StubCache(_FakeMemory())
    long_memory._cache = stub
    try:
        assert asyncio.run(long_memory.recall(user_id, "hi")) == ""
        asyncio.run(long_memory.remember(user_id, "goal", "reply"))
        assert stub.build_attempts == 0  # 连实例构建都不该发生
    finally:
        long_memory._cache = original


def test_remember_background_no_loop_is_noop():
    """不在事件循环里调用时静默跳过 (不抛异常)。"""
    long_memory.remember_background("u1", "goal", "reply")


def test_clear_cache_closes_instances(tmp_store):
    fake = _FakeMemory()
    original = long_memory._cache
    long_memory._cache = long_memory._MemoryCache(maxsize=2)
    try:
        long_memory._cache._entries[("k",)] = fake
        long_memory.clear_cache()
        assert fake.closed
    finally:
        long_memory._cache = original


def test_build_instance_none_when_unconfigured(tmp_store, admin_user):
    """未配置模型时 _build_instance 返回 None (不触网)。"""
    assert long_memory._build_instance(str(admin_user["id"])) is None


def test_configured_user_can_build_instance(tmp_store, admin_user):
    """配置齐全时 _build_instance 能构建真实 Memory (连 zhixue_test 的 pgvector)。"""
    user_id = str(admin_user["id"])
    store.update_model_settings(
        user_id,
        api_key="sk-test", model="test-chat-model", base_url="http://localhost:9/v1",
        embedding_model="test-embedding", embedding_base_url="http://localhost:9/v1",
        embedding_api_key="sk-emb",
    )

    class _FakeEmbeddings:
        def create(self, **kwargs):
            class _D:
                embedding = [0.0] * 4
            class _R:
                data = [_D()]
            return _R()

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            self.embeddings = _FakeEmbeddings()

    orig_openai = long_memory.OpenAI
    long_memory.OpenAI = _FakeOpenAI
    try:
        mem = long_memory._build_instance(user_id)
    finally:
        long_memory.OpenAI = orig_openai
    assert mem is not None
    mem.close()


def test_master_switch_skips_recall_and_remember(tmp_store, admin_user):
    """总开关关闭时 recall/remember 静默跳过（不触碰 mem0）。"""
    user_id = _configure_models(admin_user)
    store.update_memory_settings(user_id, enabled=False)
    fake = _FakeMemory()
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        assert asyncio.run(long_memory.recall(user_id, "hi")) == ""
        asyncio.run(long_memory.remember(user_id, "goal", "reply"))
        assert fake.searches == []
        assert fake.adds == []
    finally:
        long_memory._cache = original
        store.update_memory_settings(user_id, enabled=True)


def test_list_memories_formats(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    fake = _FakeMemory(
        get_all_results=[
            {
                "id": "abc",
                "memory": "学生喜欢天文",
                "created_at": "2026-09-01T00:00:00Z",
                "updated_at": None,
            },
            {"id": "", "memory": "应被丢掉"},
            {"id": "xyz", "memory": ""},
        ]
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        items = asyncio.run(long_memory.list_memories(user_id))
    finally:
        long_memory._cache = original
    assert items == [
        {
            "id": "abc",
            "memory": "学生喜欢天文",
            "createdAt": "2026-09-01T00:00:00Z",
            "updatedAt": None,
        }
    ]
    assert fake.get_alls[0]["filters"] == {"user_id": user_id}


def test_delete_memory_checks_ownership(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    fake = _FakeMemory(
        get_map={
            "mine": {"id": "mine", "memory": "x", "user_id": user_id},
            "theirs": {"id": "theirs", "memory": "y", "user_id": "other"},
        }
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        assert asyncio.run(long_memory.delete_memory(user_id, "mine")) is True
        assert asyncio.run(long_memory.delete_memory(user_id, "theirs")) is False
        assert asyncio.run(long_memory.delete_memory(user_id, "missing")) is False
    finally:
        long_memory._cache = original
    assert fake.deletes == ["mine"]


def test_list_and_delete_when_disabled_still_work(tmp_store, admin_user):
    """总开关关闭时仍可 list/delete（管理页要能清掉旧记忆）。"""
    user_id = _configure_models(admin_user)
    store.update_memory_settings(user_id, enabled=False)
    fake = _FakeMemory(
        get_all_results=[{"id": "m1", "memory": "旧事实", "created_at": None, "updated_at": None}],
        get_map={"m1": {"id": "m1", "memory": "旧事实", "user_id": user_id}},
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        items = asyncio.run(long_memory.list_memories(user_id))
        assert len(items) == 1
        assert asyncio.run(long_memory.delete_memory(user_id, "m1")) is True
    finally:
        long_memory._cache = original
        store.update_memory_settings(user_id, enabled=True)
    assert fake.deletes == ["m1"]
