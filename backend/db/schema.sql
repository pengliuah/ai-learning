-- ============================================================================
-- zhixue (智学助手) PostgreSQL schema
-- Replaces backend/data/plans.json with a normalized relational structure.
--
-- 一键建库建表 (psql):
--   psql -U postgres -d postgres -f backend/db/schema.sql
--   先连 postgres 维护库 → 脚本自动建 zhixue 库 → \connect 切换 → 建表
-- 应用启动时 db.init_schema() 也会自动完成建库 + 建表。
-- ============================================================================

-- ── 建库 (幂等, 需在 postgres 维护库中执行) ──────────────────────────────
-- CREATE DATABASE 不支持 IF NOT EXISTS, 用 psql \gexec 实现幂等。
SELECT 'CREATE DATABASE zhixue'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zhixue')\gexec

-- 切换到 zhixue 库, 以下建表语句在其上执行
\connect zhixue

-- Reusable trigger function: auto-update updated_at on row modification.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- users  —  account system (username/email + password, roles)
--
-- `role` gates admin-only endpoints; per-user data is scoped via
-- plans.user_id and the user_* settings tables below. wechat_* are reserved
-- for a future WeChat integration (unionid unifies accounts across apps).
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT NOT NULL UNIQUE,
    email         TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user'
                  CHECK (role IN ('admin', 'user')),
    wechat_unionid TEXT UNIQUE,
    wechat_openid  TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- refresh_tokens  —  opaque refresh tokens, hashed at rest
--
-- Rotated on every use: the presented token is revoked and a new row is
-- inserted. Re-presenting a revoked token revokes all of the user's tokens
-- (replay of a possibly-stolen token). Logout revokes explicitly.
-- ---------------------------------------------------------------------------
CREATE TABLE refresh_tokens (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked    BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_tokens_user ON refresh_tokens (user_id);

-- ---------------------------------------------------------------------------
-- plans  —  one row per learning plan (the top-level Document)
--
-- `user_id` scopes every plan to its owning account.
-- ---------------------------------------------------------------------------
CREATE TABLE plans (
    id            UUID PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    goal          TEXT NOT NULL DEFAULT '',
    summary       TEXT NOT NULL DEFAULT '',
    level         TEXT NOT NULL DEFAULT 'intermediate'
                  CHECK (level IN ('beginner', 'intermediate', 'advanced')),
    total_minutes INTEGER NOT NULL DEFAULT 0,
    source_input  TEXT NOT NULL,
    source_mode   TEXT NOT NULL DEFAULT 'topic'
                  CHECK (source_mode IN ('topic', 'materials')),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER plans_set_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_plans_user ON plans (user_id);

-- ---------------------------------------------------------------------------
-- modules  —  one row per module within a plan
--
-- `key`   is the API-facing id ("m1", "module-1"); the UUID `id` is the
--         internal stable reference used by all child-table foreign keys.
-- `answers` holds the draft answer dict {questionId: text} as JSONB so the
--         PUT .../answers merge can be done atomically (jsonb ||).
-- ---------------------------------------------------------------------------
CREATE TABLE modules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id     UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    objectives  JSONB NOT NULL DEFAULT '[]'::jsonb,
    minutes     INTEGER NOT NULL DEFAULT 0,
    difficulty  TEXT NOT NULL DEFAULT 'medium'
                CHECK (difficulty IN ('easy', 'medium', 'hard')),
    status      TEXT NOT NULL DEFAULT 'not_started'
                CHECK (status IN ('not_started', 'studying', 'completed')),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    answers     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, key)
);
CREATE TRIGGER modules_set_updated_at
    BEFORE UPDATE ON modules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_modules_plan ON modules (plan_id);

-- ---------------------------------------------------------------------------
-- module_contents  —  1:1 with module, nullable
--
-- Separated from modules so the modules table stays narrow: the list-plans
-- query only needs module status (for progress), never the content body.
-- ---------------------------------------------------------------------------
CREATE TABLE module_contents (
    module_id     UUID PRIMARY KEY REFERENCES modules(id) ON DELETE CASCADE,
    markdown      TEXT NOT NULL DEFAULT '',
    key_takeaways JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER module_contents_set_updated_at
    BEFORE UPDATE ON module_contents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- questions  —  the module's "quiz" (1:N from module)
--
-- No separate quizzes table: a Quiz in the Pydantic model is just
-- { questions: [...] }. A quiz *is* the set of questions for a module.
-- Regenerating a quiz = DELETE old questions + INSERT new ones; the CASCADE
-- on grading_results → question_results cleans up dependent grading data.
-- ---------------------------------------------------------------------------
CREATE TABLE questions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id    UUID NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    key          TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('mcq', 'mcq_multi', 'short')),
    prompt       TEXT NOT NULL,
    options      JSONB NOT NULL DEFAULT '[]'::jsonb,
    answer       TEXT,
    answers      JSONB NOT NULL DEFAULT '[]'::jsonb,
    model_answer TEXT,
    key_points   JSONB NOT NULL DEFAULT '[]'::jsonb,
    explanation  TEXT NOT NULL DEFAULT '',
    sort_order   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (module_id, key)
);
CREATE INDEX idx_questions_module ON questions (module_id);

