"""Shared test factories for preset Pydantic objects (spec sec 8: mock LLM)."""
from __future__ import annotations

from app.schemas import (
    Assessment,
    Content,
    GradingResult,
    Level,
    Module,
    ModuleStatus,
    Plan,
    Question,
    QuestionResult,
    QuestionType,
    Quiz,
)


def make_module(id: str = "m1", title: str = "module-one", status: ModuleStatus = ModuleStatus.not_started) -> Module:
    return Module(
        id=id,
        title=title,
        summary="module summary",
        objectives=["objective A", "objective B"],
        minutes=30,
        status=status,
    )


def make_plan(title: str = "test-plan", modules: int = 2, total_minutes: int = 60) -> Plan:
    return Plan(
        title=title,
        goal="learn the topic",
        summary="plan summary",
        level=Level.intermediate,
        totalMinutes=total_minutes,
        modules=[make_module(f"m{i+1}", f"module-{i+1}") for i in range(modules)],
    )


def make_quiz() -> Quiz:
    return Quiz(
        questions=[
            Question(
                id="q1",
                type=QuestionType.mcq,
                prompt="1+1=?",
                options=["1", "2", "3"],
                answer="2",
                explanation="addition",
            ),
            Question(
                id="q2",
                type=QuestionType.short,
                prompt="describe a decorator",
                modelAnswer="a callable wrapping a function",
                keyPoints=["callable object", "does not change source"],
                explanation="concept",
            ),
        ]
    )


def make_result() -> GradingResult:
    return GradingResult(
        results=[
            QuestionResult(questionId="q1", score=1, maxScore=1, correct=True, feedback="correct"),
            QuestionResult(questionId="q2", score=0.5, maxScore=1, correct=False, feedback="partial"),
        ],
        totalScore=1.5,
        maxScore=2.0,
        assessment=Assessment(
            strengths=["basic concept"],
            weaknesses=["detail"],
            recommendations=["practice more"],
            level=Level.intermediate,
        ),
    )


def make_content() -> Content:
    return Content(markdown="# heading\n\nbody paragraph", keyTakeaways=["point one", "point two"])
