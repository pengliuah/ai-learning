"""Pytest fixtures: PG-backed store, fake coach, FastAPI TestClient.

Store-dependent tests use a real PostgreSQL database (the DATABASE_URL from
settings / .env).  Each test gets a clean database via TRUNCATE CASCADE.
If PG is unreachable, store-dependent tests are skipped automatically.
"""
from __future__ import annotations

from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app import db, main, store
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

    def make_plan(self, source: PlanSource) -> Plan:
        assert self.plan is not None, "test must set fake_coach.plan"
        return self.plan

    def make_quiz(self, plan: Plan, module: Module) -> Quiz:
        assert self.quiz is not None, "test must set fake_coach.quiz"
        return self.quiz

    def grade_quiz(self, plan: Plan, module: Module, answers: dict) -> GradingResult:
        self.last_grade_answers = answers
        assert self.result is not None, "test must set fake_coach.result"
        return self.result

    async def author_content_stream(self, plan: Plan, module: Module) -> AsyncIterator:
        yield ("delta", self.content.markdown)
        yield ("done", self.content)


@pytest.fixture
def fake_coach() -> FakeCoach:
    return FakeCoach()


@pytest.fixture
def client(tmp_store, fake_coach, monkeypatch):
    monkeypatch.setattr(main, "coach", fake_coach)
    monkeypatch.setattr(main, "is_configured", lambda: True)
    return TestClient(main.app)


@pytest.fixture
def unconfigured_client(tmp_store, fake_coach, monkeypatch):
    monkeypatch.setattr(main, "coach", fake_coach)
    monkeypatch.setattr(main, "is_configured", lambda: False)
    return TestClient(main.app)


@pytest.fixture
def seeded_doc(tmp_store):
    """A document persisted in the store: 3 modules, first completed."""
    plan = make_plan(modules=3)
    plan.modules[0].status = ModuleStatus.completed
    return store.create_document(PlanSource(input="a topic", mode="topic"), plan)
