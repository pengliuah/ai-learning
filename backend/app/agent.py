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
  reliable token-by-token UX.
- The coach chat (/api/coach/stream) is a plain streaming ChatOpenAI
  conversation (no tools / no agent): the frontend detects plan-creation or
  search intent and routes to the structured plan flow.
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncIterator

from deepagents import create_deep_agent
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from . import ima, store
from .config import BACKEND_DIR, is_configured
from .llm import build_chat_model, build_streaming_model
from .schemas import (
    Content,
    GradingResult,
    Module,
    ModuleStatus,
    Plan,
    PlanSource,
    Quiz,
    SaveToImaResponse,
)

logger = logging.getLogger(__name__)


def _gen_strategy_suffix(gen_type: str) -> str:
    """Read the generation-strategy prompt for ``gen_type`` (plan/content/quiz).

    Returns ``""`` when the DB is unreachable or no strategy is set, so
    generation still works without configured settings.
    """
    try:
        row = store.get_gen_settings_row()
        s = (row.get(gen_type) or "").strip()
        return f"\n\n生成策略要求：\n{s}" if s else ""
    except Exception:
        return ""


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
    "你是一名学习教练助手，与用户进行自然的学习对话：解答概念、提供学习建议、鼓励和引导用户。\n"
    "你有两个工具，只在用户明确表达对应意图时才调用，日常闲聊与知识问答不要调用工具：\n"
    "- create_plan：用户明确想要制定/生成一份学习计划时调用，传入学习主题；调用后前端会跳转到新建计划页面并预填主题，你无需自行生成计划内容。\n"
    "- search_plans：用户想要查找/看看已有的学习计划时调用，传入搜索关键词（可为空表示全部）。\n"
    "调用工具后，根据返回结果用自然语言向用户说明。"
    "输出语言与用户输入语言保持一致。"
)

