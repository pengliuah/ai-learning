"""PostgreSQL connection pool and schema initialization.

Provides a lazily-created ``ConnectionPool`` (psycopg3) shared by the store
layer, plus an idempotent ``init_schema()`` that creates the database (if
missing) and applies ``db/schema.sql`` when the ``plans`` table does not yet
exist.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import BACKEND_DIR, settings

logger = logging.getLogger(__name__)

SCHEMA_PATH = BACKEND_DIR / "db" / "schema.sql"

_pool: ConnectionPool | None = None

# Cached schema-init status so we only attempt the PG connection once.
#   None  = not attempted yet
#   True  = schema verified/applied successfully
#   False = attempt failed (PG unreachable or error)
_schema_ok: bool | None = None


def get_pool() -> ConnectionPool:
    """Lazily create and return the shared connection pool."""
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured")
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=10,
            open=True,
            timeout=5,
        )
        logger.info("db pool created for %s", settings.database_url.split("/")[-1] or "?")
    return _pool


def close_pool() -> None:
    """Close and discard the pool (tests, graceful shutdown)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def db_conn():
    """Yield a pooled connection configured for dict-row access."""
    with get_pool().connection() as conn:
        conn.row_factory = dict_row
        yield conn


def _ensure_database() -> None:
    """Create the target database if it does not yet exist.

    Connects to the ``postgres`` maintenance database (CREATE DATABASE
    cannot run inside a transaction or while connected to the target).
    """
    params = conninfo_to_dict(settings.database_url)
    dbname = params.get("dbname") or "zhixue"
    admin_params = {**params, "dbname": "postgres"}
    with psycopg.connect(
        **admin_params, autocommit=True, connect_timeout=3
    ) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{dbname}"')
            logger.info("created database %s", dbname)


def _ddl_only(sql: str) -> str:
    """Strip psql meta-commands from schema.sql, keeping only the DDL.

    schema.sql begins with ``\\gexec`` / ``\\connect`` lines for one-shot
    ``psql -f`` usage.  psycopg3 cannot execute those, so everything up to
    and including the ``\\connect`` meta-command line is removed.  Comment
    lines that merely mention ``\\connect`` are skipped over.
    """
    lines = sql.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("\\connect"):
            return "\n".join(lines[i + 1:])
    return sql


