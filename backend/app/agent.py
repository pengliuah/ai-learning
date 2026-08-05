"""Learning coach built on DeepAgents (create_deep_agent) + LangGraph.

Verified against deepagents 0.6.12: create_deep_agent(model=BaseChatModel, ...,
response_format=<PydanticType>, subagents=[CompiledSubAgent], ...) returns a
LangGraph CompiledStateGraph; subagents return structured output via
``structured_response``. DeepAgents always binds tools (write_todos, filesystem,
task, ...), so the model must support function calling -- Ark/doubao does.

Architecture (design 5.2 hybrid):
- Planner / Quizzer / Grader are create_deep_agent graphs with response_format
  set to their Pydantic type; endpoints invoke them directly and read
  structured_response ("endpoints call the relevant sub-agent"). DeepAgents +
  LangGraph, for real.
- ContentAuthor streams markdown directly from a streaming ChatOpenAI for
  reliable token-by-token UX; a DeepAgents content graph is also wired as a
  supervisor subagent for the agentic coach path.
- A supervisor create_deep_agent(subagents=[...]) holds shared state and
  delegates via the built-in ``task`` tool (the 学习教练), exposed via
  /api/coach/stream using LangGraph astream_events.
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncIterator

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import SkillsMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from . import store
from .config import BACKEND_DIR
from .llm import build_chat_model, build_streaming_model
from .schemas import (
    Content,
    GradingResult,
    Module,
    ModuleStatus,
    Plan,
    PlanSource,
    Quiz,
)

logger = logging.getLogger(__name__)

KEY_TAKEAWAYS_HEADING = "## 关键要点"

DIRECTNESS = "直接以结构化结果作答，不要使用文件或命令工具，不要写待办。"

MATH_NOTATION = (
    r"公式与数学符号必须用 LaTeX 语法书写，并放在美元符定界符内，以便前端渲染："
    r"行内公式用 $...$（如 $F_{浮}=G-F^{\prime}$、$p=\rho g h$），独立公式用 $$...$$。"
    r"下标用 _{}（如 $F_{浮}$），数值与单位用 \text{} 包裹（如 $5\text{N}$）。"
    r"不要把公式、下标或单位写成纯文本（如 F浮、5N）。"
)

PLANNER_SYSTEM = (
    "你是一名专业的学习规划师。根据用户提供的主题或学习资料，"
    "设计一份结构化的学习计划。\n"
    "要求：\n"
    "- 产出 3~8 个递进式学习模块，每个模块聚焦一个子目标。\n"
    "- 为每个模块给出简短摘要、学习目标（2~5 条）、预计学习分钟数与难度。\n"
    "- 整体给出计划目标、概要、适用等级与总时长（分钟）。\n"
    "- 输出语言与用户输入语言保持一致。\n"
    + DIRECTNESS
)

CONTENT_SYSTEM = (
    "你是一名学习内容作者。针对给定学习模块，撰写高质量的 Markdown 学习内容。\n"
    "要求：\n"
    "- 内容结构清晰，使用标题、列表、代码块（如需要）。\n"
    "- 覆盖该模块的学习目标，循序渐进。\n"
    "- 结尾必须包含一个标题为「## 关键要点」的小节，用 3~6 条简洁要点总结。\n"
    "- 直接以消息形式输出 Markdown，不要使用文件或命令工具。\n"
    "- 输出语言与计划语言保持一致。\n"
    + MATH_NOTATION
)

QUIZ_SYSTEM = (
    "你是一名测验设计者。针对给定模块与学习内容，设计一份测验。\n"
    "要求：\n"
    "- 每道题 type 为 mcq（单选）或 short（简答）。\n"
    "- mcq 题给出 2~4 个 options 与唯一正确 answer，以及 explanation。\n"
    "- short 题给出 modelAnswer 与 2~5 条 keyPoints，以及 explanation。\n"
    "- 输出语言与计划语言保持一致。\n"
    + DIRECTNESS
    + MATH_NOTATION
)

GRADER_SYSTEM = (
    "你是一名严格公正的评分老师。根据测验题目与参考答案，对学生的作答进行评分。\n"
    "要求：\n"
    "- 每题给出 score、maxScore、correct（布尔）、feedback。\n"
    "- 给出 totalScore、maxScore 与整体 assessment（优势/不足/建议/等级）。\n"
    "- 简答题按要点命中度给分；输出语言与计划语言保持一致。\n"
    + DIRECTNESS
    + MATH_NOTATION
)

COACH_SYSTEM = (
    "你是一名学习教练（supervisor）。你持有当前计划与源资料作为共享状态，"
    "并通过 task 工具将任务委派给专门的子代理：planner（制定计划）、"
    "content_author（撰写模块内容）、quizzer（设计测验）、grader（批改测验）。"
    "根据用户目标决定委派哪个子代理，并把子代理返回的结果整合后回复用户。"
    "输出语言与用户输入语言保持一致。"
)

PLANNER_DESC = "根据主题或学习资料生成结构化学习计划（多模块）。当用户需要制定学习计划时使用。"
CONTENT_DESC = "为指定学习模块撰写 Markdown 学习内容。当需要生成模块学习内容时使用。"
QUIZ_DESC = "为指定模块与内容设计测验（单选+简答）。当需要生成测验时使用。"
GRADER_DESC = "根据测验题目与参考答案对学生作答评分。当需要批改测验时使用。"


class LearningCoach:
    """Supervisor + four structured-output sub-agents over Volcengine Ark."""

    def __init__(self) -> None:
        self._graphs: dict | None = None

    def _build(self) -> dict:
        if self._graphs is None:
            chat = build_chat_model()
            planner = create_deep_agent(model=chat, tools=[], response_format=Plan, system_prompt=PLANNER_SYSTEM)
            content = create_deep_agent(model=chat, tools=[], system_prompt=CONTENT_SYSTEM)
            quizzer = create_deep_agent(model=chat, tools=[], response_format=Quiz, system_prompt=QUIZ_SYSTEM)
            grader = create_deep_agent(model=chat, tools=[], response_format=GradingResult, system_prompt=GRADER_SYSTEM)
            subagents = [
                {"name": "planner", "description": PLANNER_DESC, "runnable": planner},
                {"name": "content_author", "description": CONTENT_DESC, "runnable": content},
                {"name": "quizzer", "description": QUIZ_DESC, "runnable": quizzer},
                {"name": "grader", "description": GRADER_DESC, "runnable": grader},
            ]
            # Custom tool: generate + persist a learning plan.
            # Reuses self.make_plan (planner sub-agent) and store.create_document.
            @tool
            def create_plan(input: str, mode: str = "topic") -> str:
                """生成学习计划并保存到数据库，返回计划 ID 和标题。
                当用户想要制定学习计划、规划学习路径时使用此工具。

                Args:
                    input: 学习主题（如"Python 装饰器"）或粘贴的学习资料文本
                    mode: "topic" 按主题规划，或 "materials" 基于资料规划

                Returns:
                    JSON: {"plan_id": "...", "title": "...", "modules": N}
                """
                plan = self.make_plan(PlanSource(input=input, mode=mode))
                doc = store.create_document(PlanSource(input=input, mode=mode), plan)
                return json.dumps(
                    {"plan_id": doc.id, "title": plan.title, "modules": len(plan.modules)},
                    ensure_ascii=False,
                )

            # SkillsMiddleware: progressive disclosure of IMA note/KB skill.
            # Shared FilesystemBackend so the agent's read_file can access
            # skill files under backend/skills/.
            fs_backend = FilesystemBackend(root_dir=str(BACKEND_DIR))
            skills_mw = SkillsMiddleware(backend=fs_backend, sources=["/skills/"])
            supervisor = create_deep_agent(
                model=chat,
                subagents=subagents,
                system_prompt=COACH_SYSTEM,
                tools=[create_plan],
                middleware=[skills_mw],
                backend=fs_backend,
            )
            self._graphs = {
                "planner": planner,
                "content": content,
                "quizzer": quizzer,
                "grader": grader,
                "supervisor": supervisor,
            }
        return self._graphs

    def _invoke_structured(self, key: str, user_text: str):
        graph = self._build()[key]
        messages = {"messages": [HumanMessage(content=user_text)]}
        logger.info("llm_invoke: agent=%s input_len=%d", key, len(user_text))
        try:
            result = graph.invoke(messages)
        except Exception as exc:
            logger.warning("llm_invoke: agent=%s failed, retrying: %s", key, exc)
            retry = user_text + "\n\n注意：上一次失败，请严格按结构化要求返回。"
            result = graph.invoke({"messages": [HumanMessage(content=retry)]})
        structured = result.get("structured_response")
        if structured is None:
            logger.error("llm_invoke: agent=%s produced no structured_response", key)
            raise RuntimeError(f"{key} produced no structured_response")
        logger.info("llm_invoke: agent=%s ok type=%s", key, type(structured).__name__)
        return structured

    def make_plan(self, source: PlanSource) -> Plan:
        mode_desc = "主题" if source.mode == "topic" else "学习资料"
        user = f"输入模式：{mode_desc}\n\n内容：\n{source.input}"
        logger.info("make_plan: mode=%s input=%s", source.mode, source.input[:100])
        plan = self._invoke_structured("planner", user)
        for idx, module in enumerate(plan.modules, start=1):
            if not module.id:
                module.id = f"m{idx}"
            module.status = ModuleStatus.not_started
            module.content = None
            module.quiz = None
            module.result = None
            module.answers = None
        if not plan.totalMinutes:
            plan.totalMinutes = sum(m.minutes for m in plan.modules)
        logger.info("make_plan: ok title=%s modules=%d totalMinutes=%d", plan.title, len(plan.modules), plan.totalMinutes)
        return plan

    async def author_content_stream(self, plan: Plan, module: Module) -> AsyncIterator[tuple[str, object]]:
        streaming = build_streaming_model()
        user = self._content_user(plan, module)
        parts: list[str] = []
        async for chunk in streaming.astream([SystemMessage(content=CONTENT_SYSTEM), HumanMessage(content=user)]):
            text = chunk.content
            if isinstance(text, str) and text:
                parts.append(text)
                yield ("delta", text)
        full = "".join(parts)
        markdown, key_takeaways = _split_key_takeaways(full)
        logger.info("author_content: module=%s chars=%d keyTakeaways=%d", module.id, len(markdown), len(key_takeaways))
        yield ("done", Content(markdown=markdown, keyTakeaways=key_takeaways))

    @staticmethod
    def _content_user(plan: Plan, module: Module) -> str:
        objectives = "；".join(module.objectives) if module.objectives else "（无）"
        return (
            f"计划：{plan.title}\n目标：{plan.goal}\n等级：{plan.level.value}\n\n"
            f"模块：{module.title}\n摘要：{module.summary}\n"
            f"学习目标：{objectives}\n难度：{module.difficulty.value}\n"
            f"预计时长：{module.minutes} 分钟\n\n请撰写该模块的 Markdown 学习内容。"
        )

    def make_quiz(self, plan: Plan, module: Module) -> Quiz:
        content_md = module.content.markdown if module.content else "（尚未生成内容，请基于模块摘要出题）"
        user = (
            f"计划：{plan.title}\n模块：{module.title}\n摘要：{module.summary}\n"
            f"学习目标：{'; '.join(module.objectives)}\n\n学习内容：\n{content_md}"
        )
        quiz = self._invoke_structured("quizzer", user)
        for idx, q in enumerate(quiz.questions, start=1):
            if not q.id:
                q.id = f"q{idx}"
        logger.info("make_quiz: module=%s questions=%d", module.id, len(quiz.questions))
        return quiz

    def grade_quiz(self, plan: Plan, module: Module, answers: dict[str, str]) -> GradingResult:
        """Grade the quiz from saved draft answers.

        ``answers`` maps questionId -> student answer text. After grading we
        write each student's raw answer back into QuestionResult.studentAnswer
        so the result page can show what was answered, not just the score.
        """
        quiz = module.quiz
        if quiz is None:
            raise ValueError("module has no quiz to grade")
        lines: list[str] = []
        for q in quiz.questions:
            student = answers.get(q.id, "")
            if q.type.value == "mcq":
                ref = f"正确答案：{q.answer}"
            else:
                ref = f"参考答案：{q.modelAnswer}；要点：{', '.join(q.keyPoints)}"
            lines.append(f"题目 {q.id}（{q.type.value}）：{q.prompt}\n{ref}\n学生作答：{student}")
        user = (
            f"计划：{plan.title}\n模块：{module.title}\n\n"
            + "\n\n".join(lines)
            + "\n\n请逐题评分并给出整体评估。"
        )
        result = self._invoke_structured("grader", user)
        if not result.maxScore:
            result.maxScore = float(len(quiz.questions))
        # 保留原始作答：批改结果里能回看学生当时答了什么
        for question_result in result.results:
            question_result.studentAnswer = answers.get(question_result.questionId, "")
        logger.info("grade_quiz: module=%s score=%.1f/%.1f", module.id, result.totalScore, result.maxScore)
        return result

    async def coach_stream(self, goal: str) -> AsyncIterator[tuple[str, object]]:
        """Run the DeepAgents supervisor and stream model/tool events."""
        supervisor = self._build()["supervisor"]
        logger.info("coach_stream: goal=%s", goal[:100])
        async for event in supervisor.astream_events(
            {"messages": [HumanMessage(content=goal)]}, version="v2"
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                text = getattr(chunk, "content", "") if chunk else ""
                if isinstance(text, str) and text:
                    yield ("delta", {"text": text})
            elif kind in ("on_tool_start", "on_tool_end"):
                name = event.get("name")
                if kind == "on_tool_end" and name == "create_plan":
                    output = event.get("data", {}).get("output")
                    if isinstance(output, str):
                        try:
                            info = json.loads(output)
                            yield ("plan_created", info)
                        except (json.JSONDecodeError, KeyError):
                            pass
                yield ("tool", {"event": kind, "name": name})


def _split_key_takeaways(text: str) -> tuple[str, list[str]]:
    idx = text.find(KEY_TAKEAWAYS_HEADING)
    if idx == -1:
        return text.strip(), []
    body = text[:idx].rstrip()
    tail = text[idx + len(KEY_TAKEAWAYS_HEADING):]
    points: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        stripped = re.sub(r"^\d+[.)]\s+", "", stripped)
        if stripped:
            points.append(stripped)
    return body, points