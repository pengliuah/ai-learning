from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import long_memory, store
from ..auth import get_current_user
from ..config import _CST
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
from . import helpers as h

router = APIRouter()
logger = logging.getLogger(__name__)

from .. import ima
from ..schemas import SaveToImaRequest, SaveToImaResponse
from ..schemas import (
    ImaArchiveRequest,
    SaveToImaRequest,
    SaveToImaResponse,
)
from . import helpers as h

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/api/ima/archive")
def archive_to_ima(req: ImaArchiveRequest, user: dict = Depends(get_current_user)):
    """把聊天内容保存为 IMA 笔记（聊天页「保存到 IMA」按钮）。

    与模块内容保存不同：直接把文本导入 IMA，不经 LLM 格式化
    （对话内容本身已是干净文本）。

    返回 ``SaveToImaResponse``: ``{ok, noteId, title, detail}``。
    """
    uid = str(user["id"])
    row = store.get_ima_settings_row(uid)
    client_id = row["ima_client_id"]
    api_key = row["ima_api_key"]
    if not client_id or not api_key:
        return SaveToImaResponse(ok=False, detail="IMA 凭证未配置，请先在设置中填写 Client ID 和 API Key")
    title = (req.title or "").strip() or f"聊天存档 {datetime.now(_CST):%Y-%m-%d %H:%M}"
    try:
        result = ima.import_note(client_id, api_key, req.content, title)
    except Exception as exc:
        logger.error("archive_to_ima: failed (user=%s): %s", user["username"], exc)
        return SaveToImaResponse(ok=False, detail=str(exc))
    logger.info("archive_to_ima: ok (user=%s) note_id=%s", user["username"], result.get("note_id"))
    return SaveToImaResponse(ok=True, noteId=result.get("note_id") or "", title=title, detail="")



@router.post("/api/plans/{plan_id}/save-to-ima")
def save_to_ima(plan_id: str, req: SaveToImaRequest, user: dict = Depends(get_current_user)):
    """将计划或模块内容保存到 IMA 笔记。

    读取已存储的 IMA 凭证与 skill prompt，按需用 LLM 格式化后
    调用 IMA import_doc API 创建笔记。若 ``moduleId`` 为空则保存整个计划概览。

    请求体 ``SaveToImaRequest``:
        - ``moduleId`` (str, 可选): 指定模块则保存该模块内容，为空保存整个计划。
        - ``skillPromptOverride`` (str, 可选): 覆盖存储的 IMA skill prompt。

    返回 ``SaveToImaResponse``: ``{ok, noteId, title, detail}``。
    """
    doc = h._get_doc(plan_id, str(user["id"]))
    module = None
    if req.moduleId:
        module = h._get_module(doc, req.moduleId)
    return h.coach.save_to_ima(
        doc.plan, module=module, content_type=req.contentType,
        skill_prompt_override=req.skillPromptOverride, user_id=str(user["id"]),
    )


