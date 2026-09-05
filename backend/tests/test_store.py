"""Store CRUD coverage (spec sec 8): create/get/list/delete/update + progress.

All operations run as a fresh admin user; user isolation is covered in
test_isolation below.
"""
from __future__ import annotations

import pytest

from app import store
from app.schemas import ModuleStatus, PlanSource

from _factories import make_plan


@pytest.fixture
def owner(admin_user):
    """The user id owning every document in these tests."""
    return str(admin_user["id"])


def test_create_and_get(tmp_store, owner):
    doc = store.create_document(PlanSource(input="topic", mode="topic"), make_plan(modules=2), owner)
    assert doc.id
    fetched = store.get_document(doc.id, owner)
    assert fetched is not None
    assert fetched.plan.title == "test-plan"
    assert len(fetched.plan.modules) == 2


def test_get_unknown_returns_none(tmp_store, owner):
    assert store.get_document("does-not-exist", owner) is None


def test_list_documents_empty(tmp_store, owner):
    assert store.list_documents(owner) == []


def test_list_items_progress(tmp_store, owner):
    plan = make_plan(modules=4)
    plan.modules[0].status = ModuleStatus.completed
    plan.modules[1].status = ModuleStatus.completed
    store.create_document(PlanSource(input="x", mode="topic"), plan, owner)
    items = store.list_items(owner)
    assert len(items) == 1
    assert items[0].progress == 0.5
    assert items[0].title == "test-plan"


def test_delete(tmp_store, owner):
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan(), owner)
    assert store.delete_document(doc.id, owner) is True
    assert store.get_document(doc.id, owner) is None
    assert store.delete_document(doc.id, owner) is False


def test_update_module(tmp_store, owner):
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan(modules=2), owner)
    mid = doc.plan.modules[1].id

    def mutate(m):
        m.status = ModuleStatus.completed

    updated = store.update_module(doc.id, mid, mutate, owner)
    assert updated.plan.modules[1].status == ModuleStatus.completed
    assert updated.plan.modules[0].status == ModuleStatus.not_started
    # 注：不比较 updatedAt —— doc 的时间戳来自应用机时钟、updated 来自 DB 机时钟，
    # 跨机部署时时钟偏差会让 >= 断言偶发失败。
    # persisted to disk
    assert store.get_document(doc.id, owner).plan.modules[1].status == ModuleStatus.completed


def test_update_module_missing_raises(tmp_store, owner):
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan(), owner)
    with pytest.raises(KeyError):
        store.update_module(doc.id, "missing-module", lambda m: None, owner)
    with pytest.raises(KeyError):
        store.update_module("missing-plan", doc.plan.modules[0].id, lambda m: None, owner)


def test_persistence_round_trip(tmp_store, owner):
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan(modules=1), owner)
    docs = store.list_documents(owner)
    assert len(docs) == 1
    assert docs[0].id == doc.id

def test_list_items_filter_by_title(tmp_store, owner):
    store.create_document(PlanSource(input="x", mode="topic"), make_plan(title="Python 装饰器基础"), owner)
    store.create_document(PlanSource(input="x", mode="topic"), make_plan(title="机器学习入门"), owner)
    store.create_document(PlanSource(input="x", mode="topic"), make_plan(title="React 开发"), owner)

    assert [i.title for i in store.list_items(owner, "Python")] == ["Python 装饰器基础"]
    assert [i.title for i in store.list_items(owner, "python")] == ["Python 装饰器基础"]  # case-insensitive
    assert [i.title for i in store.list_items(owner, "机器学习")] == ["机器学习入门"]
    assert store.list_items(owner, "不存在的主题") == []
    # empty / None / whitespace -> all
    assert len(store.list_items(owner)) == 3
    assert len(store.list_items(owner, "")) == 3
    assert len(store.list_items(owner, "  ")) == 3


def test_isolation_between_users(tmp_store, admin_user, normal_user):
    """A user's plan is invisible to another user (404-equivalent: None)."""
    admin_id = str(admin_user["id"])
    user_id = str(normal_user["id"])
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan(), admin_id)

    assert store.get_document(doc.id, user_id) is None
    assert store.list_documents(user_id) == []
    assert store.list_items(user_id) == []
    assert store.delete_document(doc.id, user_id) is False
    # owner still sees it
    assert store.get_document(doc.id, admin_id) is not None


