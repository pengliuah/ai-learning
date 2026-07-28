"""FastAPI application: routes, CORS, JSON store, SSE streaming.

对外接口集中在下方路由函数。每个端点的 docstring 即 OpenAPI 描述
（可在 /docs 查看），同时作为接口契约文档。
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from . import store
from .agent import LearningCoach
from .config import BACKEND_DIR, is_configured, settings
from .middleware import AccessLogMiddleware
from .schemas import (
    AnswersState,
    CoachRequest,
    ModuleStatus,
    ModuleStatusPatch,
    PlanCreateRequest,
    PlanSource,
    SaveAnswersRequest,
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


def _require_configured() -> None:
    """未配置 ARK_API_KEY 时抛 503，统一拦截所有需要调用 LLM 的端点。"""
    if not is_configured():
        raise HTTPException(status_code=503, detail="ARK_API_KEY not configured")


def _get_doc(plan_id: str):
    """按 id 取计划文档；不存在则抛 404。"""
    doc = store.get_document(plan_id)
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
def health():
    """健康检查。

    探测后端是否就绪、是否已配置火山方舟 API Key。不调用任何 LLM，
    可直接用于存活/就绪探针（liveness/readiness probe）。

    返回:
        200 ``{"configured": bool, "model": str}``

        - ``configured``: 是否已设置 ``ARK_API_KEY``；为 false 时，
          所有需要 LLM 的生成端点会返回 503。
        - ``model``: 当前使用的模型名（``ARK_MODEL``，默认
          ``doubao-1.5-pro-32k``，可填推理端点 ID 如 ``ep-xxx``）。
    """
    return {"configured": is_configured(), "model": settings.ark_model}


@app.post("/api/plans")
def create_plan(req: PlanCreateRequest):
    """生成并创建一份学习计划。

    调用 DeepAgents Planner 子代理（``create_deep_agent`` +
    ``response_format=Plan``），根据主题或粘贴的学习资料生成结构化、
    多模块的学习计划，并持久化到 ``backend/data/plans.json``。
    模块 id 会被规范化，状态初始化为 ``not_started``。

    请求体 ``PlanCreateRequest``:
        - ``input`` (str): 主题描述，或粘贴的学习资料文本。
        - ``mode`` ("topic" | "materials"): "topic" 按主题规划；
          "materials" 基于资料规划。两者输出语言均与输入保持一致。

    返回:
        200 ``Document``: 完整计划文档，含 ``id``、``createdAt``、
        ``updatedAt``、``source``、``plan``（含 ``modules`` 列表）。

    错误:
        - 503: 未配置 ``ARK_API_KEY``。
        - 502: LLM 或结构化输出失败（已内置一次重试）。
    """
    _require_configured()
    logger.info("create_plan: input=%s mode=%s", req.input[:100], req.mode)
    try:
        plan = coach.make_plan(PlanSource(input=req.input, mode=req.mode))
    except Exception as exc:
        logger.error("create_plan: failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"plan generation failed: {exc}")
    doc = store.create_document(PlanSource(input=req.input, mode=req.mode), plan)
    logger.info("create_plan: ok plan_id=%s title=%s modules=%d", doc.id, plan.title, len(plan.modules))
    return doc


@app.get("/api/plans")
def list_plans():
    """列出所有计划（概要视图）。

    返回轻量列表，用于首页计划列表展示。进度按「已完成模块数 / 模块总数」计算。

    返回:
        200 ``list[PlanListItem]``，每项含:
        - ``id`` (str)
        - ``title`` (str)
        - ``createdAt`` (datetime)
        - ``progress`` (float, 0.0~1.0)
    """
    items = store.list_items()
    logger.info("list_plans: count=%d", len(items))
    return items


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: str):
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
    doc = _get_doc(plan_id)
    logger.info("get_plan: plan_id=%s title=%s", plan_id, doc.plan.title)
    return doc


@app.delete("/api/plans/{plan_id}")
def delete_plan(plan_id: str):
    """删除某份计划（及其全部模块产物）。

    路径参数:
        plan_id (str): 计划 id。

    返回:
        200 ``{"deleted": "<plan_id>"}``

    错误:
        404: 计划不存在。
    """
    if not store.delete_document(plan_id):
        raise HTTPException(status_code=404, detail="plan not found")
    logger.info("delete_plan: plan_id=%s", plan_id)
    return {"deleted": plan_id}


@app.post("/api/plans/{plan_id}/modules/{module_id}/content")
async def generate_content(plan_id: str, module_id: str):
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
        - 503: 未配置 ``ARK_API_KEY``（生成前拦截）。
        - 404: 计划或模块不存在。
        - 流中 error 事件: 生成或持久化失败。
    """
    _require_configured()
    doc = _get_doc(plan_id)
    module = _get_module(doc, module_id)
    logger.info("generate_content: plan_id=%s module_id=%s", plan_id, module_id)

    async def event_stream():
        nonlocal content
        try:
            async for kind, payload in coach.author_content_stream(doc.plan, module):
                if kind == "delta":
                    yield _sse("delta", {"delta": payload})
                elif kind == "done":
                    content = payload

            def mutate(m):
                m.content = content
                if m.status == ModuleStatus.not_started:
                    m.status = ModuleStatus.studying

            updated = store.update_module(plan_id, module_id, mutate)
            logger.info("generate_content: ok module_id=%s chars=%d", module_id, len(content.markdown) if content else 0)
            yield _sse("done", updated.model_dump(mode="json"))
        except Exception as exc:
            yield _sse("error", {"detail": str(exc)})

    content = None
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/plans/{plan_id}/modules/{module_id}/content")
def get_content(plan_id: str, module_id: str):
    """读取某模块已生成的学习内容。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    返回:
        200 ``Content``: ``{"markdown": str, "keyTakeaways": list[str]}``。

    错误:
        - 404: 计划/模块不存在，或该模块尚未生成内容。
    """
    module = _get_module(_get_doc(plan_id), module_id)
    if module.content is None:
        raise HTTPException(status_code=404, detail="content not generated")
    return module.content


