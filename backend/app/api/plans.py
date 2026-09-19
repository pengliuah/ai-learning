from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import attachments as attachments_svc
from .. import long_memory, store
from ..auth import get_current_user
from ..agent import _friendly_llm_error
from . import helpers as h

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_source(req: PlanCreateRequest, uid: str) -> PlanSource:
    """Build the PlanSource for creation, resolving attachment transcripts.

    带附件时把转写文本拼成 materials 输入（两段式：全模态转写 → 现有规划
    链路），mode 强制 materials；引用的附件都没转完返回 409。无附件原样透传。
    """
    input_text = (req.input or "").strip()
    if req.attachmentIds:
        try:
            materials = attachments_svc.build_materials_input(uid, req.attachmentIds, input_text)
        except attachments_svc.AttachmentsNotReady:
            raise HTTPException(409, "附件还在解析中，请稍候几秒再生成")
        if not materials:
            raise HTTPException(400, "学习资料为空：请上传文件或输入文本")
        return PlanSource(input=materials, mode="materials", attachmentIds=req.attachmentIds)
    if req.mode == "materials" and not input_text:
        raise HTTPException(400, "学习资料为空：请上传文件或输入文本")
    return PlanSource(input=input_text, mode=req.mode, attachmentIds=[])

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
# Plans（全部按当前用户隔离）
# ---------------------------------------------------------------------------

