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

# ---------------------------------------------------------------------------
# 学习内容批注（Word 式笔记，按用户隔离）
# ---------------------------------------------------------------------------

@router.get("/api/plans/{plan_id}/modules/{module_id}/annotations")
def list_annotations(plan_id: str, module_id: str, user: dict = Depends(get_current_user)):
    """列出当前用户在某模块学习内容上的全部批注。

    返回:
        200 list[AnnotationOut]: 按创建时间升序。

    错误:
        - 404: 计划或模块不存在。
    """
    uid = str(user["id"])
    h._get_module(h._get_doc(plan_id, uid), module_id)
    return [
        AnnotationOut(**a)
        for a in store.list_annotations(uid, plan_id, module_id)
    ]


@router.get("/api/annotations")
def list_bookmarks(user: dict = Depends(get_current_user)):
    """列出当前用户的全部书签（跨计划/模块聚合，供书签列表页使用）。

    每项附带计划/模块标题；点击书签跳转
    ``/plans/{planId}/modules/{moduleId}?bookmark={id}`` 即可定位到原文。

    返回:
        200 list[BookmarkOut]: 按创建时间倒序。
    """
    uid = str(user["id"])
    items = [
        BookmarkOut(
            id=a["id"],
            planId=a["planId"],
            planTitle=a["plan_title"],
            moduleId=a["moduleKey"],
            moduleTitle=a.get("module_title"),
            quote=a["quote"],
            note=a["note"],
            createdAt=a["createdAt"],
        )
        for a in store.list_all_annotations(uid)
    ]
    logger.info("list_bookmarks: user=%s count=%d", user["username"], len(items))
    return items


@router.post("/api/plans/{plan_id}/modules/{module_id}/annotations")
def create_annotation(plan_id: str, module_id: str, req: AnnotationCreate, user: dict = Depends(get_current_user)):
    """在模块学习内容上添加一条批注。

    请求体 ``AnnotationCreate``:
        - ``quote`` (str): 选中的原文。
        - ``prefix`` / ``suffix`` (str): 原文前后约 32 字符，用于重新渲染时锚定。
        - ``note`` (str): 批注内容。

    返回:
        200 ``AnnotationOut``: 新建的批注。

    错误:
        - 404: 计划或模块不存在。
    """
    uid = str(user["id"])
    h._get_module(h._get_doc(plan_id, uid), module_id)
    created = store.create_annotation(
        uid, plan_id, module_id,
        quote=req.quote.strip(), prefix=req.prefix, suffix=req.suffix, note=req.note,
    )
    return AnnotationOut(**created)


@router.put("/api/plans/{plan_id}/annotations/{annotation_id}")
def update_annotation(plan_id: str, annotation_id: str, req: AnnotationUpdate, user: dict = Depends(get_current_user)):
    """修改一条批注的内容。

    返回:
        200 ``AnnotationOut``: 更新后的批注。

    错误:
        - 404: 计划不存在，或批注不存在/不属于当前用户。
    """
    try:
        updated = store.update_annotation(str(user["id"]), plan_id, annotation_id, req.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="annotation not found")
    return AnnotationOut(**updated)


@router.delete("/api/plans/{plan_id}/annotations/{annotation_id}")
def delete_annotation(plan_id: str, annotation_id: str, user: dict = Depends(get_current_user)):
    """删除一条批注。

    返回:
        200 ``{"deleted": "<annotation_id>"}``。

    错误:
        - 404: 计划不存在，或批注不存在/不属于当前用户。
    """
    try:
        ok = store.delete_annotation(str(user["id"]), plan_id, annotation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="plan not found")
    if not ok:
        raise HTTPException(status_code=404, detail="annotation not found")
    return {"deleted": annotation_id}