class LearningCoach:
    """Supervisor + four structured-output sub-agents over Volcengine Ark."""

    def __init__(self) -> None:
        self._graphs: dict | None = None
        self._chat_agent = None

    @staticmethod
    def _make_subagent(response_format, system_prompt):
        return create_deep_agent(
            model=build_chat_model(),
            tools=[],
            response_format=response_format,
            system_prompt=system_prompt,
        )

    def _build(self) -> dict:
        # Cache only the stateless sub-agents (StateBackend, no checkpointer ->
        # fresh state every invoke, no cross-invocation leakage).
        if self._graphs is None:
            self._graphs = {
                "planner": self._make_subagent(Plan, PLANNER_SYSTEM),
                "content": self._make_subagent(None, CONTENT_SYSTEM),
                "quizzer": self._make_subagent(Quiz, QUIZ_SYSTEM),
                "grader": self._make_subagent(GradingResult, GRADER_SYSTEM),
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
        user = f"输入模式：{mode_desc}\n\n内容：\n{source.input}" + _gen_strategy_suffix("plan")
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
            + _gen_strategy_suffix("content")
        )

    def make_quiz(self, plan: Plan, module: Module) -> Quiz:
        content_md = module.content.markdown if module.content else "（尚未生成内容，请基于模块摘要出题）"
        user = (
            f"计划：{plan.title}\n模块：{module.title}\n摘要：{module.summary}\n"
            f"学习目标：{'; '.join(module.objectives)}\n\n学习内容：\n{content_md}"
            + _gen_strategy_suffix("quiz")
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

    def save_to_ima(
        self,
        plan: Plan,
        module: Module | None = None,
        content_type: str | None = None,
        skill_prompt_override: str | None = None,
    ) -> SaveToImaResponse:
        """Save plan/module content as an IMA note.

        ``content_type`` controls what gets saved:
        - ``"plan"``: plan overview (title, goal, summary, module list)
        - ``"content"``: module learning content (markdown + key takeaways)
        - ``"quiz"``: module quiz questions (with correct answers + explanations)
        - ``"result"``: grading results (score, assessment, per-question review)

        Defaults to ``"plan"`` when no module, ``"content"`` when a module is given.
        """
        row = store.get_ima_settings_row()
        client_id = row["ima_client_id"]
        api_key = row["ima_api_key"]
        skill_prompt = (skill_prompt_override or row.get("ima_skill_prompt") or "").strip()

        if not client_id or not api_key:
            return SaveToImaResponse(
                ok=False, detail="IMA 凭证未配置，请先在设置中填写 Client ID 和 API Key")

        # Resolve effective content type
        ct = content_type or ("content" if module is not None else "plan")

        title, body = self._gather_for_ima(plan, module, ct)

        # If skill prompt is set and ARK is configured, use LLM to format
        if skill_prompt and is_configured():
            try:
                body = self._format_for_ima(body, skill_prompt)
            except Exception as exc:
                logger.warning("save_to_ima: LLM formatting failed, using raw: %s", exc)

        try:
            result = ima.import_note(client_id, api_key, body, title)
        except Exception as exc:
            logger.error("save_to_ima: IMA API failed: %s", exc)
            return SaveToImaResponse(ok=False, detail=str(exc))

        logger.info("save_to_ima: ok type=%s title=%s note_id=%s", ct, title, result.get("note_id", ""))
        return SaveToImaResponse(ok=True, noteId=result.get("note_id", ""), title=title)

    @staticmethod
    def _gather_for_ima(plan: Plan, module: Module | None, ct: str) -> tuple[str, str]:
        """Build (title, markdown_body) for the requested content type."""
        if ct == "plan":
            title = plan.title
            parts = [f"{plan.summary}", f"", f"**目标：** {plan.goal}", ""]
            for i, m in enumerate(plan.modules, 1):
                parts.append(f"## {i}. {m.title}")
                parts.append(m.summary)
                if m.objectives:
                    parts.append("**学习目标：** " + "；".join(m.objectives))
                parts.append(f"*难度：{m.difficulty.value} · 时长：{m.minutes} 分钟*")
                parts.append("")
            return title, "\n".join(parts)

        # All other types need a module
        if module is None:
            module = plan.modules[0] if plan.modules else None
        if module is None:
            return plan.title, plan.summary

        if ct == "content":
            title = f"{plan.title} - {module.title}"
            if module.content:
                body = module.content.markdown
                if module.content.keyTakeaways:
                    body += "\n\n## 关键要点\n" + "\n".join(f"- {p}" for p in module.content.keyTakeaways)
            else:
                body = module.summary or module.title
            return title, body

        if ct == "quiz":
            title = f"{plan.title} - {module.title}（测验）"
            if not module.quiz:
                return title, "该模块尚未生成测验"
            lines = [f"## 测验：{module.title}", ""]
            for i, q in enumerate(module.quiz.questions, 1):
                lines.append(f"### {i}. {q.prompt}")
                lines.append(f"*{('单选' if q.type.value == 'mcq' else '简答')}*")
                lines.append("")
                if q.type.value == "mcq":
                    for opt in q.options:
                        mark = " ✓" if opt == q.answer else ""
                        lines.append(f"- {opt}{mark}")
                    lines.append("")
                lines.append(f"> **解析：** {q.explanation}")
                if q.type.value == "short" and q.modelAnswer:
                    lines.append(f"> **参考答案：** {q.modelAnswer}")
                lines.append("")
            return title, "\n".join(lines)

        if ct == "result":
            title = f"{plan.title} - {module.title}（答案解析）"
            if not module.result:
                return title, "该模块尚未批改"
            r = module.result
            lines = [
                f"## 批改结果：{module.title}",
                f"**得分：{r.totalScore}/{r.maxScore}**",
                "",
            ]
            # Assessment
            if r.assessment.strengths:
                lines.append("### 优势")
                for s in r.assessment.strengths:
                    lines.append(f"- {s}")
                lines.append("")
            if r.assessment.weaknesses:
                lines.append("### 不足")
                for s in r.assessment.weaknesses:
                    lines.append(f"- {s}")
                lines.append("")
            if r.assessment.recommendations:
                lines.append("### 建议")
                for s in r.assessment.recommendations:
                    lines.append(f"- {s}")
                lines.append("")
            # Per-question review
            quiz = module.quiz
            lines.append("### 逐题解析")
            lines.append("")
            for i, qr in enumerate(r.results, 1):
                q = next((qq for qq in (quiz.questions if quiz else []) if qq.id == qr.questionId), None)
                if q:
                    mark = "✓" if qr.correct else "✗"
                    lines.append(f"#### {i}. {q.prompt} [{mark} {qr.score}/{qr.maxScore}]")
                    lines.append(f"- 你的答案：{qr.studentAnswer or '（未作答）'}")
                    if q.type.value == "mcq":
                        lines.append(f"- 正确答案：{q.answer or ''}")
                    elif q.modelAnswer:
                        lines.append(f"- 参考答案：{q.modelAnswer}")
                    lines.append(f"- 反馈：{qr.feedback}")
                    lines.append(f"- 解析：{q.explanation}")
                else:
                    lines.append(f"#### {i}. [{qr.questionId}] {qr.score}/{qr.maxScore}")
                    lines.append(f"- 反馈：{qr.feedback}")
                lines.append("")
            return title, "\n".join(lines)

        # Fallback: same as content
        title = f"{plan.title} - {module.title}"
        body = module.content.markdown if module.content else (module.summary or module.title)
        return title, body

    def _format_for_ima(self, content: str, skill_prompt: str) -> str:
        """Use the LLM to reformat content per the IMA skill prompt."""
        system = (
            "你是一名笔记整理助手。根据用户的保存策略要求，"
            "整理学习内容为适合保存到 IMA 笔记的 Markdown。"
            "保持核心内容完整，不要编造信息。直接输出 Markdown，不要添加额外说明。"
        )
        user = f"保存策略要求：\n{skill_prompt}\n\n待整理的学习内容：\n{content}"
        model = build_chat_model()
        result = model.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = result.content
        return text if isinstance(text, str) else str(text)

    def _build_chat_agent(self):
        # Lean LangChain agent: only create_plan / search_plans.
        # No filesystem / todos / execute / task tools (unlike create_deep_agent),
        # so normal chat won't trigger tool calls. The LLM calls a tool only when
        # it detects a clear intent. Cached (no checkpointer -> fresh state every
        # invoke).
        if self._chat_agent is None:
            @tool
            def create_plan(topic: str) -> str:
                """当用户明确想要制定/生成一份学习计划时调用，传入学习主题。调用后前端会跳转到新建计划页面并预填该主题，你无需自行生成计划内容。

                Args:
                    topic: 学习主题，例如 "Python 装饰器" 或 "机器学习基础"。
                """
                return json.dumps({"topic": topic}, ensure_ascii=False)

            @tool
            def search_plans(query: str) -> str:
                """搜索已有的学习计划。当用户想要查找/看看已有计划时调用。

                Args:
                    query: 搜索关键词（学习主题）；为空字符串时列出全部已有计划。
                """
                items = store.list_items(query.strip() or None)
                return json.dumps(
                    [{"id": i.id, "title": i.title, "progress": i.progress} for i in items],
                    ensure_ascii=False,
                )

            self._chat_agent = create_agent(
                model=build_streaming_model(),
                tools=[create_plan, search_plans],
                system_prompt=COACH_SYSTEM,
            )
        return self._chat_agent

    async def coach_stream(self, goal: str) -> AsyncIterator[tuple[str, object]]:
        """Run the chat agent: a normal conversation that calls create_plan /
        search_plans only when the LLM detects a clear intent."""
        agent = self._build_chat_agent()
        logger.info("coach_stream: goal=%s", goal[:100])
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=goal)]}, version="v2"
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                text = getattr(chunk, "content", "") if chunk else ""
                if isinstance(text, str) and text:
                    yield ("delta", {"text": text})
            elif kind == "on_tool_start":
                yield ("tool", {"phase": "start", "name": event.get("name")})
            elif kind == "on_tool_end":
                output = event.get("data", {}).get("output", "")
                if hasattr(output, "content"):
                    output = output.content
                yield ("tool", {"phase": "end", "name": event.get("name"), "output": str(output)})


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