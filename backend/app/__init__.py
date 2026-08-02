"""zhixue-backend: AI learning agent (FastAPI + LangChain)."""

import logging

from .config import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

# Initialize database schema (idempotent: only creates tables if missing).
# Wrapped so the app still starts (health endpoint works) even if PG is
# unreachable at boot; store operations will then raise a clear error.
try:
    from .db import init_schema

    init_schema()
except Exception as exc:
    logger.error("DB schema init failed: %s", exc)