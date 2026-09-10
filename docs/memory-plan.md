# 教练对话长期记忆接入计划（Mem0 + pgvector）v1

> 2026-09-06 起草，供评审可行性。对应调研：Mem0 OSS v2.0.20（Apache-2.0），
> 测试库 pgvector 0.8.6 已就绪（镜像 pgvector/pgvector:pg16，扩展已建）。

## 1. 要解决的问题

教练对话（/api/coach/stream）目前只有**会话内临时记忆**：前端把历史对话
重发上来，服务端 `app/memory.py` 做 trim + 摘要压缩。换一个会话、隔一天、
换台设备，教练对孩子学过什么、哪里薄弱、之前约定过什么，一概不知。

目标：给每个用户加**跨会话长期记忆**——教练自动记住学习偏好、薄弱点、
目标约定，开场即带上下文；同时提供记忆管理入口（能看、能删）。

定位：Mem0 管长期事实记忆，现有 `memory.py` 继续管会话内短期上下文，
两层互补，不替换。

## 2. 技术选型（已验证可行）

| 项 | 选择 | 依据 |
|---|---|---|
| 记忆引擎 | mem0ai（OSS，pip 进程内 SDK） | 不加 REST 容器，FastAPI 直接 import |
| 向量库 | mem0 的 pgvector 后端 → 现有 Postgres | 零新增服务；测试库已验证 HNSW/距离查询可用 |
| 抽取 LLM | 复用用户自己的模型配置 | `user_model_settings` 是 OpenAI 兼容 base_url，mem0 的 openai LLM 支持 base_url；费用记到该用户 |
| Embedding | 系统级统一配置（.env，见决策点 D1） | embedding 模型全局一个，维度一致，避免 per-user 差异 |
| 隔离 | mem0 原生 `user_id` scope | 与多用户体系天然对齐 |

## 3. 数据流

```
写入: coach 对话结束(finally) ──后台任务──> mem0.add(本轮 goal+回复, user_id)
        └─ mem0 内部: 召回旧记忆 → LLM 抽取事实(1次调用) → 去重 → pgvector + history 落库
        └─ 失败只 warn, 不影响对话本身

读取: _build_coach_messages() 里 ──> mem0.search(goal, user_id, limit=5)
        └─ 命中的事实拼成 "[该生的长期记忆] ..." 前缀进 system prompt
```

- 记忆存在 mem0 自建的一张 pgvector 表 + SQLite 审计 history（路径指到
  `backend/data` 挂载卷），不侵入现有业务表。
- 用户注销/清数据时 `delete_all(user_id=user_id)` 一并清掉。

## 4. 改动清单

**后端**
- `requirements.txt`: + mem0ai
- `app/long_memory.py`（新建）：
  - 系统级 embedding 配置读取（.env：`MEMORY_EMBEDDING_BASE_URL/KEY/MODEL/DIMS`）；
  - `MemoryManager`：按 (api_key, base_url, model) 缓存 mem0 `Memory` 实例
    （LRU 上限 8，防止 per-user 模型导致连接池泛滥）；
  - `recall(user_id, query) -> str`、`remember(user_id, messages)`（带 try/except 兜底）；
  - custom_instructions 注入：忽略密码/身份证等敏感信息、以学生视角记学习事实。
- `app/agent.py`：`_build_coach_messages` 加 recall 前缀；`coach_stream` finally 里
  `asyncio.create_task(remember(...))`。
- token 计量：抽取调用的 usage 记 `token_usage(gen_type='memory')`，模型设置页可见。
- `app/main.py` + `schemas.py`：`GET /api/memories`、`DELETE /api/memories/{id}`（P2 再挂前端）。
- `deploy.sh`：已有 pgvector 扩展幂等步骤；无需再改（需重建后端镜像）。

**前端（P2）**
- 「我的记录」页（原书签页 `/bookmarks`）：长期记忆区块（列表 / 删除 / 总开关）+ 书签列表。

## 5. 成本估算

- 每次 coach 对话结束：1 次 LLM 抽取调用（约几百 token，走用户自己的 key）+ 1~N 次 embedding（走系统 key）。
- 每次提问前：1 次 embedding + 1 次向量查询（pgvector 本地，无外部调用）。
- mem0 有 MD5 哈希去重，重复内容不重复入库，但抽取调用照跑——用量异常时再加节流（见 D2）。

## 6. 阶段划分

| 阶段 | 内容 | 验收 |
|---|---|---|
| P1 核心（约 1 天） | 依赖 + long_memory.py + coach 读写 + token 计量 + 测试 | 测试环境对话「我叫XX，我喜欢天文」→ 新开会话问「还记得我吗」能答上 |
| P2 管理 UI | /api/memories + 记忆管理页（书签/记录页）+ 总开关 | 用户能看/删自己的记忆 |
| P3 可选 | custom_instructions 调优、批改/计划场景复用、节流策略 | 按效果决定 |

## 7. 风险与对策

- **per-user Memory 实例**（各带 LLM client + pgvector 连接池）：LRU 缓存上限 8 + 池 minconn=1。
- **SQLite history 单文件**：后端单容器单进程，路径放挂载卷 `backend/data`，与现有 data 文件同级。
- **embedding 维度一旦定死不可换模型**（换=清库重建）：D1 定好再动工。
- **mem0 v2 迭代快**：锁版本（如 `mem0ai==2.0.20`），升级单独评估。

