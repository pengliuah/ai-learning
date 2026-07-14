"""Schema validation (spec sec 8): defaults, enum rejection, round-trip."""
from __future__ import annotations

import datetime

import pytest

from app.schemas import (
    AnswersState,
    Document,
    GradingResult,
    Level,
    Module,
    ModuleStatus,
    Plan,
    PlanSource,
    Question,
    QuestionType,
    SaveAnswersRequest,
)

from _factories import make_plan, make_quiz, make_result


def test_module_defaults():
    m = Module(id="m1", title="t", summary="s")
    assert m.status == ModuleStatus.not_started
    assert m.content is None and m.quiz is None and m.result is None and m.answers is None


def test_question_defaults():
    q = Question(id="q1", type=QuestionType.mcq, prompt="p")
    assert q.options == [] and q.answer is None and q.explanation == ""


def test_question_type_invalid_rejected():
    with pytest.raises(ValueError):
        Question(id="q1", type="not-a-real-type", prompt="p")


def test_module_status_invalid_rejected():
    with pytest.raises(ValueError):
        ModuleStatus("finished")


def test_answers_state_defaults():
    a = AnswersState()
    assert a.answers == {} and a.answered == 0 and a.total == 0


def test_save_answers_request():
    r = SaveAnswersRequest(answers={"q1": "2"})
    assert r.answers == {"q1": "2"}


def test_grading_result_defaults():
    g = GradingResult()
    assert g.totalScore == 0.0 and g.maxScore == 0.0
    assert g.assessment.level == Level.intermediate


def test_document_round_trip():
    plan = make_plan(modules=2)
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    doc = Document(id="d1", createdAt=now, updatedAt=now, source=PlanSource(input="x", mode="topic"), plan=plan)
    dumped = doc.model_dump(mode="json")
    back = Document.model_validate(dumped)
    assert back.id == "d1"
    assert back.plan.modules[1].id == "m2"
    assert back.source.mode == "topic"


def test_plan_source_mode_invalid_rejected():
    with pytest.raises(ValueError):
        PlanSource(input="x", mode="bogus")


def test_factories_valid():
    assert len(make_quiz().questions) == 2
    assert make_result().maxScore == 2.0
