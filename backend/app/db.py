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
