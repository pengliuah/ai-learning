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

from ..config import settings
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

@router.get("/api/memories")
async def list_memories(user: dict = Depends(get_current_user)):
    """列出当前用户的长期记忆（Mem0 事实列表，含整理元数据）。

    模型未配置时返回空列表；总开关关闭时仍可查看已有记忆。
    每条含 category / importance / superseded（被整理任务标记过时）。
    """
    uid = str(user["id"])
    items = await long_memory.list_memories(uid)
    return [
        MemoryOut(
            id=m["id"],
            memory=m["memory"],
            createdAt=m.get("createdAt"),
            updatedAt=m.get("updatedAt"),
            category=m.get("category"),
            importance=m.get("importance"),
            superseded=bool(m.get("superseded")),
        )
        for m in items
    ]


@router.get("/api/memories/status")
async def memory_status(user: dict = Depends(get_current_user)):
    """记忆整理状态一览：画像 / 水位 / 标注覆盖率 / 循环配置。

    用于回答"整理到底跑没跑"：
    - lastRunAt 为 null 且 touched=false → 循环还没处理过该用户；
    - labeled < total → 有事实尚未被标注（写入时的标注调用失败或来自老数据）；
    - profile 为空且记忆非空 → 画像尚未生成（等下一轮或手动触发整理）。
    """
    uid = str(user["id"])
    items = await long_memory.list_memories(uid)
    st = await asyncio.to_thread(store.memory_housekeeping_status, uid)
    return {
        **st,
        "total": len(items),
        "labeled": sum(1 for m in items if m.get("category")),
        "superseded": sum(1 for m in items if m.get("superseded")),
        "housekeepingEnabled": settings.memory_housekeeping,
        "intervalHours": settings.memory_housekeeping_interval_hours,
    }


@router.post("/api/memories/consolidate")
async def consolidate_memories(user: dict = Depends(get_current_user)):
    """立即为当前用户执行一次记忆整理（合并重复/标记过时/刷新画像）。

    与夜间循环相同的逻辑，用于不等 6 小时间隔的手动验证。
    返回: ``{"merged": int, "superseded": int, "profile": bool}``。
    """
    uid = str(user["id"])
    stats = await long_memory.consolidate_user(uid)
    await asyncio.to_thread(store.touch_housekeeping, uid)
    return stats


@router.get("/api/memories/profile")
async def get_memory_profile(user: dict = Depends(get_current_user)):
    """获取当前用户的学生画像（长期记忆的摘要层，展示在记忆页可被修改）。"""
    uid = str(user["id"])
    st = await asyncio.to_thread(store.memory_housekeeping_status, uid)
    return {
        "profile": st["profile"],
        "updatedAt": st["profileUpdatedAt"],
        "editedByUser": st["profileEditedByUser"],
    }


@router.put("/api/memories/profile")
async def put_memory_profile(req: MemoryProfileUpdate, user: dict = Depends(get_current_user)):
    """修改当前用户的学生画像。

    用户手动修正后 ``edited_by_user=true``，夜间整理不再自动覆盖
    （画像以用户的版本为准，之后仍可继续手动编辑）。
    """
    uid = str(user["id"])
    await asyncio.to_thread(store.save_memory_profile, uid, req.profile, True)
    logger.info("memory_profile: 用户修改画像 (user=%s, %d chars)", user["username"], len(req.profile))
    st = await asyncio.to_thread(store.memory_housekeeping_status, uid)
    return {"profile": st["profile"], "updatedAt": st["profileUpdatedAt"], "editedByUser": True}


@router.put("/api/memories/{memory_id}")
async def edit_memory(memory_id: str, req: MemoryUpdate, user: dict = Depends(get_current_user)):
    """修改一条属于当前用户的长期记忆正文。

    修改后重新向量化，元数据（分类/重要性/时间）保留。
    返回:
        200 ``{"updated": "<id>"}``

    错误:
        - 404: 记忆不存在或不属于当前用户（含模型未配置无法访问）。
    """
    uid = str(user["id"])
    ok = await long_memory.update_memory_text(uid, memory_id, req.memory)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在或不属于当前用户")
    return {"updated": memory_id}


@router.post("/api/memories/archive")
async def archive_memory(req: MemoryArchiveRequest, user: dict = Depends(get_current_user)):
    """把用户明确要求保存的内容原样写入长期记忆（聊天页「保存到长期记忆」按钮）。

    逐字入库（跳过抽取改写），仍会自动标注分类/重要性。
    返回:
        200 ``{"ok": true}``
    错误:
        - 503: 未配置模型 / 记忆总开关关闭。
    """
    uid = str(user["id"])
    ok = await long_memory.archive(uid, req.content)
    if not ok:
        raise HTTPException(status_code=503, detail="写入失败（记忆未开启或模型未配置）")
    return {"ok": True}




@router.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str, user: dict = Depends(get_current_user)):
    """删除一条属于当前用户的长期记忆。

    返回:
        200 ``{"deleted": "<id>"}``

    错误:
        - 404: 记忆不存在或不属于当前用户（含模型未配置无法访问）。
    """
    uid = str(user["id"])
    ok = await long_memory.delete_memory(uid, memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在或无权删除")
    return {"deleted": memory_id}
