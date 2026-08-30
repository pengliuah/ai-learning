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
                   created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
        conn.execute(
            "CREATE INDEX idx_token_usage_user_created ON token_usage (user_id, created_at)"
        )
        logger.info("init_schema: token_usage table added")

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
               gen_type          TEXT NOT NULL CHECK (gen_type IN ('plan', 'content', 'quiz')),
               strategy          TEXT NOT NULL DEFAULT '',
               updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
               PRIMARY KEY (user_id, gen_type)
           )""", "user_gen_settings"),
        ("user_model_settings", """CREATE TABLE user_model_settings (
               user_id     UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
               api_key     TEXT NOT NULL DEFAULT '',
               model       TEXT NOT NULL DEFAULT '',
               base_url    TEXT NOT NULL DEFAULT '',
               max_tokens  INTEGER NOT NULL DEFAULT 8192,
               updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
           )""", "user_model_settings"),
    ):
        if not conn.execute(f"SELECT to_regclass('public.{table}')").fetchone()[0]:
            conn.execute(ddl)
            conn.execute(
                f"""CREATE TRIGGER {trigger}_set_updated_at
                    BEFORE UPDATE ON {trigger}
                    FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
            )
            logger.info("init_schema: %s table added", table)

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