## 8. 决策点（动工前需要拍板）

- **D1 embedding 模型**：推荐硅基流动/阿里云的 bge-m3 或 OpenAI text-embedding-3-small，
  配在 .env（需要你提供可用的 embedding API key，或告诉我用哪家）。
- **D2 写入节流**：推荐先每轮对话都写（实现最简），观察一周用量再决定是否
  改成每 N 轮/仅会话收尾时写。
- **D3 管理 UI**：P2 是否做、做到什么程度（只删 vs 可编辑）。
- **D4 范围**：本期只挂教练对话，批改/计划生成先不动。

---

## 9. P1 具体接入流程（评审稿 2026-09-06）

> 实测前提：向量模型配置已上线并保存（admin 配置了阿里云百炼
> `qwen3.7-text-embedding`，独立 Key/BaseURL，实测 `/embeddings` 通，**1024 维**）。

### 9.1 依赖与初始化

1. `backend/requirements.txt` 增加 `mem0ai==2.0.20`（锁版本）。
2. 装完先做导入冒烟：`from mem0 import Memory` + pgvector 后端可用（psycopg 已在依赖里）。

### 9.2 新模块 `backend/app/long_memory.py`

**配置组装**（每次构建 Memory 实例时从 DB 读）：
- LLM（抽取用）：`store.get_llm_config(user_id)` → mem0 的 OpenAI LLM 配置（带 base_url）；
- Embedding：`store.get_embedding_config(user_id)`（已含 Key/BaseURL 回退）→ mem0 的 OpenAI embedder；
- 向量库：`PGVectorConfig(connection_string=DATABASE_URL, collection_name=按维度命名, embedding_dims=<探测值>, hnsw=True)`；
- history：`history_db_path=backend/data/mem0_history.db`（挂载卷，随容器持久化）。

**维度 → 分表**：不同用户可能配不同维度的向量模型，同一张表维度必须一致。
首次构建时用该用户的 embedding 模型探测一次维度（embed 一句探针），collection
命名为 `zhixue_memory_{dims}`（当前即 `zhixue_memory_1024`）。探测结果随实例缓存。

**MemoryManager（模块级单例）**：
- 缓存键 `(llm_key_hash, llm_model, llm_base_url, emb_model, emb_base_url)` → mem0 `Memory` 实例；
- LRU 上限 8，逐出时关闭实例（释放 pgvector 连接池）；
- 用户改模型设置后：`put_model_settings` 里已调 `reset_model_runtime`，在其内部同步
  清空记忆实例缓存（改配置立即生效，不留旧连接）。

**两个入口**（全部 try/except 兜底，任何失败只打日志，绝不影响对话）：
- `async recall(user_id, query, limit=5) -> str`：`mem0.search`（走 to_thread 不堵事件循环），
  命中格式化为 `• 事实` 行；未配置/无命中返回 `""`。
- `async remember(user_id, goal: str, reply: str)`：后台任务（create_task + to_thread），
  把本轮「用户问 + 教练答」交给 `mem0.add`（mem0 内部 1 次 LLM 抽取 + 去重 + 入库）。

**custom_instructions**（写进 MemoryConfig）：
「用中文记录与学生学习相关的事实（年级/学科/薄弱点/偏好/约定）；忽略密码、
身份证等敏感信息；一段对话没有值得记的内容就返回空列表。」

### 9.3 挂接点（`app/agent.py`，共两处）

1. **读取**：`_build_coach_messages()` 里，trim/摘要完成后、追加本次 goal 之前：
   ```python
   mem = await long_memory.recall(user_id, goal)
   if mem:
       messages.insert(0, SystemMessage(content=f"[该学员的长期记忆，供参考]\n{mem}"))
   ```
2. **写入**：`coach_stream()` 里累计助手回复文本（现有 delta 循环加一个 list），
   `finally` 落库 usage 之后：
   ```python
   if assistant_text.strip():
       asyncio.create_task(long_memory.remember(user_id, goal, assistant_text))
   ```

### 9.4 抽取调用计量

自定义 mem0 LLM 子类（继承 `mem0.llms.openai.OpenAI`），重写 `generate_response`
捕获 `usage`，调 `store.record_token_usage(user_id, "memory", ...)`——抽取费用照旧
记到用户自己的用量统计（模型设置页可见「记忆」分类）。

### 9.5 测试与部署

- 单测（mock mem0，不起真库）：配置回退、维度分表命名、recall 格式化、
  失败兜底（LLM 抛异常 → 返回空/静默跳过）；
- 测试环境验收（真流程）：部署后和教练说「我叫XX，在读初一，喜欢天文」→
  **新开会话**问「还记得我吗」→ 应能答出；
- 部署即现有流程：`sudo bash scripts/deploy.sh test`（requirements 变更自动重建
  后端镜像；pgvector 扩展已就绪，mem0 首次使用时自建表）。

### 9.6 明确不做（P1）

- 记忆管理 API / 前端页（P2）
- 批改、计划生成等场景的记忆（P3）
- 写入节流（先每轮对话都写，观察用量后调）

### 9.7 审核前请注意一个前置问题

当前 admin 只配了**向量模型**，**大模型配置的 API Key 还是空的**。记忆抽取
（mem0.add 时「把对话提炼成事实」这一步）用的是**大模型配置**——不填的话，
对话照常进行，但记忆永远不会写入（每次 add 静默失败）。评审通过后请先把
大模型配置填好再验收。
