"""Pytest fixtures: PG-backed store, fake coach, FastAPI TestClient.

Store-dependent tests use a real PostgreSQL database. For safety the
database name from DATABASE_URL is rewritten to ``zhixue_test`` (see the
guard at the top of this file) -- tests TRUNCATE everything, so they must
never touch the live database. If PG is unreachable, store-dependent tests
are skipped automatically.

Account system: every test starts with a fresh admin (``admin_user``) and an
optional normal user (``normal_user``). The ``client`` fixture carries the
admin's access token as a default Authorization header, so existing
single-user endpoint tests keep working unchanged.
"""
from __future__ import annotations

from typing import AsyncIterator

import os

# --- 数据库安全护栏 (必须先于任何 app 导入执行) -------------------------------
# .env 的 DATABASE_URL 指向测试环境服务器的真实库 (如 192.168.1.184:5432/zhixue),
# 而 tmp_store 夹具会 TRUNCATE 全库 —— 直接用会把线上数据清掉 (2026-09-06 事故:
# 跑一次测试, 账号/模型配置/书签/用量全部丢失)。这里强制把库名改写为
# zhixue_test, 测试永远打不进真实库。逃生阀: ZHIXUE_ALLOW_LIVE_DB_TESTS=1。
from dotenv import load_dotenv

load_dotenv()  # 先把 .env 读进来 (config.py 的 load_dotenv 不会覆盖已有变量)
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url and os.environ.get("ZHIXUE_ALLOW_LIVE_DB_TESTS") != "1":
    _head, _, _dbname = _db_url.rstrip("/").rpartition("/")
    if _dbname != "zhixue_test":
        os.environ["DATABASE_URL"] = f"{_head}/zhixue_test"

import pytest
from fastapi.testclient import TestClient

from app import db, main, store
from app.auth import create_access_token, hash_password
from app.schemas import Content, GradingResult, Module, ModuleStatus, Plan, PlanSource, Quiz

from _factories import make_plan


@pytest.fixture(scope="session")
def pg_available():
    """Check PG availability once for the whole test session."""
    try:
        db.init_schema()
        return True
    except Exception:
        return False


@pytest.fixture
def tmp_store(pg_available):
    """Provide a clean PG database for one test.

    Truncates all tables before and after the test.  If PostgreSQL is not
    available, the test is skipped (not failed).
    """
    if not pg_available:
        pytest.skip("PostgreSQL not available")
    db.truncate_all()
    yield
    try:
        db.truncate_all()
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def _close_pool():
    """Close the connection pool after all tests finish."""
    yield
    db.close_pool()


@pytest.fixture
def admin_user(tmp_store):
    """Fresh admin account (users table was truncated with the store)."""
    return store.create_user("admin", hash_password("adminpw"), role="admin")


@pytest.fixture
def normal_user(tmp_store):
    """Fresh normal (non-admin) account."""
    return store.create_user("user1", hash_password("userpw"), role="user")


def auth_headers(user: dict) -> dict:
    """Authorization header carrying the user's access token."""
    return {"Authorization": f"Bearer {create_access_token(user)}"}


class FakeCoach:
    """Stand-in for LearningCoach returning preset structured results.

    No LLM/Ark call: spec sec 8 mock ("return preset structured JSON").
    """

    def __init__(self) -> None:
        self.plan: Plan | None = None
        self.quiz: Quiz | None = None
        self.result: GradingResult | None = None
        self.content: Content = Content(markdown="# heading\n\nbody paragraph", keyTakeaways=["point one", "point two"])
        self.last_grade_answers: dict | None = None

    def make_plan(self, source: PlanSource, user_id: str = "") -> Plan:
        assert self.plan is not None, "test must set fake_coach.plan"
        return self.plan

    def make_quiz(self, plan: Plan, module: Module, user_id: str = "") -> Quiz:
        assert self.quiz is not None, "test must set fake_coach.quiz"
        return self.quiz

    def grade_quiz(self, plan: Plan, module: Module, answers: dict, user_id: str = "") -> GradingResult:
        self.last_grade_answers = answers
        assert self.result is not None, "test must set fake_coach.result"
        return self.result

    async def author_content_stream(self, plan: Plan, module: Module, user_id: str = "") -> AsyncIterator:
        yield ("delta", self.content.markdown)
        yield ("done", self.content)


@pytest.fixture
def fake_coach() -> FakeCoach:
    return FakeCoach()


@pytest.fixture
def client(tmp_store, fake_coach, admin_user, monkeypatch):
    """TestClient acting as the admin user (default Authorization header)."""
    from app.api import helpers
    monkeypatch.setattr(helpers, "coach", fake_coach)
    monkeypatch.setattr(helpers, "is_configured_for_user", lambda uid: True)
    monkeypatch.setattr(store, "is_llm_configured_for_user", lambda uid: True)
    c = TestClient(main.app)
    c.headers.update(auth_headers(admin_user))
    return c


@pytest.fixture
def unconfigured_client(tmp_store, fake_coach, admin_user, monkeypatch):
    from app.api import helpers
    monkeypatch.setattr(helpers, "coach", fake_coach)
    monkeypatch.setattr(helpers, "is_configured_for_user", lambda uid: False)
    monkeypatch.setattr(store, "is_llm_configured_for_user", lambda uid: False)
    c = TestClient(main.app)
    c.headers.update(auth_headers(admin_user))
    return c


@pytest.fixture
def seeded_doc(admin_user):
    """A document persisted in the store: 3 modules, first completed."""
    plan = make_plan(modules=3)
    plan.modules[0].status = ModuleStatus.completed
    return store.create_document(PlanSource(input="a topic", mode="topic"), plan, str(admin_user["id"]))
