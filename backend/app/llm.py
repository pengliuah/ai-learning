from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI

from . import store
from .config import settings

logger = logging.getLogger(__name__)


def build_chat_model(user_id: str, **kwargs) -> ChatOpenAI:
    """ChatOpenAI pointed at the configured OpenAI-compatible endpoint.

    Connection settings come from the user's ``user_model_settings`` DB row
    (saved via the web UI) -- the single source of truth. Raises when the
    user has not configured an API key yet. Extra ``kwargs`` override.
    """
    api_key, model, base_url, max_tokens = store.get_llm_config(user_id)
    if not api_key:
        raise RuntimeError("model API key is not configured")
    logger.info(
        "build_chat_model: user=%s model=%s base_url=%s max_tokens=%s key=%s...(已隐藏)",
        user_id, model, base_url, max_tokens, api_key[:6],
    )
    params = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "max_tokens": max_tokens,
        "request_timeout": settings.llm_request_timeout,
        "streaming": False,
        # 流式时在最后一个 chunk 附带 usage_metadata (stream_options.include_usage),
        # 供 agent 层统计 token 用量; 非流式调用不受影响。
        "stream_usage": True,
    }
    params.update(kwargs)
    return ChatOpenAI(**params)


def build_streaming_model(user_id: str, **kwargs) -> ChatOpenAI:
    return build_chat_model(user_id, streaming=True, **kwargs)


def build_vision_model(user_id: str, **kwargs) -> ChatOpenAI:
    """ChatOpenAI pointed at the user's omni-modal (vision) endpoint.

    配置来自 user_model_settings 的 vision_* 字段；Key / Base URL 留空时
    回退到大模型的对应值（主模型本身是全模态时零配置可用）。模型名未配置
    则抛错，由调用方给用户明确的引导信息。
    """
    from .store import get_vision_config

    api_key, model, base_url = get_vision_config(user_id)
    if not model:
        raise RuntimeError("多模态模型未配置：请在「模型设置 → 多模态模型」中填写模型名（或直接使用全模态大模型）")
    logger.info(
        "build_vision_model: user=%s model=%s base_url=%s key=%s...(已隐藏)",
        user_id, model, base_url, api_key[:6] if api_key else "-",
    )
    params = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "request_timeout": settings.llm_request_timeout,
        "streaming": False,
        "stream_usage": True,
        # 转写输出可能很长 (整份 PDF 资料), 不能用大模型的 max_tokens 截断
        "max_tokens": 8192,
    }
    params.update(kwargs)
    return ChatOpenAI(**params)
