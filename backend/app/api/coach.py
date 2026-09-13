from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import long_memory, store
from ..auth import get_current_user
from . import helpers as h

router = APIRouter()
logger = logging.getLogger(__name__)

from ..agent import _friendly_llm_error
from ..schemas import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AnnotationCreate,
    AnnotationOut,
    AnnotationUpdate,
    AnswersState,
    Assessment,
    BookmarkOut,
    ChangePasswordRequest,
    ChatTurn,
    CoachRequest,
    Content,
    ContentUpdate,
    Difficulty,
    Document,
    GenSettings,
    GenSettingsUpdate,
    GradingResult,
    ImaArchiveRequest,
    ImaSettings,
    ImaSettingsUpdate,
    Level,
    LoginRequest,
    MemoryArchiveRequest,
    MemoryOut,
    MemoryProfileUpdate,
    MemorySettings,
    MemorySettingsUpdate,
    MemoryUpdate,
    ModelSettings,
    ModelSettingsUpdate,
    ModelTestResult,
    Module,
    ModuleStatus,
    ModuleStatusPatch,
    Plan,
    PlanCreateRequest,
    PlanListItem,
    PlanSource,
    PlansOrderUpdate,
    Question,
    QuestionResult,
    QuestionType,
    Quiz,
    RefreshRequest,
    SaveAnswersRequest,
    SaveToImaRequest,
    SaveToImaResponse,
)

@router.post("/api/coach/stream")
async def coach_stream(req: CoachRequest, user: dict = Depends(get_current_user)):
    """智能体全流程辅导（SSE 流式）。

    运行 DeepAgents 学习教练（supervisor，``create_deep_agent`` +
    ``subagents``），由其通过内置 ``task`` 工具自主委派给子代理
    （planner / content_author / quizzer / grader），并把模型 token 与
    工具/子代理事件以 SSE 流式输出。适合「给定目标，自主规划并产出」的
    智能体场景，区别于按端点逐步触发的结构化仪表盘流程。

    请求体 ``CoachRequest``:
        - ``goal`` (str): 学习目标/任务描述，例如「帮我制定并讲解 Python 装饰器的学习计划」。

    响应: ``text/event-stream``，事件依次为:

        event: delta
        data: {"text": "<模型 token 片段>"}
        event: tool
        data: {"event": "on_tool_start" | "on_tool_end", "name": "<工具/子代理名>"}
        event: done
        data: {"ok": true}
        event: error
        data: {"detail": "<错误信息>"}

    说明: delta 为模型（含子代理）推理与输出文本片段；tool 事件透出委派/工具调用，
    可用于在 UI 展示「正在调用 quizzer」等过程。最终结论以 delta 累积为准。

    错误:
        - 503: 未在「模型设置」配置模型 API Key。
        - 流中 error 事件: 运行失败。
    """
    h._require_configured(str(user["id"]))
    logger.info("coach_stream: user=%s goal=%s", user["username"], req.goal[:100])

    async def event_stream():
        try:
            async for kind, payload in h.coach.coach_stream(
                req.goal, req.history, str(user["id"]),
                prev_summary=req.summary, summarized_count=req.summarizedCount or 0,
            ):
                yield h._sse(kind, payload)
            yield h._sse("done", {"ok": True})
        except Exception as exc:
            yield h._sse("error", {"detail": _friendly_llm_error(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


