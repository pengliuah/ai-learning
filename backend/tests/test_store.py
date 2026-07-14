"""Store CRUD coverage (spec sec 8): create/get/list/delete/update + progress."""
from __future__ import annotations

import pytest

from app import store
from app.schemas import ModuleStatus, PlanSource

from _factories import make_plan


def test_create_and_get(tmp_store):
    doc = store.create_document(PlanSource(input="topic", mode="topic"), make_plan(modules=2))
    assert doc.id
    fetched = store.get_document(doc.id)
    assert fetched is not None
    assert fetched.plan.title == "test-plan"
    assert len(fetched.plan.modules) == 2


def test_get_unknown_returns_none(tmp_store):
    assert store.get_document("does-not-exist") is None


def test_list_documents_empty(tmp_store):
    assert store.list_documents() == []


def test_list_items_progress(tmp_store):
    plan = make_plan(modules=4)
    plan.modules[0].status = ModuleStatus.completed
    plan.modules[1].status = ModuleStatus.completed
    store.create_document(PlanSource(input="x", mode="topic"), plan)
    items = store.list_items()
    assert len(items) == 1
    assert items[0].progress == 0.5
    assert items[0].title == "test-plan"


def test_delete(tmp_store):
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan())
    assert store.delete_document(doc.id) is True
    assert store.get_document(doc.id) is None
    assert store.delete_document(doc.id) is False


def test_update_module(tmp_store):
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan(modules=2))
    mid = doc.plan.modules[1].id

    def mutate(m):
        m.status = ModuleStatus.completed

    updated = store.update_module(doc.id, mid, mutate)
    assert updated.plan.modules[1].status == ModuleStatus.completed
    assert updated.plan.modules[0].status == ModuleStatus.not_started
    assert updated.updatedAt >= doc.updatedAt
    # persisted to disk
    assert store.get_document(doc.id).plan.modules[1].status == ModuleStatus.completed


def test_update_module_missing_raises(tmp_store):
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan())
    with pytest.raises(KeyError):
        store.update_module(doc.id, "missing-module", lambda m: None)
    with pytest.raises(KeyError):
        store.update_module("missing-plan", doc.plan.modules[0].id, lambda m: None)


def test_persistence_round_trip(tmp_store):
    doc = store.create_document(PlanSource(input="x", mode="topic"), make_plan(modules=1))
    docs = store.list_documents()
    assert len(docs) == 1
    assert docs[0].id == doc.id
