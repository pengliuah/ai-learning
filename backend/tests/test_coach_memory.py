"""Integration tests for the coach's temporary conversation memory.

These cover the full assembly path used by ``/api/coach/stream``:
``LearningCoach._build_coach_messages`` -> ``memory.trim_history`` +
``memory.summarize_turns`` + ``memory.build_messages_from``, proving that the
prior turns (and their compressed summary) actually reach the chat agent.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app import agent as agent_mod
from app import memory as memory_mod
from app.agent import LearningCoach
from app.schemas import ChatTurn


def turn(role: str, content: str) -> ChatTurn:
    return ChatTurn(role=role, content=content)


def run(coro):
    return asyncio.run(coro)


def test_build_coach_messages_keeps_short_history_verbatim(monkeypatch):
    monkeypatch.setattr(memory_mod, "ENABLE_SUMMARIZATION", False)
    coach = LearningCoach()
    history = [
        turn("user", "你好"),
        turn("assistant", "你好！有什么想学的？"),
    ]
    messages = run(coach._build_coach_messages("什么是闭包？", history))
    assert [m.content for m in messages] == [
        "你好",
        "你好！有什么想学的？",
        "什么是闭包？",
    ]
    # No summary/note prefix when nothing was trimmed.
    assert all(not str(m.content).startswith("[") for m in messages)


def test_build_coach_messages_compresses_long_history(monkeypatch):
    monkeypatch.setattr(memory_mod, "MAX_MESSAGES", 2)
    monkeypatch.setattr(memory_mod, "ENABLE_SUMMARIZATION", True)
    monkeypatch.setattr(agent_mod, "build_chat_model", lambda **kw: SimpleNamespace())

    async def fake_summary(model, dropped):
        return "之前聊了 Python 装饰器的学习计划"

    monkeypatch.setattr(memory_mod, "summarize_turns", fake_summary)
    coach = LearningCoach()
    history = [
        turn("user", "帮我制定 Python 装饰器的学习计划"),
        turn("assistant", "好的，我来帮你规划。"),
        turn("user", "第一模块学什么？"),
        turn("assistant", "先理解闭包与高阶函数。"),
    ]
    messages = run(coach._build_coach_messages("继续", history))

    texts = [m.content for m in messages]
    assert "更早对话摘要" in texts[0]
    assert "之前聊了 Python 装饰器的学习计划" in texts[0]
    # Recent window + the new goal are still present verbatim.
    assert texts[-3:] == ["第一模块学什么？", "先理解闭包与高阶函数。", "继续"]


def test_build_coach_messages_summary_failure_falls_back_to_note(monkeypatch):
    monkeypatch.setattr(memory_mod, "MAX_MESSAGES", 2)
    monkeypatch.setattr(memory_mod, "ENABLE_SUMMARIZATION", True)
    monkeypatch.setattr(agent_mod, "build_chat_model", lambda **kw: SimpleNamespace())

    async def boom(model, dropped):
        raise RuntimeError("simulated summarizer failure")

    monkeypatch.setattr(memory_mod, "summarize_turns", boom)
    coach = LearningCoach()
    history = [
        turn("user", "u0"),
        turn("assistant", "a0"),
        turn("user", "u1"),
        turn("assistant", "a1"),
    ]
    messages = run(coach._build_coach_messages("u2", history))
    texts = [m.content for m in messages]
    assert "记忆说明" in texts[0]
    assert texts[-1] == "u2"


def test_build_coach_messages_empty_history_is_just_goal(monkeypatch):
    monkeypatch.setattr(memory_mod, "ENABLE_SUMMARIZATION", False)
    coach = LearningCoach()
    messages = run(coach._build_coach_messages("你好", None))
    assert [m.content for m in messages] == ["你好"]