@app.post("/api/plans/{plan_id}/modules/{module_id}/quiz")
def generate_quiz(plan_id: str, module_id: str):
    """为某模块生成测验。

    调用 DeepAgents Quizzer 子代理（``response_format=Quiz``），基于模块内容
    （若无内容则基于摘要）生成单选 + 简答题，并写回该模块。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    返回:
        200 ``Document``: 更新后的完整计划文档（该模块含 ``quiz``）。

    错误:
        - 503: 未配置 ``ARK_API_KEY``。
        - 404: 计划或模块不存在。
        - 502: LLM 或结构化输出失败（已内置一次重试）。
    """
    _require_configured()
    doc = _get_doc(plan_id)
    module = _get_module(doc, module_id)
    try:
        quiz = coach.make_quiz(doc.plan, module)
    except Exception as exc:
        logger.error("generate_quiz: failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"quiz generation failed: {exc}")

    def mutate(m):
        m.quiz = quiz
        # Regenerating the quiz invalidates any prior grading result and saved
        # draft answers (they reference old question ids).
        m.result = None
        m.answers = None

    logger.info("generate_quiz: plan_id=%s module_id=%s questions=%d", plan_id, module_id, len(quiz.questions))
    return store.update_module(plan_id, module_id, mutate)


@app.get("/api/plans/{plan_id}/modules/{module_id}/quiz")
def get_quiz(plan_id: str, module_id: str):
    """读取某模块已生成的测验。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    返回:
        200 ``Quiz``: ``{"questions": [Question...]}``。

    错误:
        - 404: 计划/模块不存在，或该模块尚未生成测验。
    """
    module = _get_module(_get_doc(plan_id), module_id)
    if module.quiz is None:
        raise HTTPException(status_code=404, detail="quiz not generated")
    return module.quiz


@app.put("/api/plans/{plan_id}/modules/{module_id}/answers")
def save_answers(plan_id: str, module_id: str, req: SaveAnswersRequest):
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
    _get_module(_get_doc(plan_id), module_id)

    def mutate(m):
        m.answers = {**(m.answers or {}), **req.answers}

    return store.update_module(plan_id, module_id, mutate)


@app.get("/api/plans/{plan_id}/modules/{module_id}/answers")
def get_answers(plan_id: str, module_id: str):
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
    module = _get_module(_get_doc(plan_id), module_id)
    answers = module.answers or {}
    total = len(module.quiz.questions) if module.quiz else 0
    answered = sum(1 for v in answers.values() if v and v.strip())
    return AnswersState(answers=answers, answered=answered, total=total)


@app.post("/api/plans/{plan_id}/modules/{module_id}/grade")
def grade_quiz(plan_id: str, module_id: str):
    """批改某模块测验并给出评估（从已保存草稿批改）。

    调用 DeepAgents Grader 子代理（``response_format=GradingResult``），
    从该模块已保存的 ``answers`` 草稿读取作答逐题评分并给出整体评估。
    批改后把每题原始作答写回 ``QuestionResult.studentAnswer``，结果页可回看
    学生当时答了什么（不只是分数）。结果写回该模块，状态置为 ``completed``。

    典型流程: ``PUT .../answers``（随答随存草稿） -> ``POST .../grade``（批改）。

    路径参数:
        - plan_id (str): 计划 id。
        - module_id (str): 模块 id。

    返回:
        200 ``Document``: 更新后的完整计划文档（该模块含 ``result``，
        且 ``status`` 为 ``completed``）。

    错误:
        - 503: 未配置 ``ARK_API_KEY``。
        - 404: 计划/模块不存在，或该模块尚未生成测验。
        - 400: 没有已保存作答（需先 ``PUT .../answers``）。
        - 502: LLM 或结构化输出失败（已内置一次重试）。
    """
    _require_configured()
    doc = _get_doc(plan_id)
    module = _get_module(doc, module_id)
    if module.quiz is None:
        raise HTTPException(status_code=404, detail="quiz not generated")
    answers = module.answers or {}
    if not answers:
        raise HTTPException(status_code=400, detail="no saved answers to grade; PUT .../answers first")
    try:
        result = coach.grade_quiz(doc.plan, module, answers)
    except Exception as exc:
        logger.error("grade_quiz: failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"grading failed: {exc}")

    def mutate(m):
        m.result = result
        m.status = ModuleStatus.completed

    logger.info("grade_quiz: plan_id=%s module_id=%s score=%.1f/%.1f", plan_id, module_id, result.totalScore, result.maxScore)
    return store.update_module(plan_id, module_id, mutate)


@app.patch("/api/plans/{plan_id}/modules/{module_id}")
def patch_module_status(plan_id: str, module_id: str, patch: ModuleStatusPatch):
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
    _get_module(_get_doc(plan_id), module_id)

    def mutate(m):
        m.status = patch.status

    return store.update_module(plan_id, module_id, mutate)


@app.post("/api/coach/stream")
async def coach_stream(req: CoachRequest):
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
        - 503: 未配置 ``ARK_API_KEY``。
        - 流中 error 事件: 运行失败。
    """
    _require_configured()
    logger.info("coach_stream: goal=%s", req.goal[:100])

    async def event_stream():
        try:
            async for kind, payload in coach.coach_stream(req.goal):
                yield _sse(kind, payload)
            yield _sse("done", {"ok": True})
        except Exception as exc:
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(event: str, data) -> str:
    """格式化一条 SSE 事件帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# --- 生产静态托管: 前端构建产物 ---
_frontend_dist = BACKEND_DIR.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        """非 API 路径返回 index.html，交给前端路由处理 (SPA)。"""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(_frontend_dist / "index.html")
