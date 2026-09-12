from __future__ import annotations

import logging
import secrets
import sys
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL_DEFAULT = ""  # e.g. postgresql://user:pass@host:5432/zhixue

# Unified log format, e.g.:
#   2026-07-26 11:36:04 | 36.163.166.53:13700 | INFO     | app.main | <message>
# The `client` (ip:port) field is injected per-record by ClientContextFilter
# from the request-scoped context var set by AccessLogMiddleware; it is "-"
# for lines emitted outside any request (startup, shutdown, etc.).
LOG_FORMAT = "%(asctime)s | %(client)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Per-request client "ip:port". Set by AccessLogMiddleware around the whole
# ASGI call so logs emitted inside endpoints (and SSE generators) carry it.
client_addr_var: ContextVar[str] = ContextVar("client_addr", default="-")

# 日志时间统一用东八区 (不依赖容器/系统 TZ 设置)
_CST = timezone(timedelta(hours=8))


def _cst_time(*args) -> datetime:
    """logging.Formatter.converter: 把时间戳转成东八区。"""
    return (datetime.fromtimestamp(args[0], tz=_CST) if args else datetime.now(_CST)).timetuple()


class ClientContextFilter(logging.Filter):
    """Attach the current request's client ip:port to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.client = client_addr_var.get()
        return True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # NOTE: 模型 (LLM) 连接配置不在这里——它按用户存在数据库
    # user_model_settings 表（网页「模型设置」页），环境变量不是配置来源。
    log_level: str = "INFO"
    database_url: str = DATABASE_URL_DEFAULT
    # LLM 单次调用超时秒数: 上游挂起时避免 SSE 永久等待
    llm_request_timeout: int = 180

    # 长期记忆夜间整理: 合并重复/标记过时/刷新学生画像。
    # 关闭用 MEMORY_HOUSEKEEPING=false; 间隔小时数可用环境变量覆盖。
    memory_housekeeping: bool = True
    memory_housekeeping_interval_hours: int = 6

    # Auth: JWT secret for access tokens. When unset, a random secret is
    # generated at startup -- restarts then invalidate all access tokens
    # (refresh tokens still work), so set JWT_SECRET for stable sessions.
    jwt_secret: str = ""
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    # Bootstrap admin, created only when the users table is empty.
    admin_username: str = "admin"
    admin_password: str = "admin123"


settings = Settings()

if not settings.jwt_secret:
    settings.jwt_secret = secrets.token_urlsafe(48)
    logging.getLogger(__name__).warning(
        "JWT_SECRET 未设置，已生成临时密钥：重启后所有 access token 失效（refresh token 仍可用）。"
    )
if settings.admin_username == "admin" and settings.admin_password == "admin123":
    logging.getLogger(__name__).warning(
        "使用默认管理员引导配置（admin/admin123），仅用于首次建号，请登录后立即修改密码。"
    )


def _make_handler() -> logging.Handler:
    """A stderr handler with the unified format + client context filter."""
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
    formatter.converter = _cst_time  # type: ignore[assignment]
    handler.setFormatter(formatter)
    handler.addFilter(ClientContextFilter())
    return handler


def setup_logging() -> None:
    """Configure unified logging for the ``app`` hierarchy and uvicorn.

    Called once from ``app/__init__.py`` so every module can just do
    ``logging.getLogger(__name__)`` and inherit the handler + format.

    uvicorn runs its own ``configure_logging()`` in ``Config.load()`` before
    importing the app, so this runs after it and can override uvicorn's default
    formatters/handlers. All logs share one format on stderr:
    ``DATE | ip:port | LEVEL | name | message``.

    Level semantics (preserved from the original setup):
      - ``app.*`` follow ``settings.log_level`` (the ``LOG_LEVEL`` env var).
      - uvicorn's own loggers keep the level uvicorn assigned them; only their
        formatter/handler is replaced.
      - access logs (``app.access``, emitted by AccessLogMiddleware) mirror
        uvicorn.access's level so they stay visible at the default INFO even
        when ``LOG_LEVEL=WARNING`` -- matching the previous uvicorn.access
        behaviour -- and are not subject to the ``app`` logger's level.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = _make_handler()

    # Application logger hierarchy: app.main, app.agent, app.access, ...
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    app_logger.handlers = [handler]
    app_logger.propagate = False

    # uvicorn lifecycle/startup messages: reformat only, keep uvicorn's level.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.asgi"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = [handler]
        uv_logger.propagate = False

    # Access logging is owned by AccessLogMiddleware (unified format). Mirror
    # uvicorn.access's level (default INFO) so access logs stay independent of
    # the app level, then silence uvicorn's built-in access logger so each
    # request is logged exactly once.
    uv_access = logging.getLogger("uvicorn.access")
    access_level = uv_access.level or logging.INFO
    uv_access.disabled = True

    app_access = logging.getLogger("app.access")
    app_access.setLevel(access_level)
    app_access.handlers = [handler]
    app_access.propagate = False