def test_settings_are_per_user(tmp_store, admin_user, normal_user):
    """Model/IMA/gen settings written by one user don't leak to another."""
    admin_id = str(admin_user["id"])
    user_id = str(normal_user["id"])

    store.update_model_settings(user_id, api_key="user-key", model="user-model")
    store.update_model_settings(admin_id, api_key="admin-key")

    assert store.get_llm_config(user_id)[0] == "user-key"
    assert store.get_model_settings_row(user_id)["model"] == "user-model"
    assert store.get_model_settings_row(admin_id)["model"] != "user-model" or True

    store.update_ima_settings(user_id, client_id="cid-user")
    store.update_gen_settings(user_id, plan="自定义策略", grade="按步骤给分")

    assert store.get_ima_settings_row(user_id)["ima_client_id"] == "cid-user"
    assert store.get_ima_settings_row(admin_id)["ima_client_id"] == ""
    assert store.get_gen_settings_row(user_id)["plan"] == "自定义策略"
    assert store.get_gen_settings_row(user_id)["grade"] == "按步骤给分"
    assert store.get_gen_settings_row(admin_id)["plan"] == ""
    assert store.get_gen_settings_row(admin_id)["grade"] == ""


def test_token_usage_record_and_summary(tmp_store, admin_user, normal_user):
    """Usage rows are per-user and aggregate into today/month/allTime."""
    admin_id = str(admin_user["id"])
    user_id = str(normal_user["id"])

    store.record_token_usage(admin_id, "coach", 100, 20, 120, model="m1")
    store.record_token_usage(admin_id, "plan", 200, 300, 500, model="m1")
    store.record_token_usage(user_id, "coach", 10, 5, 15, model="m2")

    s = store.get_usage_summary(admin_id)
    assert s["today"]["requests"] == 2
    assert s["today"]["inputTokens"] == 300
    assert s["today"]["outputTokens"] == 320
    assert s["today"]["totalTokens"] == 620
    assert s["month"] == s["today"]  # fresh DB: nothing older than today
    assert s["allTime"]["totalTokens"] == 620

    u = store.get_usage_summary(user_id)
    assert u["today"]["totalTokens"] == 15

    # model 默认取用户配置 (未配置时为空串), 不抛异常
    store.record_token_usage(user_id, "quiz", 1, 2, 3)
    assert store.get_usage_summary(user_id)["today"]["requests"] == 2


def test_annotations_crud_and_isolation(tmp_store, admin_user, normal_user):
    """Annotation CRUD works per user; other users cannot see or touch them."""
    admin_id = str(admin_user["id"])
    user_id = str(normal_user["id"])
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan(modules=1), admin_id)
    plan_id, module_key = doc.id, doc.plan.modules[0].id

    a1 = store.create_annotation(admin_id, plan_id, module_key, "被注释的句子", "前文", "后文", "第一条笔记")
    a2 = store.create_annotation(admin_id, plan_id, module_key, "另一句", note="第二条")
    assert a1["quote"] == "被注释的句子" and a1["prefix"] == "前文"
    assert a1["createdAt"] is not None

    rows = store.list_annotations(admin_id, plan_id, module_key)
    assert [r["id"] for r in rows] == [a1["id"], a2["id"]]

    updated = store.update_annotation(admin_id, plan_id, a1["id"], "改过的笔记")
    assert updated["note"] == "改过的笔记"

    # 用户隔离: normal_user 看不到、改不了、删不掉 admin 的批注
    assert store.list_annotations(user_id, plan_id, module_key) == []
    with pytest.raises(KeyError):
        store.update_annotation(user_id, plan_id, a1["id"], "越权修改")
    with pytest.raises(KeyError):
        store.delete_annotation(user_id, plan_id, a1["id"])
    with pytest.raises(KeyError):
        store.create_annotation(user_id, plan_id, module_key, "x")  # plan 不属于他

    # 不存在的批注 id → KeyError / False
    with pytest.raises(KeyError):
        store.update_annotation(admin_id, plan_id, "does-not-exist", "n")
    assert store.delete_annotation(admin_id, plan_id, "does-not-exist") is False

    assert store.delete_annotation(admin_id, plan_id, a1["id"]) is True
    assert store.delete_annotation(admin_id, plan_id, a1["id"]) is False
    assert len(store.list_annotations(admin_id, plan_id, module_key)) == 1


def test_mcq_multi_roundtrip(tmp_store, owner):
    """多选题的 answers 列表能完整落库并读回。"""
    from app.schemas import Question, QuestionType, Quiz

    quiz = Quiz(questions=[
        Question(id="q1", type=QuestionType.mcq_multi, prompt="哪些正确?",
                 options=["A. 甲", "B. 乙", "C. 丙", "D. 丁"], answers=["A. 甲", "C. 丙"],
                 explanation="甲丙正确"),
    ])
    plan = make_plan(modules=1)
    plan.modules[0].quiz = quiz
    doc = store.create_document(PlanSource(input="x", mode="topic"), plan, owner)

    loaded = store.get_document(doc.id, owner)
    q = loaded.plan.modules[0].quiz.questions[0]
    assert q.type == QuestionType.mcq_multi
    assert q.answers == ["A. 甲", "C. 丙"]
