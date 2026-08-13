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
-- plans  —  one row per learning plan (the top-level Document)
-- ---------------------------------------------------------------------------
CREATE TABLE plans (
    id            UUID PRIMARY KEY,
    title         TEXT NOT NULL,
    goal          TEXT NOT NULL DEFAULT '',
    summary       TEXT NOT NULL DEFAULT '',
    level         TEXT NOT NULL DEFAULT 'intermediate'
                  CHECK (level IN ('beginner', 'intermediate', 'advanced')),
    total_minutes INTEGER NOT NULL DEFAULT 0,
    source_input  TEXT NOT NULL,
    source_mode   TEXT NOT NULL DEFAULT 'topic'
                  CHECK (source_mode IN ('topic', 'materials')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER plans_set_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

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
    type         TEXT NOT NULL CHECK (type IN ('mcq', 'short')),
    prompt       TEXT NOT NULL,
    options      JSONB NOT NULL DEFAULT '[]'::jsonb,
    answer       TEXT,
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
-- ima_settings  -  single-row table for IMA OpenAPI configuration
--
-- Stores IMA credentials + the skill prompt that controls how content is
-- formatted before saving to IMA.  One row (id=1) per deployment.
-- ---------------------------------------------------------------------------
CREATE TABLE ima_settings (
    id                INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    ima_client_id     TEXT NOT NULL DEFAULT '',
    ima_api_key       TEXT NOT NULL DEFAULT '',
    ima_skill_prompt  TEXT NOT NULL DEFAULT '',
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER ima_settings_set_updated_at
    BEFORE UPDATE ON ima_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- gen_settings  -  per-type generation strategy prompts
--
-- One row per generation type (plan / content / quiz).  Each row's
-- ``strategy`` text is appended to the LLM prompt when generating that
-- type of content, letting users steer generation without code changes.
-- ---------------------------------------------------------------------------
CREATE TABLE gen_settings (
    gen_type          TEXT PRIMARY KEY CHECK (gen_type IN ('plan', 'content', 'quiz')),
    strategy          TEXT NOT NULL DEFAULT '',
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER gen_settings_set_updated_at
    BEFORE UPDATE ON gen_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- model_settings  -  single-row table for LLM (Ark/OpenAI 兼容) connection
--
-- API Key / 模型 / Base URL 在网页「模型设置」中配置并保存到此表。
-- 空值回退到 ARK_* 环境变量及内置默认值，因此环境变量仍可作为新部署的
-- 初始配置。One row (id=1) per deployment.
-- ---------------------------------------------------------------------------
CREATE TABLE model_settings (
    id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    api_key     TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    base_url    TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER model_settings_set_updated_at
    BEFORE UPDATE ON model_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
