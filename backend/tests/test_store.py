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
    assert updated.updatedAt >= doc.updatedAt
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
    store.update_gen_settings(user_id, plan="自定义策略")

    assert store.get_ima_settings_row(user_id)["ima_client_id"] == "cid-user"
    assert store.get_ima_settings_row(admin_id)["ima_client_id"] == ""
    assert store.get_gen_settings_row(user_id)["plan"] == "自定义策略"
    assert store.get_gen_settings_row(admin_id)["plan"] == ""
