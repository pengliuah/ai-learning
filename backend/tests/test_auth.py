"""Auth & admin coverage: login, token refresh/rotation, logout, isolation,
user management, per-user settings.

The LLM is mocked (fake_coach); the store is isolated per test (tmp_store).
"""
from __future__ import annotations

import pytest

from _factories import make_plan


@pytest.fixture
def admin_credentials(admin_user):
    return {"username": "admin", "password": "adminpw"}


@pytest.fixture
def user_credentials(normal_user):
    return {"username": "user1", "password": "userpw"}


def _login(client, creds):
    return client.post("/api/auth/login", json=creds)


# ----- login -----

def test_login_ok(client, admin_credentials):
    r = _login(client, admin_credentials)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["role"] == "admin"
    assert "password_hash" not in body["user"]
    assert "password" not in body["user"]


def test_login_wrong_password(client, admin_credentials):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user(client):
    r = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401


# ----- protected endpoints -----

def test_plans_require_auth(client):
    # No token -> 401
    assert client.get("/api/plans", headers={"Authorization": ""}).status_code in (401, 403)
    # Garbage token -> 401
    r = client.get("/api/plans", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_me_endpoint(client, admin_credentials):
    r = _login(client, admin_credentials)
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


# ----- refresh rotation -----

def test_refresh_rotates_tokens(client, admin_credentials):
    login = _login(client, admin_credentials).json()
    r = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    # The refreshed pair keeps working (rotation chain).
    r2 = client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r2.status_code == 200


def test_replayed_refresh_token_revokes_everything(client, admin_credentials):
    """Replaying a rotated refresh token revokes every token of the user
    (stolen-token leak response)."""
    login = _login(client, admin_credentials).json()
    fresh = client.post(
        "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
    ).json()
    # Chain still valid before the replay.
    r3 = client.post("/api/auth/refresh", json={"refresh_token": fresh["refresh_token"]})
    assert r3.status_code == 200
    # Replay the original (now revoked) token -> 401 and ...
    r4 = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r4.status_code == 401
    # ... the whole chain is now revoked, including a previously valid token.
    r5 = client.post(
        "/api/auth/refresh",
        json={"refresh_token": r3.json()["refresh_token"]},
    )
    assert r5.status_code == 401


def test_logout_revokes_refresh_token(client, admin_credentials):
    login = _login(client, admin_credentials).json()
    r = client.post("/api/auth/logout", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200
    r2 = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r2.status_code == 401


# ----- data isolation between users -----

def test_user_cannot_see_admin_plans(client, admin_user, normal_user, user_credentials, fake_coach):
    fake_coach.plan = make_plan(modules=1)
    admin_login = _login(client, {"username": "admin", "password": "adminpw"}).json()
    admin_token = admin_login["access_token"]
    doc = client.post("/api/plans", json={"input": "x", "mode": "topic"}).json()

    user_login = _login(client, user_credentials).json()
    user_token = user_login["access_token"]
    uh = {"Authorization": f"Bearer {user_token}"}

    assert client.get(f"/api/plans/{doc['id']}", headers=uh).status_code == 404
    assert client.get("/api/plans", headers=uh).json() == []
    assert client.delete(f"/api/plans/{doc['id']}", headers=uh).status_code == 404

    # Sanity: admin still sees it
    ah = {"Authorization": f"Bearer {admin_token}"}
    assert client.get(f"/api/plans/{doc['id']}", headers=ah).status_code == 200


def test_settings_isolated_between_users(client, admin_user, normal_user, user_credentials):
    ah = client.headers.get("Authorization")
    admin_client_token = ah.split(" ", 1)[1]
    user_login = _login(client, user_credentials).json()
    uh = {"Authorization": f"Bearer {user_login['access_token']}"}

    # A user with nothing saved sees empty values, NOT env-var fallbacks.
    fresh = client.get("/api/settings/model", headers=uh).json()
    assert fresh["apiKey"] == ""
    assert fresh["model"] == ""

    # Each user writes their own model settings.
    r_user = client.put(
        "/api/settings/model",
        json={"apiKey": "user-key", "model": "user-model"},
        headers=uh,
    )
    assert r_user.status_code == 200
    r_admin = client.put("/api/settings/model", json={"apiKey": "admin-key"})
    assert r_admin.status_code == 200

    assert client.get("/api/settings/model", headers=uh).json()["apiKey"] == "user-key"
    assert client.get("/api/settings/model").json()["apiKey"] == "admin-key"


# ----- change password -----

def test_change_password(client, admin_credentials):
    login = _login(client, admin_credentials).json()
    h = {"Authorization": f"Bearer {login['access_token']}"}
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "adminpw", "new_password": "newpass1"},
        headers=h,
    )
    assert r.status_code == 200
    # Old password no longer logs in; new one does.
    assert _login(client, admin_credentials).status_code == 401
    assert _login(client, {"username": "admin", "password": "newpass1"}).status_code == 200
    # All refresh tokens were revoked by the password change.
    r2 = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r2.status_code == 401


def test_change_password_wrong_old(client, admin_credentials):
    login = _login(client, admin_credentials).json()
    h = {"Authorization": f"Bearer {login['access_token']}"}
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "nope", "new_password": "newpass1"},
        headers=h,
    )
    assert r.status_code == 400


# ----- admin user management -----

def test_admin_endpoints_require_admin(client, user_credentials):
    user_login = _login(client, user_credentials).json()
    uh = {"Authorization": f"Bearer {user_login['access_token']}"}
    assert client.get("/api/admin/users", headers=uh).status_code == 403
    assert client.post("/api/admin/users", json={"username": "xy", "password": "123456"}, headers=uh).status_code == 403


def test_admin_lists_and_creates_users(client):
    r = client.post("/api/admin/users", json={"username": "alice", "password": "secret1"})
    assert r.status_code == 200
    assert r.json()["role"] == "user"

    users = client.get("/api/admin/users").json()
    names = {u["username"] for u in users}
    assert {"admin", "alice"} <= names


def test_admin_create_duplicate_username_409(client):
    r = client.post("/api/admin/users", json={"username": "admin", "password": "secret1"})
    assert r.status_code == 409


def test_admin_cannot_delete_self(client, admin_user):
    r = client.delete(f"/api/admin/users/{admin_user['id']}")
    assert r.status_code == 400


def test_admin_deletes_user_and_their_data(client, admin_user, normal_user, user_credentials, fake_coach):
    """Deleting a user cascades their plans and blocks their tokens."""
    user_login = _login(client, user_credentials).json()
    uh = {"Authorization": f"Bearer {user_login['access_token']}"}
    fake_coach.plan = make_plan(modules=1)
    doc = client.post("/api/plans", json={"input": "x", "mode": "topic"}, headers=uh).json()
    assert doc["id"]

    r = client.delete(f"/api/admin/users/{normal_user['id']}")
    assert r.status_code == 200
    # Plan cascaded away; user can no longer authenticate.
    assert client.get(f"/api/plans/{doc['id']}", headers=uh).status_code == 401
    assert _login(client, user_credentials).status_code == 401


def test_admin_reset_password(client, normal_user, user_credentials):
    r = client.post(f"/api/admin/users/{normal_user['id']}/reset-password", json={"new_password": "resetpw1"})
    assert r.status_code == 200
    assert _login(client, user_credentials).status_code == 401
    assert _login(client, {"username": "user1", "password": "resetpw1"}).status_code == 200
