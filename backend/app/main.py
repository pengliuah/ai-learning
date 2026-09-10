"""FastAPI application: routes, CORS, JSON store, SSE streaming.

对外接口集中在下方路由函数。每个端点的 docstring 即 OpenAPI 描述
（可在 /docs 查看），同时作为接口契约文档。
"""

from __future__ import annotations

import json
import logging
import asyncio

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from . import long_memory, store
from .agent import LearningCoach, _friendly_llm_error
from .auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    require_admin,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from .config import BACKEND_DIR
from .middleware import AccessLogMiddleware
from .schemas import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AnnotationCreate,
    AnnotationOut,
    AnnotationUpdate,
    AnswersState,
    BookmarkOut,
    ChangePasswordRequest,
    CoachRequest,
    ContentUpdate,
    GenSettings,
    GenSettingsUpdate,
    ImaSettings,
    ImaSettingsUpdate,
    LoginRequest,
    MemoryOut,
    MemorySettings,
    MemorySettingsUpdate,
    ModelSettings,
    ModelSettingsUpdate,
    ModuleStatus,
    ModuleStatusPatch,
    PlanCreateRequest,
    PlanSource,
    PlansOrderUpdate,
    RefreshRequest,
    SaveAnswersRequest,
    SaveToImaRequest,
    SaveToImaResponse,
)

app = FastAPI(title="zhixue-backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AccessLogMiddleware)

coach = LearningCoach()
logger = logging.getLogger(__name__)

# SSE 长任务 (测验生成/批改) 的心跳间隔: 期间无数据回传会被 nginx/移动网络
# 当作空闲连接掐断 (浏览器报 Failed to fetch), 每 30s 发一个 ": ping" 注释帧保活。
LLM_HEARTBEAT_SECONDS = 30


def _user_public(user: dict) -> dict:
    """用户公开信息（绝不包含 password_hash）。"""
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "email": user.get("email"),
        "role": user["role"],
        "createdAt": user.get("created_at"),
    }


def is_configured_for_user(user_id: str) -> bool:
    """Whether the user's saved model config has an API key."""
    return store.is_llm_configured_for_user(user_id)


def _require_configured(user_id: str) -> None:
    """该用户未配置模型 API Key 时抛 503，统一拦截需要调用 LLM 的端点。"""
    if not is_configured_for_user(user_id):
        raise HTTPException(status_code=503, detail="model API key not configured")


def _get_doc(plan_id: str, user_id: str):
    """按 id 取当前用户的计划文档；不存在（或属于他人）则抛 404。"""
    doc = store.get_document(plan_id, user_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return doc


def _get_module(doc, module_id: str):
    """在文档中按 id 取模块；不存在则抛 404。"""
    module = next((m for m in doc.plan.modules if m.id == module_id), None)
    if module is None:
        raise HTTPException(status_code=404, detail="module not found")
    return module


@app.get("/api/health")
def health(user: dict = Depends(get_current_user)):
    """健康检查（需登录，按当前用户判定）。

    探测后端是否就绪、当前用户是否已配置模型 API Key。不调用任何 LLM。
    模型配置只存数据库，健康状态因人而异，因此本端点要求登录。

    返回:
        200 ``{"configured": bool, "model": str}``

        - ``configured``: 当前用户是否已在「模型设置」保存 API Key；
          为 false 时，所有需要 LLM 的生成端点会返回 503。
        - ``model``: 该用户配置的模型名（未配置为空串）。

    错误:
        401: 未登录。
    """
    try:
        _, model, _, _ = store.get_llm_config(str(user["id"]))
        return {"configured": is_configured_for_user(str(user["id"])), "model": model}
    except Exception:
        return {"configured": False, "model": ""}


# ---------------------------------------------------------------------------
# Auth（账号系统：用户名/邮箱 + 密码，双 token，管理员建号不开放注册）
# ---------------------------------------------------------------------------

@app.post("/api/auth/login")
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
        "user": _user_public(store.get_user(str(user["id"]))),
    }


