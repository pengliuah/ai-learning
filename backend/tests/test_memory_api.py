"""HTTP tests for long-term memory management APIs (P2).

Mem0 is stubbed at the long_memory layer so these stay offline.
"""
from __future__ import annotations

from app import long_memory, memory_client, store
from app.auth import create_access_token


class _FakeMemory:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.items = {
            "m1": {
                "id": "m1",
                "memory": "学生喜欢天文",
                "user_id": user_id,
                "created_at": "2026-09-01T00:00:00Z",
                "updated_at": None,
            }
        }

    def get_all(self, **kwargs):
        return {"results": list(self.items.values())}

    def get(self, memory_id):
        return self.items.get(memory_id)

    def delete(self, memory_id):
        self.items.pop(memory_id, None)
        return {"message": "ok"}

    def search(self, *a, **k):
        return {"results": []}

    def add(self, *a, **k):
        pass

    def close(self):
        pass


class _StubCache:
    def __init__(self, instance):
        self.instance = instance

    def get_or_build(self, user_id):
        return self.instance

    def clear(self):
        self.instance = None


def _configure(admin_user) -> str:
    user_id = str(admin_user["id"])
    store.update_model_settings(
        user_id,
        api_key="sk-test",
        model="test-chat-model",
        base_url="http://localhost:9/v1",
        embedding_model="test-embedding",
        embedding_base_url="http://localhost:9/v1",
        embedding_api_key="sk-emb",
    )
    return user_id


def test_memory_settings_default_and_toggle(client, admin_user):
    r = client.get("/api/settings/memory")
    assert r.status_code == 200
    assert r.json() == {"enabled": True}

    r = client.put("/api/settings/memory", json={"enabled": False})
    assert r.status_code == 200
    assert r.json() == {"enabled": False}
    assert client.get("/api/settings/memory").json()["enabled"] is False

    r = client.put("/api/settings/memory", json={"enabled": True})
    assert r.json()["enabled"] is True


def test_list_and_delete_memories(client, admin_user, tmp_store):
    user_id = _configure(admin_user)
    fake = _FakeMemory(user_id)
    original = memory_client._cache
    memory_client._cache = _StubCache(fake)
    try:
        r = client.get("/api/memories")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["id"] == "m1"
        assert body[0]["memory"] == "学生喜欢天文"

        r = client.delete("/api/memories/m1")
        assert r.status_code == 200
        assert r.json() == {"deleted": "m1"}
        assert client.get("/api/memories").json() == []

        r = client.delete("/api/memories/m1")
        assert r.status_code == 404
    finally:
        memory_client._cache = original


def test_delete_rejects_other_users_memory(client, admin_user, normal_user, tmp_store):
    """删除时校验 user_id，不能删别人的记忆。"""
    admin_id = _configure(admin_user)
    user_id = str(normal_user["id"])
    store.update_model_settings(
        user_id,
        api_key="sk-u",
        model="m",
        base_url="http://localhost:9/v1",
        embedding_model="emb",
        embedding_base_url="http://localhost:9/v1",
        embedding_api_key="sk-e",
    )

    fake = _FakeMemory(admin_id)
    original = memory_client._cache
    memory_client._cache = _StubCache(fake)
    try:
        uh = {"Authorization": f"Bearer {create_access_token(normal_user)}"}
        r = client.delete("/api/memories/m1", headers=uh)
        assert r.status_code == 404
        assert "m1" in fake.items
    finally:
        memory_client._cache = original
