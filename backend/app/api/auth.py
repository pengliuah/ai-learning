from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import long_memory, store
from ..auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)
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
# Auth（账号系统：用户名/邮箱 + 密码，双 token，管理员建号不开放注册）
# ---------------------------------------------------------------------------

@router.post("/api/auth/login")
def auth_login(req: LoginRequest):
    """登录，换取双 token。

    请求体 ``LoginRequest``: ``{username, password}``（username 兼容邮箱字段
    预留，当前仅按用户名匹配）。

    返回:
        200 ``{access_token, refresh_token, token_type: "bearer", user}``。
        access_token 为 30 分钟 JWT；refresh_token 为 14 天 opaque 串
        （服务端只存哈希），每次刷新轮换。

    错误:
        401: 用户名或密码错误。
    """
    user = store.get_user_by_username(req.username.strip())
    if user is None or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(str(user["id"])),
        "token_type": "bearer",
        "user": h._user_public(store.get_user(str(user["id"]))),
    }


@router.post("/api/auth/refresh")
def auth_refresh(req: RefreshRequest):
    """用 refresh token 换取新 token 对（轮换：旧 refresh token 立即作废）。

    错误:
        401: refresh token 无效/过期/已吊销。再次提交已吊销的 token 会
        吊销该用户全部 refresh token（泄露处置）。
    """
    user, access, refresh = rotate_refresh_token(req.refresh_token)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": h._user_public(store.get_user(str(user["id"]))),
    }


@router.post("/api/auth/logout")
def auth_logout(req: RefreshRequest):
    """登出：吊销提交的 refresh token（幂等）。"""
    revoke_refresh_token(req.refresh_token)
    return {"ok": True}


@router.get("/api/auth/me")
def auth_me(user: dict = Depends(get_current_user)):
    """当前登录用户信息。"""
    return h._user_public(user)


@router.post("/api/auth/change-password")
def auth_change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """修改自己的密码；成功后吊销该用户所有其他会话的 refresh token。"""
    if not verify_password(req.old_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")
    store.update_user_password(str(user["id"]), hash_password(req.new_password))
    store.revoke_all_refresh_tokens(str(user["id"]))
    logger.info("auth_change_password: user=%s", user["username"])
    return {"ok": True}