-- ---------------------------------------------------------------------------
-- grading_results  —  1:1 with module, nullable
--
-- Overall quiz score + assessment (strengths / weaknesses / recommendations).
-- Arrays are JSONB because they are always read/written as a unit with the
-- result and are never queried individually.
-- ---------------------------------------------------------------------------
CREATE TABLE grading_results (
    module_id        UUID PRIMARY KEY REFERENCES modules(id) ON DELETE CASCADE,
    total_score      NUMERIC(6,1) NOT NULL DEFAULT 0,
    max_score        NUMERIC(6,1) NOT NULL DEFAULT 0,
    strengths        JSONB NOT NULL DEFAULT '[]'::jsonb,
    weaknesses       JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations  JSONB NOT NULL DEFAULT '[]'::jsonb,
    assessment_level TEXT NOT NULL DEFAULT 'intermediate'
                     CHECK (assessment_level IN ('beginner', 'intermediate', 'advanced')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- question_results  —  per-question grading detail (1:N from grading_result)
--
-- question_key is a denormalized snapshot (TEXT, not FK to questions.id):
-- it records which question was graded. The lifecycle guarantee is that
-- regenerating a quiz clears both the old questions and the grading result,
-- so the snapshot is always consistent with the live quiz at grading time.
-- ---------------------------------------------------------------------------
CREATE TABLE question_results (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grading_module_id UUID NOT NULL REFERENCES grading_results(module_id) ON DELETE CASCADE,
    question_key      TEXT NOT NULL,
    score             NUMERIC(6,1) NOT NULL DEFAULT 0,
    max_score         NUMERIC(6,1) NOT NULL DEFAULT 0,
    correct           BOOLEAN NOT NULL DEFAULT false,
    feedback          TEXT NOT NULL DEFAULT '',
    student_answer    TEXT NOT NULL DEFAULT '',
    sort_order        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_qresults_grading ON question_results (grading_module_id);

-- ---------------------------------------------------------------------------
-- user_ima_settings  -  per-user IMA OpenAPI configuration
--
-- Stores IMA credentials + the skill prompt that controls how content is
-- formatted before saving to IMA. One row per user; empty values mean the
-- user has not configured IMA.
-- ---------------------------------------------------------------------------
CREATE TABLE user_ima_settings (
    user_id           UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    ima_client_id     TEXT NOT NULL DEFAULT '',
    ima_api_key       TEXT NOT NULL DEFAULT '',
    ima_skill_prompt  TEXT NOT NULL DEFAULT '',
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER user_ima_settings_set_updated_at
    BEFORE UPDATE ON user_ima_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- user_gen_settings  -  per-user generation strategy prompts
--
-- One row per (user, generation type). Each row's ``strategy`` text is
-- appended to the LLM prompt when generating that type of content, letting
-- users steer generation without code changes.
-- ---------------------------------------------------------------------------
CREATE TABLE user_gen_settings (
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gen_type          TEXT NOT NULL CHECK (gen_type IN ('plan', 'content', 'quiz', 'grade')),
    strategy          TEXT NOT NULL DEFAULT '',
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, gen_type)
);
CREATE TRIGGER user_gen_settings_set_updated_at
    BEFORE UPDATE ON user_gen_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- user_model_settings  -  per-user LLM (Ark/OpenAI 兼容) connection
--
-- API Key / 模型 / Base URL 在网页「模型设置」中配置并保存到此表（按用户）。
-- 空值回退到 ARK_* 环境变量及内置默认值，因此环境变量仍可作为部署级的
-- 初始配置。
-- embedding_* 三列为「向量模型配置」：模型名必填才启用；Key / Base URL
-- 留空时运行期回退到大模型的对应值（同一服务商下常见）。
-- ---------------------------------------------------------------------------
CREATE TABLE user_model_settings (
    user_id             UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    api_key             TEXT NOT NULL DEFAULT '',
    model               TEXT NOT NULL DEFAULT '',
    base_url            TEXT NOT NULL DEFAULT '',
    max_tokens          INTEGER NOT NULL DEFAULT 8192,
    embedding_api_key   TEXT NOT NULL DEFAULT '',
    embedding_model     TEXT NOT NULL DEFAULT '',
    embedding_base_url  TEXT NOT NULL DEFAULT '',
    vision_api_key      TEXT NOT NULL DEFAULT '',
    vision_model        TEXT NOT NULL DEFAULT '',
    vision_base_url     TEXT NOT NULL DEFAULT '',
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER user_model_settings_set_updated_at
    BEFORE UPDATE ON user_model_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- user_memory_settings  -  长期记忆总开关（关掉=教练不写入不召回）
-- ---------------------------------------------------------------------------
CREATE TABLE user_memory_settings (
    user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled    BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER user_memory_settings_set_updated_at
    BEFORE UPDATE ON user_memory_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- user_memory_profile  -  学生画像（长期记忆的摘要层）
--
-- 夜间整理任务由记忆事实清单 LLM 总结生成；召回时先注入画像再注入原子事实。
-- 画像不是向量，直接存普通表。
-- ---------------------------------------------------------------------------
CREATE TABLE user_memory_profile (
    user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profile         TEXT NOT NULL DEFAULT '',
    edited_by_user  BOOLEAN NOT NULL DEFAULT false,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER user_memory_profile_set_updated_at
    BEFORE UPDATE ON user_memory_profile
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- memory_housekeeping  -  记忆夜间整理的推进水位
--
-- 记录每个用户上次被整理任务处理的时间；任务每轮挑选落后最久的用户处理。
-- ---------------------------------------------------------------------------
CREATE TABLE memory_housekeeping (
    user_id     UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER memory_housekeeping_set_updated_at
    BEFORE UPDATE ON memory_housekeeping
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- token_usage  -  per-user token 用量统计 (大模型 + 嵌入模型)
--
-- 每次 LLM/embedding 调用成功后写入一行 (按用户), 用于「模型设置」页展示
-- 今日 / 本月 / 累计的 token 消耗与请求次数。kind 区分模型类型:
-- 'llm' (大模型, AI 生成/抽取) 与 'embedding' (向量模型, 记忆检索向量化)。
-- 不涉及计费, 仅作统计。
-- ---------------------------------------------------------------------------
CREATE TABLE token_usage (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gen_type      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens  INTEGER NOT NULL DEFAULT 0,
    kind          TEXT NOT NULL DEFAULT 'llm',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_token_usage_user_created ON token_usage (user_id, created_at);

-- ---------------------------------------------------------------------------
-- annotations  -  per-user 学习内容批注 (Word 式笔记)
--
-- 用户在模块学习内容中选中文字添加的批注。锚定用 (plan_id, module_key) +
-- quote/prefix/suffix 三元组在渲染后 DOM 里重定位, 不 FK 到 modules.id
-- (保存/重新生成计划会重建模块行、更换 UUID)。内容重新生成后找不到原文的
-- 批注由前端标记为失效, 数据保留。
-- ---------------------------------------------------------------------------
CREATE TABLE annotations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id    UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    module_key TEXT NOT NULL DEFAULT '',
    quote      TEXT NOT NULL,
    prefix     TEXT NOT NULL DEFAULT '',
    suffix     TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER annotations_set_updated_at
    BEFORE UPDATE ON annotations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_annotations_user_plan ON annotations (user_id, plan_id);

-- ---------------------------------------------------------------------------
-- attachments  -  学习资料附件（全模态转写）
--
-- 原始文件存文件系统 (settings.attachments_dir, 部署时挂 docker 卷), 数据库只存
-- 相对路径 path; 后台用多模态模型把内容转写成 markdown 存 transcript；
-- transcript_status: pending/running/done/failed。
-- 计划创建与教练聊天通过 attachmentIds 引用附件的转写文本，两段式架构：
-- 全模态只做"文件→文本"的理解层，不进计划生成的结构化输出链路。
-- ---------------------------------------------------------------------------
CREATE TABLE attachments (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename          TEXT NOT NULL DEFAULT '',
    mime              TEXT NOT NULL DEFAULT '',
    size_bytes        INTEGER NOT NULL DEFAULT 0,
    path              TEXT NOT NULL DEFAULT '',
    transcript        TEXT NOT NULL DEFAULT '',
    transcript_status TEXT NOT NULL DEFAULT 'pending',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER attachments_set_updated_at
    BEFORE UPDATE ON attachments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_attachments_user ON attachments (user_id, created_at);
