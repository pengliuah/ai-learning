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
    RegisterRequest,
    SaveAnswersRequest,
    SaveToImaRequest,
    SaveToImaResponse,
)


# ---------------------------------------------------------------------------
# Auth（账号系统：用户名/邮箱 + 密码，双 token；注册走邀请制，见 /register）
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


@router.post("/api/auth/register")
def auth_register(req: RegisterRequest):
    """邀请制注册：凭有效邀请码自助建号（role=user），成功即登录。

    邀请码核销是原子操作（未禁用/未过期/未用尽才自增），并发不会超发。
    系统不开放自注册——没有有效邀请码无法创建账号。

    错误:
        400: 邀请码无效或已失效（不区分具体原因，防枚举）。
        409: 用户名已被占用。
    """
    username = req.username.strip()
    if store.get_user_by_username(username) is not None:
        raise HTTPException(status_code=409, detail="用户名已被占用")
    invite = store.consume_invite(req.invite_code)
    if invite is None:
        logger.info("register: 无效邀请码 username=%r", username)
        raise HTTPException(status_code=400, detail="邀请码无效或已失效")
    try:
        user = store.create_user(
            username, hash_password(req.password), role="user",
            invited_by=str(invite["created_by"]) if invite["created_by"] else None,
        )
    except ValueError as exc:
        # 极小概率: 核销与建号之间用户名被抢注。回滚核销不让码白扣。
        store.rollback_invite(str(invite["id"]))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("register: 新用户 %r 注册成功 (邀请制)", username)
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


