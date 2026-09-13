from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import long_memory, store
from ..auth import get_current_user, hash_password
from . import helpers as h

router = APIRouter()
logger = logging.getLogger(__name__)

from ..auth import require_admin
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
# Admin（管理员：用户管理）
# ---------------------------------------------------------------------------

@router.get("/api/admin/users")
def admin_list_users(admin: dict = Depends(require_admin)):
    """列出所有用户（仅管理员）。"""
    return store.list_users()


@router.post("/api/admin/users")
def admin_create_user(req: AdminCreateUserRequest, admin: dict = Depends(require_admin)):
    """创建用户（仅管理员，不开放自助注册）。

    请求体 ``AdminCreateUserRequest``:
        - ``username`` (str): 用户名，唯一。
        - ``password`` (str): 初始密码。
        - ``role`` ("admin" | "user"): 默认 ``user``。
        - ``email`` (str, 可选)。

    错误:
        409: 用户名或邮箱已存在。
    """
    try:
        created = store.create_user(
            req.username.strip(), hash_password(req.password),
            role=req.role, email=(req.email or None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    logger.info("admin_create_user: by=%s new=%s role=%s", admin["username"], created["username"], created["role"])
    return created


@router.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: str, admin: dict = Depends(require_admin)):
    """删除用户及其全部数据（计划、设置级联删除；仅管理员）。

    错误:
        400: 不能删除自己。
        404: 用户不存在。
    """
    if str(admin["id"]) == user_id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")
    if not store.delete_user(user_id):
        raise HTTPException(status_code=404, detail="user not found")
    logger.info("admin_delete_user: by=%s deleted=%s", admin["username"], user_id)
    return {"deleted": user_id}


@router.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: str, req: AdminResetPasswordRequest, admin: dict = Depends(require_admin)):
    """重置用户密码（仅管理员）；重置后吊销该用户全部会话。"""
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    store.update_user_password(user_id, hash_password(req.new_password))
    store.revoke_all_refresh_tokens(user_id)
    logger.info("admin_reset_password: by=%s target=%s", admin["username"], target["username"])
    return {"ok": True}


