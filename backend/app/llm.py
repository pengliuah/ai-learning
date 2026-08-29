from __future__ import annotations

from langchain_openai import ChatOpenAI

from . import store


def build_chat_model(user_id: str, **kwargs) -> ChatOpenAI:
    """ChatOpenAI pointed at the configured OpenAI-compatible endpoint.

    Connection settings come from the user's ``user_model_settings`` DB row
    (saved via the web UI), with ARK_* environment variables as fallback for
    empty fields. Extra ``kwargs`` override the effective config.
    """
    api_key, model, base_url, max_tokens = store.get_llm_config(user_id)
    if not api_key:
        raise RuntimeError("model API key is not configured")
    params = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "max_tokens": max_tokens,
        "streaming": False,
    }
    params.update(kwargs)
    return ChatOpenAI(**params)


def build_streaming_model(**kwargs) -> ChatOpenAI:
    return build_chat_model(streaming=True, **kwargs)
