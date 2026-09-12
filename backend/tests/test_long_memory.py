"""Long-term memory (Mem0) glue tests — mem0 itself is faked out.

The real mem0 Memory needs network (LLM extraction + embeddings), so these
tests stub the instance layer and verify the glue: enable conditions,
recall formatting, remember payloads, error swallowing, and the background
task helper.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app import long_memory, store


class _FakeLLM:
    """mem0 LLM 桩：按顺序吐出预设回复，记录调用到的消息。"""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls: list = []

    def generate_response(self, messages, **kwargs):
        self.calls.append(messages)
        return self.responses.pop(0) if self.responses else ""


class _FakeMemory:
    def __init__(
        self,
        results=None,
        fail=False,
        get_all_results=None,
        get_map=None,
        add_result=None,
        llm_responses=None,
    ):
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
        self._add_result = add_result
        self._fail = fail
        self.searches: list[tuple] = []
        self.adds: list[tuple] = []
        self.updates: list[dict] = []
        self.get_alls: list[tuple] = []
        self.deletes: list[str] = []
        self.llm = _FakeLLM(llm_responses)
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
        return self._add_result

    def update(self, memory_id, text=None, metadata=None):
        if self._fail:
            raise RuntimeError("update boom")
        self.updates.append({"id": memory_id, "text": text, "metadata": metadata})
        return {"message": "Memory updated successfully!"}

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


def test_list_memories_sorted_newest_first(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    fake = _FakeMemory(
        get_all_results=[
            {
                "id": "old",
                "memory": "旧事实",
                "created_at": "2026-09-01T10:00:00Z",
                "updated_at": None,
            },
            {
                "id": "new",
                "memory": "新事实",
                "created_at": "2026-09-01T08:00:00Z",
                "updated_at": "2026-09-10T12:30:45Z",
            },
            {
                "id": "mid",
                "memory": "中间",
                "created_at": "2026-09-05T00:00:00Z",
                "updated_at": None,
            },
        ]
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        items = asyncio.run(long_memory.list_memories(user_id))
    finally:
        long_memory._cache = original
    assert [m["id"] for m in items] == ["new", "mid", "old"]


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


# ---------------------------------------------------------------------------
# 自动整理: 写入打标签 / 召回重排与命中反馈 / 学生画像 / 夜间整理
# ---------------------------------------------------------------------------

def test_remember_enriches_new_facts(tmp_store, admin_user):
    """remember 后对新事实做一次 LLM 标注, category/importance 写回 payload。"""
    add_result = {"results": [{"id": "m1", "memory": "学生喜欢天文", "event": "ADD"}]}
    llm = ['参考 {"items": [{"index": 0, "category": "学习偏好", "importance": 5}]} 完']
    fake = _FakeMemory(add_result=add_result, llm_responses=llm)
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    user_id = _configure_models(admin_user)
    try:
        asyncio.run(long_memory.remember(user_id, "我喜欢天文", "好的"))
    finally:
        long_memory._cache = original
    assert fake.updates == [
        {"id": "m1", "text": None, "metadata": {"category": "学习偏好", "importance": 5}}
    ]
    # 两次 LLM 调用: mem0 抽取 + 标注 (抽取在 mem0 内部, 这里只见标注一次)
    assert len(fake.llm.calls) == 1


def test_remember_enrich_garbage_llm_uses_defaults(tmp_store, admin_user):
    """标注 LLM 输出乱码时用默认标签兜底, 不影响记忆本体。"""
    add_result = {"results": [{"id": "m1", "memory": "学生喜欢天文", "event": "ADD"}]}
    fake = _FakeMemory(add_result=add_result, llm_responses=["我不会输出 JSON"])
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    user_id = _configure_models(admin_user)
    try:
        asyncio.run(long_memory.remember(user_id, "goal", "reply"))
    finally:
        long_memory._cache = original
    assert fake.updates == [
        {
            "id": "m1",
            "text": None,
            "metadata": {"category": "其他", "importance": long_memory.DEFAULT_IMPORTANCE},
        }
    ]


def test_recall_reranks_and_touches(tmp_store, admin_user):
    """重排: 重要性/衰减参与排序; 被标记过时的条目不召回不触碰; 命中写访问反馈。"""
    recent = datetime.now(timezone.utc).isoformat()
    fake = _FakeMemory(
        results=[
            {
                "id": "weak-new",
                "memory": "新但无关紧要",
                "score": 0.80,
                "created_at": recent,
                "metadata": {"importance": 1},
            },
            {
                "id": "strong-old",
                "memory": "旧但重要",
                "score": 0.76,
                "created_at": "2020-01-01T00:00:00Z",
                "metadata": {"importance": 5},
            },
            {
                "id": "dead",
                "memory": "已被新事实取代",
                "score": 0.99,
                "created_at": recent,
                "metadata": {"superseded": True},
            },
        ]
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    user_id = _configure_models(admin_user)
    try:
        out = asyncio.run(long_memory.recall(user_id, "还记得我吗"))
    finally:
        long_memory._cache = original
    assert out.splitlines() == ["• 旧但重要", "• 新但无关紧要"]
    assert {u["id"] for u in fake.updates} == {"strong-old", "weak-new"}
    for u in fake.updates:
        assert u["metadata"]["access_count"] == 1
        assert u["metadata"]["last_accessed_at"]


def test_recall_injects_profile_before_facts(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    store.save_memory_profile(user_id, "学生喜欢天文，初一年级。")
    fake = _FakeMemory()
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        out = asyncio.run(long_memory.recall(user_id, "我上次学到哪了"))
    finally:
        long_memory._cache = original
    assert out == "【学生画像】学生喜欢天文，初一年级。\n• 学生喜欢天文"


def test_refresh_profile_builds_and_saves(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    fake = _FakeMemory(
        get_all_results=[
            {"id": "m1", "memory": "学生喜欢天文", "created_at": "2026-09-01T00:00:00Z", "metadata": {}}
        ],
        llm_responses=["学生喜欢天文；对宇宙感兴趣。"],
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        out = asyncio.run(long_memory.refresh_profile(user_id))
    finally:
        long_memory._cache = original
    assert out == "学生喜欢天文；对宇宙感兴趣。"
    assert store.get_memory_profile(user_id) == "学生喜欢天文；对宇宙感兴趣。"


def test_refresh_profile_clears_when_no_memories(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    fake = _FakeMemory(get_all_results=[], llm_responses=["不应该被调用"])
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        assert asyncio.run(long_memory.refresh_profile(user_id)) == ""
    finally:
        long_memory._cache = original
    assert store.get_memory_profile(user_id) == ""
    assert fake.llm.calls == []  # 没有事实就不该调用 LLM


def test_consolidate_user_applies_ops_and_refreshes_profile(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    fake = _FakeMemory(
        get_all_results=[
            {"id": "m1", "memory": "学生喜欢天文", "created_at": "2026-09-01T00:00:00Z",
             "metadata": {"importance": 3, "category": "学习偏好"}},
            {"id": "m2", "memory": "学生对天文感兴趣", "created_at": "2026-09-02T00:00:00Z",
             "metadata": {"importance": 3, "category": "学习偏好"}},
            {"id": "m3", "memory": "学生不喜欢语文", "created_at": "2026-09-03T00:00:00Z",
             "metadata": {"importance": 2, "category": "学习偏好"}},
        ],
        llm_responses=[
            '{"merges": [{"keep_id": 0, "drop_ids": [1], "text": "学生喜欢天文学"}], '
            '"supersede": [{"id": 2, "reason": "较新事实矛盾"}]}',
            '{"items": [{"index": 0, "category": "学习偏好", "importance": 4}]}',
            "学生喜欢天文学；暂时不喜欢语文。",
        ],
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        stats = asyncio.run(long_memory.consolidate_user(user_id))
    finally:
        long_memory._cache = original
    assert stats == {"merged": 1, "superseded": 1, "profile": True}
    assert fake.deletes == ["m2"]
    # m1 有两次 update: 先合并改写正文, 再合并后重新标注
    text_update = next(u for u in fake.updates if u["id"] == "m1" and u["text"])
    assert text_update["text"] == "学生喜欢天文学"
    label_update = next(
        u
        for u in fake.updates
        if u["id"] == "m1" and u["metadata"] and u["metadata"].get("importance") == 4
    )
    assert label_update["metadata"]["category"] == "学习偏好"
    superseded_update = next(u for u in fake.updates if u["id"] == "m3")
    assert superseded_update["metadata"]["superseded"] is True  # 过时标记
    assert store.get_memory_profile(user_id) == "学生喜欢天文学；暂时不喜欢语文。"


def test_consolidate_user_validates_ids(tmp_store, admin_user):
    """LLM 幻觉出的编号必须被丢弃, 不能碰别人的/不存在的记忆。"""
    user_id = _configure_models(admin_user)
    fake = _FakeMemory(
        get_all_results=[
            {"id": "m1", "memory": "学生喜欢天文", "created_at": "2026-09-01T00:00:00Z", "metadata": {}},
            {"id": "m2", "memory": "学生初二", "created_at": "2026-09-02T00:00:00Z", "metadata": {}},
        ],
        llm_responses=[
            '{"merges": [{"keep_id": 99, "drop_ids": [1], "text": "x"}], '
            '"supersede": [{"id": 77, "reason": "y"}]}',
            "画像。",
        ],
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        stats = asyncio.run(long_memory.consolidate_user(user_id))
    finally:
        long_memory._cache = original
    assert stats["merged"] == 0 and stats["superseded"] == 0
    assert fake.deletes == []
    assert all(u["id"] in ("m1", "m2") for u in fake.updates)


def test_consolidate_user_skips_llm_with_single_fact(tmp_store, admin_user):
    user_id = _configure_models(admin_user)
    fake = _FakeMemory(
        get_all_results=[
            {"id": "m1", "memory": "学生喜欢天文", "created_at": "2026-09-01T00:00:00Z", "metadata": {}}
        ],
        llm_responses=["学生喜欢天文。"],
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)
    try:
        stats = asyncio.run(long_memory.consolidate_user(user_id))
    finally:
        long_memory._cache = original
    assert stats["merged"] == 0 and stats["superseded"] == 0 and stats["profile"] is True
    assert len(fake.llm.calls) == 1  # 只有画像一次, 整理没跑


def test_housekeeping_store_roundtrip(tmp_store, admin_user):
    """水位表: 没跑过的用户被选中, 跑过的不重复; 画像读写往返。"""
    user_id = str(admin_user["id"])
    # 还没用过记忆的用户不该被选中 (避免为沉默账号白建实例)
    assert store.stale_housekeeping_users() == []
    store.record_token_usage(user_id, "memory", total_tokens=1)
    assert store.stale_housekeeping_users() == [user_id]
    store.touch_housekeeping(user_id)
    assert store.stale_housekeeping_users() == []
    assert store.get_memory_profile(user_id) == ""
    store.save_memory_profile(user_id, "画像内容")
    assert store.get_memory_profile(user_id) == "画像内容"


def test_housekeeping_loop_processes_pending_users(tmp_store, admin_user, monkeypatch):
    """循环任务: 只处理水位落后且用过记忆的用户, 整理与画像真实生效。"""
    monkeypatch.setattr(long_memory, "HOUSEKEEPING_START_DELAY_SECONDS", 0)
    monkeypatch.setattr(long_memory, "HOUSEKEEPING_INTERVAL_HOURS", 10**6)
    user_id = _configure_models(admin_user)
    store.record_token_usage(user_id, "memory", total_tokens=1)
    fake = _FakeMemory(
        get_all_results=[
            {"id": "m1", "memory": "学生喜欢天文", "created_at": "2026-09-01T00:00:00Z", "metadata": {}},
            {"id": "m2", "memory": "学生对天文感兴趣", "created_at": "2026-09-02T00:00:00Z", "metadata": {}},
        ],
        llm_responses=[
            '{"merges": [{"keep_id": 0, "drop_ids": [1], "text": "学生喜欢天文学"}], "supersede": []}',
            '{"items": [{"index": 0, "category": "学习偏好", "importance": 4}]}',
            "学生喜欢天文学。",
        ],
    )
    original = long_memory._cache
    long_memory._cache = _StubCache(fake)

    async def _run():
        task = asyncio.create_task(long_memory.housekeeping_loop())
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(_run())
    finally:
        long_memory._cache = original
    assert fake.deletes == ["m2"]
    assert store.get_memory_profile(user_id) == "学生喜欢天文学。"
    assert store.stale_housekeeping_users() == []  # 水位已推进


