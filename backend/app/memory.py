"""Temporary in-session memory for the coach chat.

The coach endpoint is stateless on purpose: the client owns the current
conversation (``localStorage`` in the web UI) and resends the prior turns in
``CoachRequest.history`` on every call. This module shapes that list into a
bounded ``messages`` prefix so the chat agent can "remember" the current dialog
without any server-side state.

Bounding strategy -- the same idea as LangChain's
``ConversationSummaryBufferMemory`` (and the lower-level
``langchain_core.messages.utils.trim_messages``), but implemented explicitly so
it stays easy to test and has no extra dependencies:

1. 剪裁 (trim): keep the newest turns verbatim within a per-message character
   cap and a total budget. The oldest turns are trimmed first and the window is
   always adjusted to start on a user turn (no orphan assistant reply).
2. 压缩 (compress): turns trimmed off the front are condensed into a short LLM
   summary (``summarize_turns``). If summarisation is disabled or the model
   call fails, a one-line note is used instead -- context is never silently
   lost and the chat never breaks.

The pure helpers below are deliberately dependency-free; the LangGraph/LangChain
wiring happens in ``agent.LearningCoach._build_coach_messages``.
"""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .schemas import ChatTurn

logger = logging.getLogger(__name__)

# --- budgets ---------------------------------------------------------------

MAX_MESSAGES = 16            # newest messages kept verbatim
MAX_MESSAGE_CHARS = 1200     # per-message cap (tail kept, marked)
MAX_WINDOW_CHARS = 6000      # total budget for the verbatim window
MAX_SUMMARY_CHARS = 400      # budget for the compressed prefix
MAX_SUMMARY_INPUT_CHARS = 6000  # budget for the transcript sent to the summarizer

ENABLE_SUMMARIZATION = True

_SUMMARY_SYSTEM = (
    "你是对话记忆压缩助手。请把下面这段按时间顺序的对话压缩成一段简短摘要，"
    "保留关键事实、用户目标、已讨论的结论与尚未完成的事项，省略寒暄和重复内容。"
    "直接输出摘要正文，不要添加解释。"
)


def _message_text(content: object) -> str:
    """Robustly extract plain text from an AIMessage ``content`` field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def _normalize(history: list[ChatTurn]) -> list[tuple[str, str]]:
    """Filter + cap each turn; return chronological ``(role, content)`` pairs."""
    turns: list[tuple[str, str]] = []
    for t in history:
        content = (t.content or "").strip()
        if not content:
            continue
        if len(content) > MAX_MESSAGE_CHARS:
            content = "……" + content[-MAX_MESSAGE_CHARS:]
        turns.append(("assistant" if t.role == "assistant" else "user", content))
    return turns


def trim_history(
    history: list[ChatTurn],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return ``(kept, dropped)``, both in chronological order.

    ``kept`` is the recent verbatim window; ``dropped`` holds the older turns
    that should be compressed into a summary.
    """
    turns = _normalize(history)
    if not turns:
        return [], []

    n = min(len(turns), MAX_MESSAGES)
    dropped = turns[:-n] if n < len(turns) else []
    kept = turns[-n:]

    def _chars(items: list[tuple[str, str]]) -> int:
        return sum(len(c) for _, c in items)

    while kept and _chars(kept) > MAX_WINDOW_CHARS:
        dropped.append(kept.pop(0))

    # The visible window must start with a user turn, not an orphan reply.
    while kept and kept[0][0] != "user":
        dropped.append(kept.pop(0))

    return kept, dropped


def _to_transcript(turns: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for role, content in turns:
        label = "助手" if role == "assistant" else "用户"
        parts.append(f"{label}: {content}")
    return "\n".join(parts)


def build_messages_from(
    kept: list[tuple[str, str]],
    dropped: list[tuple[str, str]],
    summary: str | None = None,
) -> list:
    """Assemble the LangChain message prefix from already-trimmed turns.

    Prepends a compressed summary (or a one-line note) when turns were trimmed,
    then the verbatim recent window. The caller appends the new user ``goal``.
    """
    messages: list = []

    if dropped:
        if summary and summary.strip():
            messages.append(HumanMessage(content=f"[更早对话摘要] {summary.strip()}"))
        else:
            messages.append(HumanMessage(
                content=(
                    f"[对话记忆说明：为控制长度，本次对话较早的 {len(dropped)} 条消息已省略，"
                    "以下为最近的对话内容。]"
                )
            ))
        messages.append(AIMessage(content="好的，已了解以上对话背景。"))

    for role, content in kept:
        messages.append(
            AIMessage(content=content) if role == "assistant"
            else HumanMessage(content=content)
        )
    return messages


def build_messages(history: list[ChatTurn], summary: str | None = None) -> list:
    """Assemble the LangChain message prefix for ``history``.

    Convenience wrapper around :func:`trim_history` + :func:`build_messages_from`
    for callers that do not need the intermediate ``(kept, dropped)`` split.
    """
    kept, dropped = trim_history(history)
    return build_messages_from(kept, dropped, summary)


async def summarize_turns(model: BaseChatModel, dropped: list[tuple[str, str]]) -> str:
    """Compress trimmed turns into a short summary via the LLM."""
    transcript = _to_transcript(dropped)
    if len(transcript) > MAX_SUMMARY_INPUT_CHARS:
        transcript = transcript[:MAX_SUMMARY_INPUT_CHARS] + "……"

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("llm_request memory payload:\n[system] %s\n[human] %s", _SUMMARY_SYSTEM, transcript)
    else:
        logger.info("llm_request memory: chars=%d (设置 LOG_LEVEL=DEBUG 可见全文)", len(transcript))

    response = await model.ainvoke(
        [SystemMessage(content=_SUMMARY_SYSTEM), HumanMessage(content=transcript)]
    )
    text = _message_text(response.content).strip()
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[:MAX_SUMMARY_CHARS] + "……"
    return text
