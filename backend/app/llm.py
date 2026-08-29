from __future__ import annotations

from langchain_openai import ChatOpenAI

from . import store
from .config import settings


def build_chat_model(user_id: str, **kwargs) -> ChatOpenAI:
    """ChatOpenAI pointed at the configured OpenAI-compatible endpoint.

    Connection settings come from the user's ``user_model_settings`` DB row
    (saved via the web UI) -- the single source of truth. Raises when the
    user has not configured an API key yet. Extra ``kwargs`` override.
    """
    api_key, model, base_url, max_tokens = store.get_llm_config(user_id)
    if not api_key:
        raise RuntimeError("model API key is not configured")
    params = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "max_tokens": max_tokens,
        "request_timeout": settings.llm_request_timeout,
        "streaming": False,
    }
    params.update(kwargs)
    return ChatOpenAI(**params)


def build_streaming_model(user_id: str, **kwargs) -> ChatOpenAI:
    return build_chat_model(user_id, streaming=True, **kwargs)