def _migrate_auth_tables(conn: psycopg.Connection) -> None:
    """Add the account-system tables and migrate existing data (idempotent).

    Runs inside ``init_schema`` on the "plans exists" path. For old
    deployments this creates ``users``/``refresh_tokens``, bootstraps the
    admin account, scopes ``plans`` to it, and moves the old global
    ``model_settings``/``ima_settings``/``gen_settings`` rows into per-user
    tables (admin keeps them), dropping the old tables. On a fresh database
    every step is a no-op because ``schema.sql`` already defines everything.
    """
    if not conn.execute("SELECT to_regclass('public.users')").fetchone()[0]:
        conn.execute(
            """CREATE TABLE users (
                   id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                   username       TEXT NOT NULL UNIQUE,
                   email          TEXT UNIQUE,
                   password_hash  TEXT NOT NULL,
                   role           TEXT NOT NULL DEFAULT 'user'
                                  CHECK (role IN ('admin', 'user')),
                   wechat_unionid TEXT UNIQUE,
                   wechat_openid  TEXT,
                   created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                   updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
        conn.execute(
            """CREATE TRIGGER users_set_updated_at
               BEFORE UPDATE ON users
               FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
        )
        logger.info("init_schema: users table added")

    if not conn.execute("SELECT to_regclass('public.refresh_tokens')").fetchone()[0]:
        conn.execute(
            """CREATE TABLE refresh_tokens (
                   id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                   user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                   token_hash TEXT NOT NULL UNIQUE,
                   expires_at TIMESTAMPTZ NOT NULL,
                   revoked    BOOLEAN NOT NULL DEFAULT false,
                   created_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
        conn.execute("CREATE INDEX idx_refresh_tokens_user ON refresh_tokens (user_id)")
        logger.info("init_schema: refresh_tokens table added")

    if not conn.execute("SELECT to_regclass('public.token_usage')").fetchone()[0]:
        conn.execute(
            """CREATE TABLE token_usage (
                   id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                   user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                   gen_type      TEXT NOT NULL DEFAULT '',
                   model         TEXT NOT NULL DEFAULT '',
                   input_tokens  INTEGER NOT NULL DEFAULT 0,
                   output_tokens INTEGER NOT NULL DEFAULT 0,
                   total_tokens  INTEGER NOT NULL DEFAULT 0,
                   kind          TEXT NOT NULL DEFAULT 'llm',
                   created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
        conn.execute(
            "CREATE INDEX idx_token_usage_user_created ON token_usage (user_id, created_at)"
        )
        logger.info("init_schema: token_usage table added")

    # 大模型/嵌入模型分别统计 (幂等): kind = 'llm' | 'embedding', 旧行回填 llm
    conn.execute(
        "ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'llm'"
    )

    if not conn.execute("SELECT to_regclass('public.annotations')").fetchone()[0]:
        conn.execute(
            """CREATE TABLE annotations (
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
               )"""
        )
        conn.execute(
            """CREATE TRIGGER annotations_set_updated_at
               BEFORE UPDATE ON annotations
               FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
        )
        conn.execute(
            "CREATE INDEX idx_annotations_user_plan ON annotations (user_id, plan_id)"
        )
        logger.info("init_schema: annotations table added")

    # 学习资料附件 (全模态转写): 上传的原始文件 + 转写出的 markdown 文本。
    # 原始文件存文件系统 (attachments_dir), 库里只存相对路径 path;
    # 转写在后台异步进行, transcript_status: pending/running/done/failed。
    if not conn.execute("SELECT to_regclass('public.attachments')").fetchone()[0]:
        conn.execute(
            """CREATE TABLE attachments (
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
               )"""
        )
        conn.execute(
            """CREATE TRIGGER attachments_set_updated_at
               BEFORE UPDATE ON attachments
               FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
        )
        conn.execute(
            "CREATE INDEX idx_attachments_user ON attachments (user_id, created_at)"
        )
        logger.info("init_schema: attachments table added")

    # 同文件转写复用: sha256 指纹列 (幂等)。上传时发现同用户已有解析完成的
    # 同内容文件, 直接把转写文本抄给新行, 不再调多模态模型。
    if not conn.execute(
        """SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'attachments'
             AND column_name = 'sha256'"""
    ).fetchone():
        conn.execute("ALTER TABLE attachments ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_attachments_user_sha ON attachments (user_id, sha256)"
        )
        logger.info("init_schema: attachments.sha256 added (同文件转写复用)")

    # 多选题支持: questions.type 增加 mcq_multi + answers 列 (幂等, 老库也升级)。
    # 内联 CHECK 约束的默认名是 questions_type_check。
    if conn.execute("SELECT to_regclass('public.questions')").fetchone()[0]:
        conn.execute("ALTER TABLE questions DROP CONSTRAINT IF EXISTS questions_type_check")
        conn.execute(
            """ALTER TABLE questions
               ADD CONSTRAINT questions_type_check
               CHECK (type IN ('mcq', 'mcq_multi', 'short'))"""
        )
        conn.execute(
            """ALTER TABLE questions
               ADD COLUMN IF NOT EXISTS answers JSONB NOT NULL DEFAULT '[]'::jsonb"""
        )
        logger.info("init_schema: questions upgraded for mcq_multi")

    # 批改策略: user_gen_settings.gen_type 增加 grade (幂等, 老库也升级)。
    if conn.execute("SELECT to_regclass('public.user_gen_settings')").fetchone()[0]:
        conn.execute("ALTER TABLE user_gen_settings DROP CONSTRAINT IF EXISTS user_gen_settings_gen_type_check")
        conn.execute(
            """ALTER TABLE user_gen_settings
               ADD CONSTRAINT user_gen_settings_gen_type_check
               CHECK (gen_type IN ('plan', 'content', 'quiz', 'grade'))"""
        )
        logger.info("init_schema: user_gen_settings upgraded for grade strategy")

    for table, ddl, trigger in (
        ("user_ima_settings", """CREATE TABLE user_ima_settings (
               user_id           UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
               ima_client_id     TEXT NOT NULL DEFAULT '',
               ima_api_key       TEXT NOT NULL DEFAULT '',
               ima_skill_prompt  TEXT NOT NULL DEFAULT '',
               updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
           )""", "user_ima_settings"),
        ("user_gen_settings", """CREATE TABLE user_gen_settings (
               user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               gen_type          TEXT NOT NULL CHECK (gen_type IN ('plan', 'content', 'quiz', 'grade')),
               strategy          TEXT NOT NULL DEFAULT '',
               updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
               PRIMARY KEY (user_id, gen_type)
           )""", "user_gen_settings"),
        ("user_model_settings", """CREATE TABLE user_model_settings (
               user_id             UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
               api_key             TEXT NOT NULL DEFAULT '',
               model               TEXT NOT NULL DEFAULT '',
               base_url            TEXT NOT NULL DEFAULT '',
               max_tokens          INTEGER NOT NULL DEFAULT 8192,
               embedding_api_key   TEXT NOT NULL DEFAULT '',
               embedding_model     TEXT NOT NULL DEFAULT '',
               embedding_base_url  TEXT NOT NULL DEFAULT '',
               updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
           )""", "user_model_settings"),
        ("user_memory_profile", """CREATE TABLE user_memory_profile (
               user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
               profile    TEXT NOT NULL DEFAULT '',
               updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
           )""", "user_memory_profile"),
        ("memory_housekeeping", """CREATE TABLE memory_housekeeping (
               user_id     UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
               last_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
           )""", "memory_housekeeping"),
    ):
        if not conn.execute(f"SELECT to_regclass('public.{table}')").fetchone()[0]:
            conn.execute(ddl)
            conn.execute(
                f"""CREATE TRIGGER {trigger}_set_updated_at
                    BEFORE UPDATE ON {trigger}
                    FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
            )
            logger.info("init_schema: %s table added", table)

    # 邀请制注册: 邀请码表 + users.invited_by 来源追溯 (幂等)。
    if not conn.execute("SELECT to_regclass('public.invite_codes')").fetchone()[0]:
        conn.execute(
            """CREATE TABLE invite_codes (
                   id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                   code       TEXT NOT NULL UNIQUE,
                   created_by UUID REFERENCES users(id) ON DELETE SET NULL,
                   max_uses   INTEGER NOT NULL DEFAULT 1,
                   used_count INTEGER NOT NULL DEFAULT 0,
                   expires_at TIMESTAMPTZ,
                   note       TEXT NOT NULL DEFAULT '',
                   disabled   BOOLEAN NOT NULL DEFAULT false,
                   created_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
        logger.info("init_schema: invite_codes table added")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS invited_by UUID")

    # Bootstrap the admin account (users table empty → first startup).
    admin_id = conn.execute(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1"
    ).fetchone()
    if admin_id is None:
        # Lazy import: auth -> store -> db would be circular at module level.
        from .auth import hash_password
        from .config import settings as app_settings

        admin_id = conn.execute(
            """INSERT INTO users (username, password_hash, role)
               VALUES (%s, %s, 'admin') RETURNING id""",
            (app_settings.admin_username, hash_password(app_settings.admin_password)),
        ).fetchone()
        logger.info(
            "init_schema: bootstrapped admin account %r (请登录后立即修改默认密码)",
            app_settings.admin_username,
        )
    admin_uuid = str(admin_id[0])  # tuple rows: this conn has no dict factory

    # Scope existing plans to the admin, then make the column NOT NULL.
    conn.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS user_id UUID")
    conn.execute(
        """UPDATE plans SET user_id = %s WHERE user_id IS NULL""", (admin_uuid,)
    )
    conn.execute("ALTER TABLE plans ALTER COLUMN user_id SET NOT NULL")
    has_user_fk = conn.execute(
        """SELECT 1 FROM pg_constraint
           WHERE conrelid = 'public.plans'::regclass AND contype = 'f'
             AND (SELECT attname FROM pg_attribute
                  WHERE attrelid = conrelid AND attnum = ANY(conkey)) = 'user_id'"""
    ).fetchone()
    if not has_user_fk:
        conn.execute(
            """ALTER TABLE plans ADD CONSTRAINT plans_user_fk
               FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"""
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_user ON plans (user_id)")

    # 首页计划列表手动排序：加列并对存量数据一次性回填（按 created_at）。
    # 回填只作用于「全部计划仍是默认 0」的用户，避免覆盖已拖拽过的顺序。
    conn.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0")

    # 学生画像允许用户手动修正: 修正后夜间整理不再覆盖
    if conn.execute("SELECT to_regclass('public.user_memory_profile')").fetchone()[0]:
        conn.execute(
            "ALTER TABLE user_memory_profile ADD COLUMN IF NOT EXISTS "
            "edited_by_user BOOLEAN NOT NULL DEFAULT false"
        )
    conn.execute(
        """UPDATE plans p SET sort_order = o.pos
           FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at, id) - 1 AS pos
                 FROM plans) o
           WHERE p.id = o.id
             AND p.user_id IN (SELECT user_id FROM plans GROUP BY user_id HAVING BOOL_AND(sort_order = 0))"""
    )

    # Move old global single-row settings to the admin's per-user rows, then
    # drop the old tables. Guarded by to_regclass so fresh DBs skip this.
    if conn.execute("SELECT to_regclass('public.model_settings')").fetchone()[0]:
        conn.execute(
            """INSERT INTO user_model_settings (user_id, api_key, model, base_url, max_tokens)
               SELECT %s, api_key, model, base_url, max_tokens FROM model_settings
               ON CONFLICT (user_id) DO NOTHING""",
            (admin_uuid,),
        )
        conn.execute("DROP TABLE model_settings")
        logger.info("init_schema: model_settings -> user_model_settings (admin)")
    if conn.execute("SELECT to_regclass('public.ima_settings')").fetchone()[0]:
        conn.execute(
            """INSERT INTO user_ima_settings (user_id, ima_client_id, ima_api_key, ima_skill_prompt)
               SELECT %s, ima_client_id, ima_api_key, ima_skill_prompt FROM ima_settings
               ON CONFLICT (user_id) DO NOTHING""",
            (admin_uuid,),
        )
        conn.execute("DROP TABLE ima_settings")
        logger.info("init_schema: ima_settings -> user_ima_settings (admin)")
    if conn.execute("SELECT to_regclass('public.gen_settings')").fetchone()[0]:
        conn.execute(
            """INSERT INTO user_gen_settings (user_id, gen_type, strategy)
               SELECT %s, gen_type, strategy FROM gen_settings
               ON CONFLICT (user_id, gen_type) DO NOTHING""",
            (admin_uuid,),
        )
        conn.execute("DROP TABLE gen_settings")
        logger.info("init_schema: gen_settings -> user_gen_settings (admin)")


def init_schema() -> None:
    """Create the database (if missing) and apply schema.sql.

    The result is cached: if the first attempt fails (PG unreachable), every
    subsequent call raises immediately without retrying the connection, so the
    app and test suite don't block on repeated timeouts.
    """
    global _schema_ok
    if _schema_ok is True:
        return
    if _schema_ok is False:
        raise RuntimeError("schema init previously failed (PG unreachable?)")
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    try:
        _ensure_database()
        with psycopg.connect(
            settings.database_url, autocommit=True, connect_timeout=3
        ) as conn:
            exists = conn.execute(
                "SELECT to_regclass('public.plans')"
            ).fetchone()[0]
            if not exists:
                sql = _ddl_only(SCHEMA_PATH.read_text(encoding="utf-8"))
                conn.execute(sql)
                logger.info("init_schema: schema applied from %s", SCHEMA_PATH.name)
            else:
                logger.debug("init_schema: plans table exists, skipping")

                # 1. Create ima_settings if missing.
                if not conn.execute(
                    "SELECT to_regclass('public.ima_settings')"
                ).fetchone()[0]:
                    conn.execute(
                        """CREATE TABLE ima_settings (
                               id                INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                               ima_client_id     TEXT NOT NULL DEFAULT '',
                               ima_api_key       TEXT NOT NULL DEFAULT '',
                               ima_skill_prompt  TEXT NOT NULL DEFAULT '',
                               updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
                           )"""
                    )
                    conn.execute(
                        """CREATE TRIGGER ima_settings_set_updated_at
                           BEFORE UPDATE ON ima_settings
                           FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
                    )
                    logger.info("init_schema: ima_settings table added")

                # 2. Create gen_settings if missing (with 3 default rows).
                if not conn.execute(
                    "SELECT to_regclass('public.gen_settings')"
                ).fetchone()[0]:
                    conn.execute(
                        """CREATE TABLE gen_settings (
                               gen_type          TEXT PRIMARY KEY CHECK (gen_type IN ('plan', 'content', 'quiz')),
                               strategy          TEXT NOT NULL DEFAULT '',
                               updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
                           )"""
                    )
                    conn.execute(
                        """CREATE TRIGGER gen_settings_set_updated_at
                           BEFORE UPDATE ON gen_settings
                           FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
                    )
                    conn.execute(
                        """INSERT INTO gen_settings (gen_type) VALUES
                           ('plan'), ('content'), ('quiz')
                           ON CONFLICT DO NOTHING"""
                    )
                    logger.info("init_schema: gen_settings table added")

                # 3. Migrate data from old app_settings table if it exists,
                #    then drop it. (Tables must already exist -- step 1+2.)
                if conn.execute(
                    "SELECT to_regclass('public.app_settings')"
                ).fetchone()[0]:
                    cur = conn.cursor(row_factory=dict_row)
                    old_row = cur.execute(
                        "SELECT * FROM app_settings WHERE id = 1"
                    ).fetchone()
                    if old_row:
                        conn.execute(
                            """INSERT INTO ima_settings (id, ima_client_id, ima_api_key, ima_skill_prompt)
                               VALUES (1, %s, %s, %s)
                               ON CONFLICT (id) DO UPDATE SET
                                   ima_client_id = EXCLUDED.ima_client_id,
                                   ima_api_key = EXCLUDED.ima_api_key,
                                   ima_skill_prompt = EXCLUDED.ima_skill_prompt""",
                            (old_row["ima_client_id"], old_row["ima_api_key"],
                             old_row["ima_skill_prompt"]),
                        )
                        conn.execute(
                            """INSERT INTO gen_settings (gen_type, strategy)
                               VALUES ('plan', %s)
                               ON CONFLICT (gen_type) DO UPDATE SET strategy = EXCLUDED.strategy""",
                            (old_row["regen_strategy"],),
                        )
                    conn.execute("DROP TABLE app_settings")
                    logger.info("init_schema: migrated app_settings -> ima_settings + gen_settings")

                # 4. Create model_settings if missing (LLM config saved from
                #    the web UI; empty values fall back to ARK_* env vars).
                if not conn.execute(
                    "SELECT to_regclass('public.model_settings')"
                ).fetchone()[0]:
                    conn.execute(
                        """CREATE TABLE model_settings (
                               id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                               api_key     TEXT NOT NULL DEFAULT '',
                               model       TEXT NOT NULL DEFAULT '',
                               base_url    TEXT NOT NULL DEFAULT '',
                               max_tokens  INTEGER NOT NULL DEFAULT 8192,
                               updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                           )"""
                    )
                    conn.execute(
                        """CREATE TRIGGER model_settings_set_updated_at
                           BEFORE UPDATE ON model_settings
                           FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
                    )
                    logger.info("init_schema: model_settings table added")

                conn.execute(
                    """ALTER TABLE model_settings
                       ADD COLUMN IF NOT EXISTS max_tokens INTEGER NOT NULL DEFAULT 8192"""
                )

            # Account system: users/refresh_tokens/per-user settings +
            # plans.user_id scoping + legacy global-settings migration.
            # Always run (all steps idempotent, no-ops on a fresh DB) so the
            # bootstrap admin is created on both fresh and existing databases.
            # Runs AFTER the legacy steps above: it moves (and drops) the old
            # global settings tables once they may have been recreated.
            _migrate_auth_tables(conn)

            # 向量模型配置 (embedding): 老库补列 (幂等)。
            # 模型名必填才启用; Key / Base URL 留空时运行期回退到大模型的对应值。
            conn.execute(
                """ALTER TABLE user_model_settings
                   ADD COLUMN IF NOT EXISTS embedding_api_key TEXT NOT NULL DEFAULT '',
                   ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT '',
                   ADD COLUMN IF NOT EXISTS embedding_base_url TEXT NOT NULL DEFAULT ''"""
            )

            # 多模态模型配置 (vision, 全模态转写附件用): 老库补列 (幂等)。
            # 模型名必填才启用; Key / Base URL 留空时回退到大模型的对应值。
            conn.execute(
                """ALTER TABLE user_model_settings
                   ADD COLUMN IF NOT EXISTS vision_api_key TEXT NOT NULL DEFAULT '',
                   ADD COLUMN IF NOT EXISTS vision_model TEXT NOT NULL DEFAULT '',
                   ADD COLUMN IF NOT EXISTS vision_base_url TEXT NOT NULL DEFAULT ''"""
            )

            # 长期记忆总开关 (幂等): 关掉后教练对话不写入/不召回。
            if not conn.execute(
                "SELECT to_regclass('public.user_memory_settings')"
            ).fetchone()[0]:
                conn.execute(
                    """CREATE TABLE user_memory_settings (
                           user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                           enabled    BOOLEAN NOT NULL DEFAULT true,
                           updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                       )"""
                )
                conn.execute(
                    """CREATE TRIGGER user_memory_settings_set_updated_at
                       BEFORE UPDATE ON user_memory_settings
                       FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
                )
                logger.info("init_schema: user_memory_settings table added")
        _schema_ok = True
    except Exception:
        _schema_ok = False
        raise


def truncate_all() -> None:
    """Delete every row (used by tests to reset state between cases).

    TRUNCATE users CASCADE reaches every account-scoped table (plans and its
    children, refresh_tokens, per-user settings) via the foreign-key
    ON DELETE CASCADE chain.
    """
    with db_conn() as conn:
        conn.execute("TRUNCATE users CASCADE")
