"""Agent orchestration logic with mocked LLM graphs (spec sec 8).

Mocks at the DeepAgents graph boundary so make_plan / make_quiz / grade_quiz /
author_content_stream run their real normalization & persistence logic.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import agent as agent_mod
from app.agent import LearningCoach, _split_key_takeaways
from app.schemas import (
    Assessment,
    Content,
    GradingResult,
    Level,
    Module,
    ModuleStatus,
    Plan,
    PlanSource,
    Question,
    QuestionResult,
    QuestionType,
    Quiz,
)

from _factories import make_plan, make_quiz, make_result


class FakeGraph:
    """Mimics a DeepAgents compiled graph: invoke -> {"structured_response": ...}."""

    def __init__(self, response, fail_first: bool = False):
        self.response = response
        self.fail_first = fail_first
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("simulated LLM failure")
        return {"structured_response": self.response}


class FakeStreamModel:
    def __init__(self, chunks):
        self.chunks = chunks

    async def astream(self, messages):
        for c in self.chunks:
            yield SimpleNamespace(content=c)


def coach_with(planner=None, quizzer=None, grader=None):
    coach = LearningCoach()
    graphs = {
        "planner": planner or FakeGraph(make_plan()),
        "quizzer": quizzer or FakeGraph(make_quiz()),
        "grader": grader or FakeGraph(make_result()),
        "content": FakeGraph(None),
        "supervisor": FakeGraph(None),
    }
    coach._build = lambda: graphs  # type: ignore[method-assign]
    return coach, graphs


# ----- make_plan -----

def test_make_plan_normalizes_module_ids():
    raw = Plan(
        title="P",
        goal="g",
        level=Level.beginner,
        totalMinutes=0,
        modules=[
            Module(id="", title="A", summary="s", minutes=10),
            Module(id="", title="B", summary="s", minutes=20),
        ],
    )
    coach, _ = coach_with(planner=FakeGraph(raw))
    plan = coach.make_plan(PlanSource(input="x", mode="topic"))
    assert [m.id for m in plan.modules] == ["m1", "m2"]
    assert all(m.status == ModuleStatus.not_started for m in plan.modules)
    assert all(m.content is None and m.quiz is None and m.result is None and m.answers is None for m in plan.modules)


def test_make_plan_sums_total_minutes_when_zero():
    raw = Plan(
        title="P",
        goal="g",
        level=Level.beginner,
        totalMinutes=0,
        modules=[
            Module(id="", title="A", summary="s", minutes=10),
            Module(id="", title="B", summary="s", minutes=25),
        ],
    )
    coach, _ = coach_with(planner=FakeGraph(raw))
    assert coach.make_plan(PlanSource(input="x", mode="topic")).totalMinutes == 35


def test_make_plan_keeps_nonzero_total_minutes():
    raw = make_plan(modules=2, total_minutes=60)
    coach, _ = coach_with(planner=FakeGraph(raw))
    assert coach.make_plan(PlanSource(input="x", mode="topic")).totalMinutes == 60


# ----- make_quiz -----

def test_make_quiz_normalizes_question_ids():
    raw = Quiz(
        questions=[
            Question(id="", type=QuestionType.mcq, prompt="p1", options=["a", "b"], answer="a"),
            Question(id="", type=QuestionType.short, prompt="p2", modelAnswer="ma"),
        ]
    )
    coach, _ = coach_with(quizzer=FakeGraph(raw))
    plan = make_plan(modules=1)
    quiz = coach.make_quiz(plan, plan.modules[0])
    assert [q.id for q in quiz.questions] == ["q1", "q2"]


# ----- grade_quiz -----

def test_grade_quiz_writes_student_answers_and_maxscore_fallback():
    plan = make_plan(modules=1)
    module = plan.modules[0]
    module.quiz = make_quiz()
    raw = GradingResult(
        results=[
            QuestionResult(questionId="q1", score=1, maxScore=1, correct=True, feedback="ok"),
            QuestionResult(questionId="q2", score=0, maxScore=1, correct=False, feedback="no"),
        ],
        totalScore=1.0,
        maxScore=0.0,
        assessment=Assessment(level=Level.intermediate),
    )
    coach, _ = coach_with(grader=FakeGraph(raw))
    answers = {"q1": "2", "q2": "a callable wrapping a function"}
    result = coach.grade_quiz(plan, module, answers)
    assert result.maxScore == 2.0  # fell back to len(questions)
    assert result.results[0].studentAnswer == "2"
    assert result.results[1].studentAnswer == "a callable wrapping a function"


# ----- retry -----

def test_invoke_structured_retries_once():
    raw = make_quiz()
    g = FakeGraph(raw, fail_first=True)
    coach, _ = coach_with(quizzer=g)
    plan = make_plan(modules=1)
    quiz = coach.make_quiz(plan, plan.modules[0])
    assert quiz is raw
    assert g.calls == 2


# ----- content streaming -----

def test_split_key_takeaways_parses_points():
    text = "body text\n\n## " + "\u5173\u952e\u8981\u70b9" + "\n- a\n- b\n2. c\n"
    body, points = _split_key_takeaways(text)
    assert body == "body text"
    assert points == ["a", "b", "c"]


def test_split_key_takeaways_no_heading():
    body, points = _split_key_takeaways("only body")
    assert body == "only body"
    assert points == []


def test_author_content_stream_splits_key_takeaways(monkeypatch):
    heading = "## " + "\u5173\u952e\u8981\u70b9"
    chunks = ["# module\n\nbody\n\n", heading + "\n", "- point one\n", "- point two\n"]
    monkeypatch.setattr(agent_mod, "build_streaming_model", lambda **kw: FakeStreamModel(chunks))
    coach, _ = coach_with()
    plan = make_plan(modules=1)
    module = plan.modules[0]

    async def collect():
        out = []
        async for kind, payload in coach.author_content_stream(plan, module):
            out.append((kind, payload))
        return out

    events = asyncio.run(collect())
    deltas = [p for k, p in events if k == "delta"]
    done = [p for k, p in events if k == "done"]
    assert "".join(deltas) == "".join(chunks)
    assert len(done) == 1
    content: Content = done[0]
    assert isinstance(content, Content)
    assert "\u5173\u952e\u8981\u70b9" not in content.markdown
    assert content.keyTakeaways == ["point one", "point two"]


# ----- math notation in prompts -----

def test_system_prompts_require_latex_math():
    """feedback/assessment formulas must use $...$ LaTeX so they render as
    typeset math on the results page, not plain text like "F浮=G-F"
    (bug: 批改结果总结栏/反馈里的公式显示异常)."""
    for prompt in (agent_mod.QUIZ_SYSTEM, agent_mod.GRADER_SYSTEM, agent_mod.CONTENT_SYSTEM):
        assert "$...$" in prompt, "prompt must require $...$ inline math delimiters"
        # LaTeX backslashes must stay literal (not escape-processed into CR/tab)
        assert r"\rho" in prompt, "prompt must include \\rho with a literal backslash"
        assert r"\text" in prompt, "prompt must include \\text with a literal backslash"
