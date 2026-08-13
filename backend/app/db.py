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
                               updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                           )"""
                    )
                    conn.execute(
                        """CREATE TRIGGER model_settings_set_updated_at
                           BEFORE UPDATE ON model_settings
                           FOR EACH ROW EXECUTE FUNCTION set_updated_at()"""
                    )
                    logger.info("init_schema: model_settings table added")
        _schema_ok = True
    except Exception:
        _schema_ok = False
        raise


def truncate_all() -> None:
    """Delete every row (used by tests to reset state between cases).

    TRUNCATE plans CASCADE reaches all child tables via the foreign-key
    ON DELETE CASCADE chain.
    """
    with db_conn() as conn:
        conn.execute("TRUNCATE plans CASCADE")
