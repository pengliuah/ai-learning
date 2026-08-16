"""Temporary in-session conversation memory: trimming + compression."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app import memory
from app.schemas import ChatTurn


def turn(role: str, content: str) -> ChatTurn:
    return ChatTurn(role=role, content=content)


def test_normalize_filters_empty_and_maps_roles():
    turns = [turn("user", "   "), turn("assistant", "hello"), turn("user", "hi")]
    assert memory._normalize(turns) == [("assistant", "hello"), ("user", "hi")]


def test_normalize_caps_long_messages_keeping_tail():
    long = "x" * (memory.MAX_MESSAGE_CHARS + 50)
    out = memory._normalize([turn("user", long)])
    assert out[0][0] == "user"
    assert out[0][1].startswith("……")
    assert out[0][1].endswith("x" * 50)


def test_trim_history_keeps_recent_window(monkeypatch):
    monkeypatch.setattr(memory, "MAX_MESSAGES", 3)
    history = [
        turn("user", "u0"),
        turn("assistant", "a0"),
        turn("user", "u1"),
        turn("assistant", "a1"),
        turn("user", "u2"),
    ]
    kept, dropped = memory.trim_history(history)
    assert kept == [("user", "u1"), ("assistant", "a1"), ("user", "u2")]
    assert dropped == [("user", "u0"), ("assistant", "a0")]


def test_trim_history_starts_on_user_turn(monkeypatch):
    monkeypatch.setattr(memory, "MAX_MESSAGES", 3)
    history = [
        turn("user", "u0"),
        turn("assistant", "a0"),
        turn("user", "u1"),
        turn("assistant", "a1"),
    ]
    kept, dropped = memory.trim_history(history)
    assert kept == [("user", "u1"), ("assistant", "a1")]
    assert dropped == [("user", "u0"), ("assistant", "a0")]


def test_trim_history_respects_char_budget():
    big = "x" * 1000
    history = [turn("user", big) for _ in range(30)]
    kept, dropped = memory.trim_history(history)
    assert sum(len(c) for _, c in kept) <= memory.MAX_WINDOW_CHARS
    assert len(dropped) + len(kept) == len(history)


def test_build_messages_no_note_when_within_budget():
    history = [turn("user", "hi"), turn("assistant", "hello")]
    msgs = memory.build_messages(history)
    assert [m.content for m in msgs] == ["hi", "hello"]


def test_build_messages_prepends_note_when_trimmed(monkeypatch):
    monkeypatch.setattr(memory, "MAX_MESSAGES", 2)
    history = [turn("user", "u0"), turn("assistant", "a0"), turn("user", "u1")]
    msgs = memory.build_messages(history)
    assert "记忆说明" in str(msgs[0].content)


def test_build_messages_prepends_summary(monkeypatch):
    monkeypatch.setattr(memory, "MAX_MESSAGES", 1)
    history = [turn("user", "u0"), turn("assistant", "a0")]
    msgs = memory.build_messages(history, summary="用户想学 Python 装饰器")
    assert "更早对话摘要" in str(msgs[0].content)


def test_summarize_turns_invokes_model():
    class FakeModel:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="压缩后的摘要")

    text = asyncio.run(memory.summarize_turns(FakeModel(), [("user", "你好")]))
    assert text == "压缩后的摘要"


def test_summarize_turns_caps_output():
    class FakeModel:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="x" * (memory.MAX_SUMMARY_CHARS + 50))

    text = asyncio.run(memory.summarize_turns(FakeModel(), [("user", "你好")]))
    assert len(text) <= memory.MAX_SUMMARY_CHARS + 2
    assert text.endswith("……")
