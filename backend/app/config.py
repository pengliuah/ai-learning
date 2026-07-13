from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"

ARK_BASE_URL_DEFAULT = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL_DEFAULT = "doubao-1.5-pro-32k"

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    ark_api_key: str | None = None
    ark_base_url: str = ARK_BASE_URL_DEFAULT
    ark_model: str = ARK_MODEL_DEFAULT
    log_level: str = "INFO"


settings = Settings()


def setup_logging() -> None:
    """Configure the ``app`` logger hierarchy.

    Called once from ``app/__init__.py`` so every module can just do
    ``logging.getLogger(__name__)`` and inherit the handler + format.
    Integrates with uvicorn's own logging on the same stderr stream.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    if not app_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
        app_logger.addHandler(handler)
    app_logger.propagate = False


def is_configured() -> bool:
    return bool(settings.ark_api_key)