@app.post("/api/auth/refresh")
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
        "user": _user_public(store.get_user(str(user["id"]))),
    }


@app.post("/api/auth/logout")
def auth_logout(req: RefreshRequest):
    """登出：吊销提交的 refresh token（幂等）。"""
    revoke_refresh_token(req.refresh_token)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(get_current_user)):
    """当前登录用户信息。"""
    return _user_public(user)


@app.post("/api/auth/change-password")
def auth_change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """修改自己的密码；成功后吊销该用户所有其他会话的 refresh token。"""
    if not verify_password(req.old_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")
    store.update_user_password(str(user["id"]), hash_password(req.new_password))
    store.revoke_all_refresh_tokens(str(user["id"]))
    logger.info("auth_change_password: user=%s", user["username"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin（管理员：用户管理）
# ---------------------------------------------------------------------------

@app.get("/api/admin/users")
def admin_list_users(admin: dict = Depends(require_admin)):
    """列出所有用户（仅管理员）。"""
    return store.list_users()


@app.post("/api/admin/users")
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


@app.delete("/api/admin/users/{user_id}")
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


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: str, req: AdminResetPasswordRequest, admin: dict = Depends(require_admin)):
    """重置用户密码（仅管理员）；重置后吊销该用户全部会话。"""
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    store.update_user_password(user_id, hash_password(req.new_password))
    store.revoke_all_refresh_tokens(user_id)
    logger.info("admin_reset_password: by=%s target=%s", admin["username"], target["username"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Plans（全部按当前用户隔离）
# ---------------------------------------------------------------------------

@app.post("/api/plans")
def create_plan(req: PlanCreateRequest, user: dict = Depends(get_current_user)):
    """生成并创建一份学习计划。

    调用 DeepAgents Planner 子代理（``create_deep_agent`` +
    ``response_format=Plan``），根据主题或粘贴的学习资料生成结构化、
    多模块的学习计划，并持久化到 PostgreSQL 数据库。
    模块 id 会被规范化，状态初始化为 ``not_started``。

    请求体 ``PlanCreateRequest``:
        - ``input`` (str): 主题描述，或粘贴的学习资料文本。
        - ``mode`` ("topic" | "materials"): "topic" 按主题规划；
          "materials" 基于资料规划。两者输出语言均与输入保持一致。

    返回:
        200 ``Document``: 完整计划文档，含 ``id``、``createdAt``、
        ``updatedAt``、``source``、``plan``（含 ``modules`` 列表）。

    错误:
        - 503: 未在「模型设置」配置模型 API Key。
        - 502: LLM 或结构化输出失败（已内置一次重试）。
    """
    _require_configured(str(user["id"]))
    logger.info("create_plan: user=%s input=%s mode=%s", user["username"], req.input[:100], req.mode)
    try:
        plan = coach.make_plan(PlanSource(input=req.input, mode=req.mode), str(user["id"]))
    except Exception as exc:
        logger.error("create_plan: failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"plan generation failed: {exc}")
    doc = store.create_document(PlanSource(input=req.input, mode=req.mode), plan, str(user["id"]))
    logger.info("create_plan: ok plan_id=%s title=%s modules=%d", doc.id, plan.title, len(plan.modules))
    return doc


@app.get("/api/plans")
def list_plans(q: str | None = None, user: dict = Depends(get_current_user)):
    """列出计划（概要视图），可按标题关键词过滤。

    查询参数 ``q`` (str, 可选) 按计划标题做大小写不敏感子串过滤；为空返回全部。
    返回轻量列表，用于首页计划列表展示。进度按「已完成模块数 / 模块总数」计算。

    返回:
        200 ``list[PlanListItem]``，每项含:
        - ``id`` (str)
        - ``title`` (str)
        - ``createdAt`` (datetime)
        - ``progress`` (float, 0.0~1.0)
    """
    items = store.list_items(str(user["id"]), q)
    logger.info("list_plans: user=%s q=%s count=%d", user["username"], (q or "-")[:50], len(items))
    return items


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: str, user: dict = Depends(get_current_user)):
    """获取某份计划的完整文档。

    包含计划元信息与全部模块（含各模块已生成的 content / quiz / result /
    answers，未生成的对应字段为 null）。供计划详情页加载。

    路径参数:
        plan_id (str): 计划 id。

    返回:
        200 ``Document``: 完整计划文档。

    错误:
        404: 计划不存在。
    """
    doc = _get_doc(plan_id, str(user["id"]))
    logger.info("get_plan: user=%s plan_id=%s title=%s", user["username"], plan_id, doc.plan.title)
    return doc


@app.delete("/api/plans/{plan_id}")
def delete_plan(plan_id: str, user: dict = Depends(get_current_user)):
    """删除某份计划（及其全部模块产物）。

    路径参数:
        plan_id (str): 计划 id。

    返回:
        200 ``{"deleted": "<plan_id>"}``

    错误:
        404: 计划不存在。
    """
    if not store.delete_document(plan_id, str(user["id"])):
        raise HTTPException(status_code=404, detail="plan not found")
    logger.info("delete_plan: plan_id=%s", plan_id)
    return {"deleted": plan_id}


@app.post("/api/plans/{plan_id}/modules/{module_id}/content")
async def generate_content(plan_id: str, module_id: str, user: dict = Depends(get_current_user)):
    """生成某模块的学习内容（SSE 流式）。

    调用流式 ``ChatOpenAI`` 逐 token 输出模块 Markdown 学习内容，
    流结束后解析结尾的「## 关键要点」小节作为 keyTakeaways，整体持久化为
    ``Content`` 并写回该模块；若模块原状态为 ``not_started`` 则置为 ``studying``。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    响应: ``text/event-stream``，事件依次为:

        event: delta
        data: {"delta": "<Markdown 片段>"}
        ...
        event: done
        data: <完整 Document（JSON，含已写入的 content）>
        event: error
        data: {"detail": "<错误信息>"}

    说明: 前端应累积 delta 拼接为正文，收到 done 后用其刷新整份文档状态。

    错误:
        - 503: 未在「模型设置」配置模型 API Key（生成前拦截）。
        - 404: 计划或模块不存在。
        - 流中 error 事件: 生成或持久化失败。
    """
    _require_configured(str(user["id"]))
    doc = _get_doc(plan_id, str(user["id"]))
    module = _get_module(doc, module_id)
    logger.info("generate_content: user=%s plan_id=%s module_id=%s", user["username"], plan_id, module_id)

    async def event_stream():
        nonlocal content
        stream_error: Exception | None = None
        try:
            async for kind, payload in coach.author_content_stream(doc.plan, module, str(user["id"])):
                if kind == "delta":
                    yield _sse("delta", {"delta": payload})
                elif kind == "done":
                    content = payload
        except Exception as exc:
            stream_error = exc

        # 成功、或中途失败但有部分内容时都持久化 (agent 会对部分内容发 done);
        # 随后如有异常再发 error 事件, 前端提示失败但已生成的部分不丢。
        if content is not None:
            def mutate(m):
                m.content = content
                if m.status == ModuleStatus.not_started:
                    m.status = ModuleStatus.studying

            try:
                updated = store.update_module(plan_id, module_id, mutate, str(user["id"]))
                logger.info("generate_content: ok module_id=%s chars=%d", module_id, len(content.markdown) if content else 0)
                yield _sse("done", updated.model_dump(mode="json"))
            except Exception as exc:
                stream_error = stream_error or exc

        if stream_error is not None:
            yield _sse("error", {"detail": _friendly_llm_error(stream_error)})

    content = None
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/plans/{plan_id}/modules/{module_id}/content")
def get_content(plan_id: str, module_id: str, user: dict = Depends(get_current_user)):
    """读取某模块已生成的学习内容。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    返回:
        200 ``Content``: ``{"markdown": str, "keyTakeaways": list[str]}``。

    错误:
        - 404: 计划/模块不存在，或该模块尚未生成内容。
    """
    module = _get_module(_get_doc(plan_id, str(user["id"])), module_id)
    if module.content is None:
        raise HTTPException(status_code=404, detail="content not generated")
    return module.content


@app.post("/api/plans/{plan_id}/modules/{module_id}/quiz")
async def generate_quiz(plan_id: str, module_id: str, user: dict = Depends(get_current_user)):
    """为某模块生成测验（SSE + 心跳保活）。

    调用 DeepAgents Quizzer 子代理（``response_format=Quiz``），基于模块内容
    （若无内容则基于摘要）生成单选 + 简答题，并写回该模块。

    生成是分钟级长任务且期间无数据回传，移动网络/nginx 会掐断"空闲"连接
    （浏览器报 Failed to fetch），因此改为 SSE：每 30 秒发一个注释帧
    ``: ping`` 保活，完成后发 done 事件携带结果。

    响应: ``text/event-stream``:

        : ping            (每 30s 一次)
        event: done
        data: <完整 Document（JSON，该模块含 quiz；result/answers 已重置）>
        event: error
        data: {"detail": "<错误信息>"}

    错误:
        - 503: 未在「模型设置」配置模型 API Key（流开始前）。
        - 404: 计划或模块不存在（流开始前）。
        - 流中 error 事件: LLM 或结构化输出失败（已内置一次重试）。
    """
    uid = str(user["id"])
    _require_configured(uid)
    doc = _get_doc(plan_id, uid)
    module = _get_module(doc, module_id)
    logger.info("generate_quiz: user=%s plan_id=%s module_id=%s", user["username"], plan_id, module_id)

    def work():
        quiz = coach.make_quiz(doc.plan, module, uid)
        logger.info("generate_quiz: generated module_id=%s questions=%d", module_id, len(quiz.questions))

        def mutate(m):
            m.quiz = quiz
            # Regenerating the quiz invalidates any prior grading result and saved
            # draft answers (they reference old question ids).
            m.result = None
            m.answers = None

        return store.update_module(plan_id, module_id, mutate, uid)

    async def event_stream():
        # LLM 调用放线程池; 每 30s 无结果就发心跳注释帧, 避免连接被中间层掐断
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            while True:
                try:
                    updated = await asyncio.wait_for(asyncio.shield(task), timeout=LLM_HEARTBEAT_SECONDS)
                    yield _sse("done", updated.model_dump(mode="json"))
                    return
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except Exception as exc:
            logger.error("generate_quiz: failed: %s", exc)
            yield _sse("error", {"detail": _friendly_llm_error(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/plans/{plan_id}/modules/{module_id}/quiz")
def get_quiz(plan_id: str, module_id: str, user: dict = Depends(get_current_user)):
    """读取某模块已生成的测验。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    返回:
        200 ``Quiz``: ``{"questions": [Question...]}``。

    错误:
        - 404: 计划/模块不存在，或该模块尚未生成测验。
    """
    module = _get_module(_get_doc(plan_id, str(user["id"])), module_id)
    if module.quiz is None:
        raise HTTPException(status_code=404, detail="quiz not generated")
    return module.quiz


@app.put("/api/plans/{plan_id}/modules/{module_id}/answers")
def save_answers(plan_id: str, module_id: str, req: SaveAnswersRequest, user: dict = Depends(get_current_user)):
    """保存（合并）测验作答草稿。

    前端可随答随存（自动保存单题作答）：请求体里的 answers 会合并进该模块
    已有草稿（按 questionId 覆盖同名项），不触发批改。用于断点续答。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    请求体 ``SaveAnswersRequest``:
        - ``answers`` (dict[str, str]): questionId -> 作答文本。
          mcq 存选项值；简答存文本。空串视为已答（答了空白）。

    返回:
        200 ``Document``: 更新后的完整计划文档（该模块含合并后的 ``answers``）。

    错误:
        - 404: 计划或模块不存在。
    """
    _get_module(_get_doc(plan_id, str(user["id"])), module_id)

    def mutate(m):
        m.answers = {**(m.answers or {}), **req.answers}

    return store.update_module(plan_id, module_id, mutate, str(user["id"]))


@app.get("/api/plans/{plan_id}/modules/{module_id}/answers")
def get_answers(plan_id: str, module_id: str, user: dict = Depends(get_current_user)):
    """读取测验作答草稿与进度。

    用于恢复已答内容、展示作答进度（已答题数 / 总题数）。总题数取自该模块
    已生成的 quiz；若未生成 quiz，total 为 0。已答数 = 草稿中非空作答的数量。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    返回:
        200 ``AnswersState``: ``{"answers": {...}, "answered": int, "total": int}``。

    错误:
        - 404: 计划或模块不存在。
    """
    module = _get_module(_get_doc(plan_id, str(user["id"])), module_id)
    answers = module.answers or {}
    total = len(module.quiz.questions) if module.quiz else 0
    answered = sum(1 for v in answers.values() if v and v.strip())
    return AnswersState(answers=answers, answered=answered, total=total)


@app.post("/api/plans/{plan_id}/modules/{module_id}/grade")
async def grade_quiz(plan_id: str, module_id: str, user: dict = Depends(get_current_user)):
    """批改某模块测验并给出评估（SSE + 心跳保活，从已保存草稿批改）。

    调用 DeepAgents Grader 子代理（``response_format=GradingResult``），
    从该模块已保存的 ``answers`` 草稿读取作答逐题评分并给出整体评估。
    批改后把每题原始作答写回 ``QuestionResult.studentAnswer``，结果页可回看
    学生当时答了什么（不只是分数）。结果写回该模块，状态置为 ``completed``。

    典型流程: ``PUT .../answers``（随答随存草稿） -> ``POST .../grade``（批改）。

    与测验生成同为分钟级长任务，改为 SSE：每 30 秒发 ``: ping`` 注释帧保活。

    响应: ``text/event-stream``:

        : ping            (每 30s 一次)
        event: done
        data: <完整 Document（JSON，该模块含 result，status 为 completed）>
        event: error
        data: {"detail": "<错误信息>"}

    错误:
        - 503: 未在「模型设置」配置模型 API Key（流开始前）。
        - 404: 计划/模块不存在，或该模块尚未生成测验（流开始前）。
        - 400: 没有已保存作答（流开始前）。
        - 流中 error 事件: LLM 或结构化输出失败（已内置一次重试）。
    """
    uid = str(user["id"])
    _require_configured(uid)
    doc = _get_doc(plan_id, uid)
    module = _get_module(doc, module_id)
    if module.quiz is None:
        raise HTTPException(status_code=404, detail="quiz not generated")
    answers = module.answers or {}
    if not answers:
        raise HTTPException(status_code=400, detail="no saved answers to grade; PUT .../answers first")

    def work():
        return coach.grade_quiz(doc.plan, module, answers, uid)

    async def event_stream():
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            while True:
                try:
                    result = await asyncio.wait_for(asyncio.shield(task), timeout=LLM_HEARTBEAT_SECONDS)

                    def mutate(m):
                        m.result = result
                        m.status = ModuleStatus.completed

                    updated = store.update_module(plan_id, module_id, mutate, uid)
                    logger.info("grade_quiz: ok user=%s plan_id=%s module_id=%s score=%.1f/%.1f",
                                user["username"], plan_id, module_id, result.totalScore, result.maxScore)
                    yield _sse("done", updated.model_dump(mode="json"))
                    return
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except Exception as exc:
            logger.error("grade_quiz: failed: %s", exc)
            yield _sse("error", {"detail": _friendly_llm_error(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.patch("/api/plans/{plan_id}/modules/{module_id}")
def patch_module_status(plan_id: str, module_id: str, patch: ModuleStatusPatch, user: dict = Depends(get_current_user)):
    """更新某模块状态。

    用于前端手动标记模块进度（如标记跳过/重做）。
    注意：grade 端点会自动将状态置为 completed，通常无需手动 patch。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    请求体 ``ModuleStatusPatch``:
        - ``status`` ("not_started" | "studying" | "completed")。

    返回:
        200 ``Document``: 更新后的完整计划文档。

    错误:
        - 404: 计划或模块不存在。
    """
    _get_module(_get_doc(plan_id, str(user["id"])), module_id)

    def mutate(m):
        m.status = patch.status

    return store.update_module(plan_id, module_id, mutate, str(user["id"]))


@app.put("/api/plans/{plan_id}/modules/{module_id}/content")
def put_module_content(plan_id: str, module_id: str, req: ContentUpdate, user: dict = Depends(get_current_user)):
    """手工编辑某模块学习内容的 markdown 正文。

    只替换 ``content.markdown``，关键要点（keyTakeaways）保持不变。
    典型用途：用户对 AI 生成的内容做增删改后保存。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    请求体 ``ContentUpdate``:
        - ``markdown`` (str): 编辑后的正文（去除首尾空白后不允许为空）。

    返回:
        200 ``Document``: 更新后的完整计划文档。

    错误:
        - 404: 计划或模块不存在。
        - 400: 模块尚未生成学习内容，或正文为空。
    """
    doc = _get_doc(plan_id, str(user["id"]))
    module = _get_module(doc, module_id)
    if module.content is None:
        raise HTTPException(status_code=400, detail="该模块还没有学习内容，请先生成")
    markdown = req.markdown.strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="内容不能为空")

    def mutate(m):
        m.content.markdown = markdown

    logger.info("put_module_content: plan=%s module=%s markdown_chars=%d",
                plan_id, module_id, len(markdown))
    return store.update_module(plan_id, module_id, mutate, str(user["id"]))


@app.put("/api/plans/order")
def put_plans_order(req: PlansOrderUpdate, user: dict = Depends(get_current_user)):
    """按新顺序持久化学习计划列表（首页拖拽排序）。

    只更新当前用户的 ``plans.sort_order``，列表读取按它排序，
    计划内容与模块数据均不受影响。

    请求体 ``PlansOrderUpdate``:
        - ``planIds`` (list[str]): 当前用户的全部计划 id，按新顺序排列。

    返回:
        200 ``list[PlanListItem]``: 重排后的计划概要列表。

    错误:
        - 400: planIds 与当前用户的计划 id 集合不完全一致。
    """
    uid = str(user["id"])
    current_ids = {item.id for item in store.list_items(uid)}
    if len(req.planIds) != len(current_ids) or set(req.planIds) != current_ids:
        raise HTTPException(status_code=400, detail="planIds 必须恰好包含当前用户的全部计划 id")
    logger.info("put_plans_order: user=%s plans=%d", user["username"], len(req.planIds))
    store.reorder_plans(req.planIds, uid)
    return store.list_items(uid)


# ---------------------------------------------------------------------------
# 学习内容批注（Word 式笔记，按用户隔离）
# ---------------------------------------------------------------------------

@app.get("/api/plans/{plan_id}/modules/{module_id}/annotations")
def list_annotations(plan_id: str, module_id: str, user: dict = Depends(get_current_user)):
    """列出当前用户在某模块学习内容上的全部批注。

    返回:
        200 list[AnnotationOut]: 按创建时间升序。

    错误:
        - 404: 计划或模块不存在。
    """
    uid = str(user["id"])
    _get_module(_get_doc(plan_id, uid), module_id)
    return [
        AnnotationOut(**a)
        for a in store.list_annotations(uid, plan_id, module_id)
    ]


@app.get("/api/annotations")
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


@app.post("/api/plans/{plan_id}/modules/{module_id}/annotations")
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
    _get_module(_get_doc(plan_id, uid), module_id)
    created = store.create_annotation(
        uid, plan_id, module_id,
        quote=req.quote.strip(), prefix=req.prefix, suffix=req.suffix, note=req.note,
    )
    return AnnotationOut(**created)


@app.put("/api/plans/{plan_id}/annotations/{annotation_id}")
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


@app.delete("/api/plans/{plan_id}/annotations/{annotation_id}")
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


@app.post("/api/coach/stream")
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
    _require_configured(str(user["id"]))
    logger.info("coach_stream: user=%s goal=%s", user["username"], req.goal[:100])

    async def event_stream():
        try:
            async for kind, payload in coach.coach_stream(req.goal, req.history, str(user["id"])):
                yield _sse(kind, payload)
            yield _sse("done", {"ok": True})
        except Exception as exc:
            yield _sse("error", {"detail": _friendly_llm_error(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/settings/ima")
def get_ima_settings(user: dict = Depends(get_current_user)):
    """读取当前用户的 IMA 设置（凭证 + skill prompt）。"""
    row = store.get_ima_settings_row(str(user["id"]))
    return ImaSettings(
        imaClientId=row["ima_client_id"],
        imaApiKey=row["ima_api_key"],
        imaSkillPrompt=row["ima_skill_prompt"],
    )


@app.put("/api/settings/ima")
def put_ima_settings(req: ImaSettingsUpdate, user: dict = Depends(get_current_user)):
    """更新当前用户的 IMA 设置（仅更新提供的字段）。"""
    row = store.update_ima_settings(
        str(user["id"]),
        client_id=req.imaClientId,
        api_key=req.imaApiKey,
        skill_prompt=req.imaSkillPrompt,
    )
    logger.info("put_ima_settings: updated (client_id set=%s, prompt set=%s)",
                bool(row["ima_client_id"]), bool(row["ima_skill_prompt"]))
    return ImaSettings(
        imaClientId=row["ima_client_id"],
        imaApiKey=row["ima_api_key"],
        imaSkillPrompt=row["ima_skill_prompt"],
    )


@app.get("/api/settings/regenerate")
def get_regen_settings(user: dict = Depends(get_current_user)):
    """读取当前用户的生成策略设置（按类型：plan/content/quiz/grade）。"""
    row = store.get_gen_settings_row(str(user["id"]))
    return GenSettings(plan=row["plan"], content=row["content"], quiz=row["quiz"], grade=row["grade"])


@app.put("/api/settings/regenerate")
def put_regen_settings(req: GenSettingsUpdate, user: dict = Depends(get_current_user)):
    """更新当前用户的生成策略设置（仅更新提供的字段）。"""
    row = store.update_gen_settings(
        str(user["id"]), plan=req.plan, content=req.content, quiz=req.quiz, grade=req.grade
    )
    logger.info("put_regen_settings: plan=%s content=%s quiz=%s grade=%s",
                bool(row["plan"]), bool(row["content"]), bool(row["quiz"]), bool(row["grade"]))
    return GenSettings(plan=row["plan"], content=row["content"], quiz=row["quiz"], grade=row["grade"])


@app.get("/api/settings/model")
def get_model_settings(user: dict = Depends(get_current_user)):
    """读取当前用户在库里保存的模型设置（原样返回，不做环境变量回退）。

    只返回该用户在数据库中保存的值：空字段表示未配置，
    不会用任何默认值填充，避免误把部署级配置当成个人配置。
    """
    row = store.get_model_settings_row(str(user["id"]))
    return ModelSettings(
        apiKey=row["api_key"], model=row["model"],
        baseUrl=row["base_url"], maxTokens=row["max_tokens"],
        embeddingApiKey=row.get("embedding_api_key") or "",
        embeddingModel=row.get("embedding_model") or "",
        embeddingBaseUrl=row.get("embedding_base_url") or "",
    )


@app.put("/api/settings/model")
def put_model_settings(req: ModelSettingsUpdate, user: dict = Depends(get_current_user)):
    """保存当前用户的模型设置（仅更新提供的字段），并刷新已缓存的模型实例。"""
    row = store.update_model_settings(
        str(user["id"]),
        api_key=req.apiKey,
        model=req.model,
        base_url=req.baseUrl,
        max_tokens=req.maxTokens,
        embedding_api_key=req.embeddingApiKey,
        embedding_model=req.embeddingModel,
        embedding_base_url=req.embeddingBaseUrl,
    )
    reset = getattr(coach, "reset_model_runtime", None)
    if reset:
        reset()
    logger.info("put_model_settings: updated (key set=%s, model set=%s, embedding set=%s)",
                bool(row["api_key"]), bool(row["model"]), bool(row.get("embedding_model")))
    return ModelSettings(
        apiKey=row["api_key"], model=row["model"],
        baseUrl=row["base_url"], maxTokens=row["max_tokens"],
        embeddingApiKey=row.get("embedding_api_key") or "",
        embeddingModel=row.get("embedding_model") or "",
        embeddingBaseUrl=row.get("embedding_base_url") or "",
    )


@app.get("/api/usage/summary")
def usage_summary(user: dict = Depends(get_current_user)):
    """当前用户的 LLM token 用量统计（今日 / 本月 / 累计，东八区）。"""
    return store.get_usage_summary(str(user["id"]))


@app.get("/api/settings/memory")
def get_memory_settings(user: dict = Depends(get_current_user)):
    """读取长期记忆总开关（默认开启）。关掉后教练对话不写入、不召回。"""
    row = store.get_memory_settings_row(str(user["id"]))
    return MemorySettings(enabled=row["enabled"])


@app.put("/api/settings/memory")
def put_memory_settings(req: MemorySettingsUpdate, user: dict = Depends(get_current_user)):
    """更新长期记忆总开关。"""
    row = store.update_memory_settings(str(user["id"]), enabled=req.enabled)
    logger.info("put_memory_settings: enabled=%s user=%s", row["enabled"], user["username"])
    return MemorySettings(enabled=row["enabled"])


@app.get("/api/memories")
async def list_memories(user: dict = Depends(get_current_user)):
    """列出当前用户的长期记忆（Mem0 事实列表）。

    模型未配置时返回空列表；总开关关闭时仍可查看已有记忆。
    """
    uid = str(user["id"])
    items = await long_memory.list_memories(uid)
    return [
        MemoryOut(
            id=m["id"],
            memory=m["memory"],
            createdAt=m.get("createdAt"),
            updatedAt=m.get("updatedAt"),
        )
        for m in items
    ]


@app.delete("/api/memories/{memory_id}")
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


@app.post("/api/plans/{plan_id}/save-to-ima")
def save_to_ima(plan_id: str, req: SaveToImaRequest, user: dict = Depends(get_current_user)):
    """将计划或模块内容保存到 IMA 笔记。

    读取已存储的 IMA 凭证与 skill prompt，按需用 LLM 格式化后
    调用 IMA import_doc API 创建笔记。若 ``moduleId`` 为空则保存整个计划概览。

    请求体 ``SaveToImaRequest``:
        - ``moduleId`` (str, 可选): 指定模块则保存该模块内容，为空保存整个计划。
        - ``skillPromptOverride`` (str, 可选): 覆盖存储的 IMA skill prompt。

    返回 ``SaveToImaResponse``: ``{ok, noteId, title, detail}``。
    """
    doc = _get_doc(plan_id, str(user["id"]))
    module = None
    if req.moduleId:
        module = _get_module(doc, req.moduleId)
    return coach.save_to_ima(
        doc.plan, module=module, content_type=req.contentType,
        skill_prompt_override=req.skillPromptOverride, user_id=str(user["id"]),
    )


def _sse(event: str, data) -> str:
    """格式化一条 SSE 事件帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# --- 生产静态托管: 前端构建产物 ---
_frontend_dist = BACKEND_DIR.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        """非 API 路径优先返回 dist 里的同名静态文件（如 favicon.svg），
        否则返回 index.html，交给前端路由处理 (SPA)。"""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (_frontend_dist / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(_frontend_dist.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(_frontend_dist / "index.html")
