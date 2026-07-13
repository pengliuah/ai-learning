# 智学助手 - 学习 Agent 设计规格

- 日期: 2026-07-10
- 状态: 设计已确认，待评审
- 变更: LLM 供应商改用 火山引擎方舟 (Volcengine Ark, OpenAI 兼容); 引入 Python 标准库 logging 日志框架 (2026-07-13)

## 1. 概述

一个 AI 学习助手：根据输入的学习资料或主题提示，自动生成学习规划、各模块学习内容、测验，并对测验打分、给出评估，支持进度跟踪与多计划管理。

## 2. 目标与非目标

目标 (v1):

- 输入: 主题/提示 或 粘贴的学习资料文本
- 生成结构化学习计划 (多模块)
- 按模块生成学习内容 (Markdown)
- 生成测验 (单选 + 简答)
- 自动打分 + 评估 (优势/不足/建议)
- 进度跟踪 (模块状态、整体进度) + 持久化 + 多计划

非目标 (v1):

- 文件上传 (PDF/DOCX) 解析
- URL 抓取
- 多模型供应商切换
- 纯对话式 UI
- 用户账号/鉴权

## 3. 技术栈

- 前端: Vite + React + TypeScript, Tailwind CSS, react-markdown + remark-gfm, lucide-react, TanStack Query
- 后端: FastAPI (Python), LangChain DeepAgents, 火山引擎方舟 (Volcengine Ark, OpenAI 兼容)
- 模型接入: langchain-openai 的 ChatOpenAI 指向 Ark endpoint (base_url=[https://ark.cn-beijing.volces.com/api/v3](https://ark.cn-beijing.volces.com/api/v3))
- 环境: uv 管理 Python 隔离环境; Node/npm 管理前端
- 持久化: JSON 文件存储 (backend/data/plans.json)
- 日志: Python 标准库 logging (无新依赖, 与 uvicorn 日志共享 stderr)
- 默认模型: doubao-1.5-pro-32k (经 ARK_API_KEY, 可用端点 ID 覆盖)

## 4. 架构

两个本地进程:

- 前端 (Vite, :5173) 经代理 /api -> 后端 (FastAPI, :8000)
- 后端: FastAPI 路由 -> DeepAgents 生成 -> 存储层 -> JSON 文件
- 数据流: 浏览器 -> React -> /api -> FastAPI -> {DeepAgents, Store} -> Ark / plans.json

交互模型: 结构化仪表盘 (非对话式)。前端按步骤触发后端端点，后端调用对应子代理生成结构化结果并持久化。

## 5. 后端

### 5.1 模块划分 (隔离与接口)

- app/main.py - FastAPI 应用、路由、CORS、生产静态托管
- app/config.py - 环境变量加载 (ARK_API_KEY, ARK_BASE_URL, ARK_MODEL) + 日志初始化 (setup_logging)
- app/llm.py - 构造指向火山方舟的 ChatOpenAI (base_url, api_key, model)
- app/agent.py - DeepAgents 学习教练 + 4 个子代理
- app/schemas.py - Pydantic 模型
- app/store.py - JSON 存储仓库 (读写/锁)
每个模块单一职责，可独立测试。

### 5.2 代理 (DeepAgents)

agent.py 构造 ChatOpenAI(base_url=ARK_BASE_URL, api_key=ARK_API_KEY, model=ARK_MODEL) 指向火山方舟，作为 DeepAgents 的模型实例传入。学习教练 (supervisor) 持有共享状态 (当前计划 + 源资料)，下设 4 个子代理，各自返回结构化 Pydantic 输出 (经 function calling / JSON mode，Ark 支持):

- Planner: 资料/主题 -> Plan
- ContentAuthor: 模块 -> Content (markdown + keyTakeaways)
- Quizzer: 模块+内容 -> Quiz (MCQ + 简答)
- Grader: 测验+答案 -> GradingResult
端点调用对应子代理并持久化结果。(DeepAgents 的确切工厂/import 在安装后对照包确认。)

### 5.3 数据模型

plans.json = { planId: Document }

- Plan: title, goal, summary, level, totalMinutes, modules[]
- Module: id, title, summary, objectives[], minutes, difficulty, status, content?, quiz?, result?
- Content: markdown, keyTakeaways[]
- Quiz: questions[] (type mcq|short, options, answer|modelAnswer+keyPoints, explanation)
- GradingResult: results[] (score, correct, feedback), totalScore, maxScore, assessment{strengths, weaknesses, recommendations, level}
模块状态: not_started / studying / completed (含分数)，由已存产物派生。

### 5.4 API 端点 (FastAPI)

- GET /api/health -> {configured, model}
- POST /api/plans {input, mode} -> Plan (mode: topic|materials)
- GET /api/plans -> 计划列表 (id, title, createdAt, progress)
- GET /api/plans/{id} -> 完整文档
- DELETE /api/plans/{id}
- POST|GET /api/plans/{id}/modules/{mid}/content
- POST|GET /api/plans/{id}/modules/{mid}/quiz
- POST /api/plans/{id}/modules/{mid}/grade {answers} -> GradingResult
- PATCH /api/plans/{id}/modules/{mid} {status}
内容生成走 SSE 流式; 其余返回 JSON。输出语言与输入一致。

### 5.5 配置

环境变量: ARK_API_KEY (必需, 火山方舟 API Key), ARK_BASE_URL (可选, 默认 [https://ark.cn-beijing.volces.com/api/v3](https://ark.cn-beijing.volces.com/api/v3)), ARK_MODEL (可选, 默认 doubao-1.5-pro-32k, 可用推理端点 ID ep-xxx 覆盖)。缺失 ARK_API_KEY 时 /api/health 返回 configured=false。

LOG_LEVEL (可选, 默认 INFO, 可设 DEBUG 输出存储层详细日志)。


### 5.6 日志

- **框架**: Python 标准库 `logging`，不引入第三方依赖
- **初始化**: `config.py` 提供 `setup_logging()`，由 `app/__init__.py` 在导入时调用一次；配置 `app` logger 层级，各模块用 `logging.getLogger(__name__)` 继承
- **格式**: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`，输出到 stderr (与 uvicorn 同流)
- **级别**: 由 `LOG_LEVEL` 环境变量控制，默认 `INFO`
- **各层记录内容**:
    - 路由 (main.py, INFO): 请求入口参数 (input 截断 100 字符、mode、plan_id、module_id)；结果摘要 (计划标题+模块数、测验题数、分数/满分、内容长度)；错误 (502/503/404/400 含上下文)
    - 代理 (agent.py, INFO): LLM 调用入口 (agent key、输入长度)；结构化返回摘要 (模块数、题数、分数)；重试 (WARNING)；内容流结束 (总字符数、keyTakeaways 数)
    - 存储 (store.py, DEBUG): CRUD 操作 (plan_id、module_id、命中/未命中)；默认不输出，LOG_LEVEL=DEBUG 时可见
- **不记录**: API Key (绝不记录)；完整 LLM prompt/response (过长)；完整内容 Markdown (过大)
- **与错误处理的关系**: Section 7 中"存储错误: 记录 + 500"的"记录"即指通过本日志框架输出 ERROR 级日志

## 6. 前端

视图:

- 首页: 计划列表 + 进度，"新建计划"
- 新建计划: 主题/资料 分段控件 + 文本框 + 生成
- 计划详情: 目标/等级/总时长 + 整体进度 + 模块列表 (状态徽章)
- 模块详情: 内容/测验 标签; 无内容时"生成内容"
- 测验: 作答 + 提交
- 结果: 分数 + 评估 + 逐题回顾 + 重做/下一模块

状态: TanStack Query 管理服务端状态; react-markdown 渲染内容; lucide-react 图标。UI 文案中文。设计风格: 安静、工具化、可扫描、可预测导航 (符合学习/操作类应用)。

## 7. 错误处理

- 缺 key: /api/health 报未配置，前端显示提示; 生成端点返回 503
- LLM/结构化输出失败: 重试一次 (纠正提示)，仍失败返回 502
- 模块/计划不存在: 404
- 存储错误: 记录 + 500

## 8. 测试

- 后端 pytest: mock LLM (返回预设结构化 JSON)，覆盖 store CRUD、schema 校验、端点 happy path。不调真实 Ark。
- 前端 Vitest + RTL: 测验作答、结果渲染、进度计算。
- 手动冒烟: 跑通 主题->计划->内容->测验->评分 全流程。

## 9. 开发环境与运行

Python (uv):

- 已初始化: backend/ (zhixue-backend)，.venv (Python 3.14)
- 安装依赖: cd backend; uv add fastapi "uvicorn[standard]" langchain langchain-openai langchain-core pydantic deepagents (需网络)
- 运行: uv run uvicorn app.main:app --reload --port 8000

前端:

- npm create vite frontend -- --template react-ts; cd frontend; npm i; npm run dev (Vite 代理 /api -> :8000)

环境变量: 运行后端前设置 ARK_API_KEY (与可选 ARK_MODEL)。

注: 沙箱当前阻止网络，后端依赖安装需联网 (实施阶段会请求网络权限)。

## 10. 风险与待确认

- 火山方舟模型/端点: 确认实际使用的模型名或推理端点 ID; ARK_MODEL 可配置
- DeepAgents + 自定义 base_url: 确认 DeepAgents 接受指向 Ark 的 ChatOpenAI 实例 (预期可行，因 Ark 为 OpenAI 兼容)
- 结构化输出: 确认所选 Ark 模型支持 function calling / JSON mode
- DeepAgents 包名/API: 安装后对照确认 (deepagents vs langchain-deepagents)
- 网络受限: pip/uv/npm 安装与运行时调 Ark 均需网络，沙箱当前阻止
- Python 3.14 兼容性: 部分包可能尚无 3.14 wheel; 必要时改用 3.12
- backend/.git: uv init 自动创建，将并入根仓库时移除