@router.post("/api/plans")
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
    h._require_configured(str(user["id"]))
    logger.info("create_plan: user=%s input=%s mode=%s attachments=%d",
                user["username"], req.input[:100], req.mode, len(req.attachmentIds))
    source = _resolve_source(req, str(user["id"]))
    try:
        plan = h.coach.make_plan(source, str(user["id"]))
    except Exception as exc:
        logger.error("create_plan: failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"plan generation failed: {exc}")
    doc = store.create_document(source, plan, str(user["id"]))
    logger.info("create_plan: ok plan_id=%s title=%s modules=%d", doc.id, plan.title, len(plan.modules))
    return doc


@router.post("/api/plans/stream")
async def create_plan_stream(req: PlanCreateRequest, user: dict = Depends(get_current_user)):
    """生成并创建一份学习计划（SSE + 心跳保活）。

    与 ``POST /api/plans`` 相同的生成与入库逻辑，但改为事件流返回：
    生成是分钟级长任务且期间无数据回传，移动网络/nginx 会掐断"空闲"连接
    （App/浏览器报超时或失败，而其实后端已生成并入库），因此每 30 秒发一个
    注释帧 ``: ping`` 保活，完成后发 done 事件携带完整计划文档。
    客户端中途断开时后端仍会把已生成的计划入库。

    响应: ``text/event-stream``:

        : ping            (每 30s 一次)
        event: done
        data: <完整 Document（JSON，含 id/plan/modules）>
        event: error
        data: {"detail": "<错误信息>"}

    错误:
        - 503: 未在「模型设置」配置模型 API Key（流开始前）。
        - 流中 error 事件: LLM 或结构化输出失败（已内置一次重试）。
    """
    uid = str(user["id"])
    h._require_configured(uid)
    logger.info("create_plan_stream: user=%s input=%s mode=%s attachments=%d",
                user["username"], req.input[:100], req.mode, len(req.attachmentIds))
    source = _resolve_source(req, uid)

    def work():
        plan = h.coach.make_plan(source, uid)
        logger.info("create_plan_stream: ok title=%s modules=%d", plan.title, len(plan.modules))
        return store.create_document(source, plan, uid)

    async def event_stream():
        # LLM 调用放线程池; 每 30s 无结果就发心跳注释帧, 避免连接被中间层掐断
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            while True:
                try:
                    doc = await asyncio.wait_for(asyncio.shield(task), timeout=h.LLM_HEARTBEAT_SECONDS)
                    yield h._sse("done", doc.model_dump(mode="json"))
                    return
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except Exception as exc:
            logger.error("create_plan_stream: failed: %s", exc)
            yield h._sse("error", {"detail": _friendly_llm_error(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/api/plans")
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


@router.get("/api/plans/{plan_id}")
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
    doc = h._get_doc(plan_id, str(user["id"]))
    logger.info("get_plan: user=%s plan_id=%s title=%s", user["username"], plan_id, doc.plan.title)
    return doc


@router.delete("/api/plans/{plan_id}")
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


@router.post("/api/plans/{plan_id}/modules/{module_id}/content")
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
    h._require_configured(str(user["id"]))
    doc = h._get_doc(plan_id, str(user["id"]))
    module = h._get_module(doc, module_id)
    logger.info("generate_content: user=%s plan_id=%s module_id=%s", user["username"], plan_id, module_id)

    async def event_stream():
        nonlocal content
        stream_error: Exception | None = None
        try:
            async for kind, payload in h.coach.author_content_stream(doc.plan, module, str(user["id"])):
                if kind == "delta":
                    yield h._sse("delta", {"delta": payload})
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
                yield h._sse("done", updated.model_dump(mode="json"))
            except Exception as exc:
                stream_error = stream_error or exc

        if stream_error is not None:
            yield h._sse("error", {"detail": _friendly_llm_error(stream_error)})

    content = None
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/api/plans/{plan_id}/modules/{module_id}/content")
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
    module = h._get_module(h._get_doc(plan_id, str(user["id"])), module_id)
    if module.content is None:
        raise HTTPException(status_code=404, detail="content not generated")
    return module.content


@router.post("/api/plans/{plan_id}/modules/{module_id}/quiz")
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
    h._require_configured(uid)
    doc = h._get_doc(plan_id, uid)
    module = h._get_module(doc, module_id)
    logger.info("generate_quiz: user=%s plan_id=%s module_id=%s", user["username"], plan_id, module_id)

    def work():
        quiz = h.coach.make_quiz(doc.plan, module, uid)
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
                    updated = await asyncio.wait_for(asyncio.shield(task), timeout=h.LLM_HEARTBEAT_SECONDS)
                    yield h._sse("done", updated.model_dump(mode="json"))
                    return
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except Exception as exc:
            logger.error("generate_quiz: failed: %s", exc)
            yield h._sse("error", {"detail": _friendly_llm_error(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/api/plans/{plan_id}/modules/{module_id}/quiz")
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
    module = h._get_module(h._get_doc(plan_id, str(user["id"])), module_id)
    if module.quiz is None:
        raise HTTPException(status_code=404, detail="quiz not generated")
    return module.quiz


@router.put("/api/plans/{plan_id}/modules/{module_id}/answers")
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
    h._get_module(h._get_doc(plan_id, str(user["id"])), module_id)

    def mutate(m):
        m.answers = {**(m.answers or {}), **req.answers}

    return store.update_module(plan_id, module_id, mutate, str(user["id"]))


@router.get("/api/plans/{plan_id}/modules/{module_id}/answers")
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
    module = h._get_module(h._get_doc(plan_id, str(user["id"])), module_id)
    answers = module.answers or {}
    total = len(module.quiz.questions) if module.quiz else 0
    answered = sum(1 for v in answers.values() if v and v.strip())
    return AnswersState(answers=answers, answered=answered, total=total)


@router.post("/api/plans/{plan_id}/modules/{module_id}/grade")
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
    h._require_configured(uid)
    doc = h._get_doc(plan_id, uid)
    module = h._get_module(doc, module_id)
    if module.quiz is None:
        raise HTTPException(status_code=404, detail="quiz not generated")
    answers = module.answers or {}
    if not answers:
        raise HTTPException(status_code=400, detail="no saved answers to grade; PUT .../answers first")

    def work():
        return h.coach.grade_quiz(doc.plan, module, answers, uid)

    async def event_stream():
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            while True:
                try:
                    result = await asyncio.wait_for(asyncio.shield(task), timeout=h.LLM_HEARTBEAT_SECONDS)

                    def mutate(m):
                        m.result = result
                        m.status = ModuleStatus.completed

                    updated = store.update_module(plan_id, module_id, mutate, uid)
                    logger.info("grade_quiz: ok user=%s plan_id=%s module_id=%s score=%.1f/%.1f",
                                user["username"], plan_id, module_id, result.totalScore, result.maxScore)
                    yield h._sse("done", updated.model_dump(mode="json"))
                    return
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except Exception as exc:
            logger.error("grade_quiz: failed: %s", exc)
            yield h._sse("error", {"detail": _friendly_llm_error(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.patch("/api/plans/{plan_id}/modules/{module_id}")
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
    h._get_module(h._get_doc(plan_id, str(user["id"])), module_id)

    def mutate(m):
        m.status = patch.status

    return store.update_module(plan_id, module_id, mutate, str(user["id"]))


@router.put("/api/plans/{plan_id}/modules/{module_id}/content")
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
    doc = h._get_doc(plan_id, str(user["id"]))
    module = h._get_module(doc, module_id)
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


@router.put("/api/plans/order")
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


