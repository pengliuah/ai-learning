"""邀请制注册: 邀请码生成/核销/过期/用尽/作废/重名回滚。"""
from __future__ import annotations

import pytest

from app import store


def _mk_invite(admin_user, **kw) -> dict:
    return store.create_invite(str(admin_user["id"]), **kw)


def _register(client, username: str, code: str, password: str = "secret123"):
    return client.post("/api/auth/register", json={
        "username": username, "password": password, "invite_code": code,
    })


def test_register_with_valid_invite(client, admin_user):
    inv = _mk_invite(admin_user)
    r = _register(client, "新学员", inv["code"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["username"] == "新学员"
    assert body["user"]["role"] == "user"
    assert body["access_token"] and body["refresh_token"]
    # 凭注册得到的 token 能访问需要登录的接口
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


def test_register_invalid_or_exhausted_code(client, admin_user):
    assert _register(client, "u1", "WRONGCOD").status_code == 400
    # 用尽: max_uses=1 的码注册第二次失败
    inv = _mk_invite(admin_user, max_uses=1)
    assert _register(client, "u2", inv["code"]).status_code == 200
    assert _register(client, "u3", inv["code"]).status_code == 400
    # 大小写不敏感: 换一个新码, 小写提交也能用
    inv2 = _mk_invite(admin_user, max_uses=1)
    assert _register(client, "u4", inv2["code"].lower()).status_code == 200


def test_register_expired_code(client, admin_user, tmp_store):
    from app.db import db_conn

    inv = _mk_invite(admin_user)
    with db_conn() as conn:
        conn.execute("UPDATE invite_codes SET expires_at = now() - interval '1 day' WHERE code = %s", (inv["code"],))
    assert _register(client, "u5", inv["code"]).status_code == 400


def test_register_disabled_code(client, admin_user):
    inv = _mk_invite(admin_user)
    assert store.disable_invite(inv["id"]) is True
    assert _register(client, "u6", inv["code"]).status_code == 400
    # 作废幂等: 再作废返回 False
    assert store.disable_invite(inv["id"]) is False


def test_register_duplicate_username_does_not_burn_code(client, admin_user):
    """用户名冲突不消耗邀请码（先查重名, 后核销; 极端并发走回滚）。"""
    inv = _mk_invite(admin_user, max_uses=5)
    _register(client, "张三", inv["code"])
    before = {i["id"]: i for i in store.list_invites()}
    r = _register(client, "张三", inv["code"])
    assert r.status_code == 409
    after = {i["id"]: i for i in store.list_invites()}
    assert after[inv["id"]]["used_count"] == before[inv["id"]]["used_count"]


def test_invite_atomic_exhaustion(tmp_store, admin_user):
    """store 层核销: 用尽后 consume 返回 None。"""
    inv = _mk_invite(admin_user, max_uses=2)
    assert store.consume_invite(inv["code"]) is not None
    assert store.consume_invite(inv["code"]) is not None
    assert store.consume_invite(inv["code"]) is None
    assert store.consume_invite("") is None


def test_admin_invite_endpoints(client, admin_user):
    # 生成
    r = client.post("/api/admin/invites", json={"max_uses": 3, "expires_days": 7, "note": "给王同学"})
    assert r.status_code == 200
    inv = r.json()
    assert len(inv["code"]) == 8
    assert inv["maxUses"] == 3 and inv["note"] == "给王同学"
    # 列表可见
    codes = [i["code"] for i in client.get("/api/admin/invites").json()]
    assert inv["code"] in codes
    # 作废后注册被拒
    d = client.put(f"/api/admin/invites/{inv['id']}/disable")
    assert d.status_code == 200
    assert _register(client, "u7", inv["code"]).status_code == 400
    # 再作废 → 404（幂等保护）
    assert client.put(f"/api/admin/invites/{inv['id']}/disable").status_code == 404
